#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any


SUPPORTED_LANGS = {
    "python": {"tester": "tester.py", "runner": "python"},
    "javascript": {"tester": "tester.js", "runner": "node"},
    "typescript": {"tester": "tester.ts", "runner": "node"},
}
RESULT_ERROR = {"status": "error", "passed": [], "failed": []}
EXPECT_RE = re.compile(r"^\s*#\s*expect_(stdout|stderr):\s*(.+?)\s*$")


class DiscoveryError(Exception):
    pass


@dataclass(frozen=True)
class TestCase:
    id: str
    line: int
    kind: str
    args: list[Any]
    expected: Any = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "line": self.line,
            "kind": self.kind,
            "args": self.args,
            "expected": self.expected,
            "expect_stdout": self.expect_stdout,
            "expect_stderr": self.expect_stderr,
        }


def normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, tuple | list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise DiscoveryError("dictionary keys must be strings")
            normalized[key] = normalize_value(item)
        return normalized
    raise DiscoveryError(f"unsupported literal value: {type(value).__name__}")


def literal_from_node(node: ast.AST) -> Any:
    try:
        value = ast.literal_eval(node)
    except Exception as exc:
        raise DiscoveryError("unsupported literal expression") from exc
    return normalize_value(value)


def parse_expectations(lines: list[str], test_line: int) -> tuple[str | None, str | None]:
    stdout = None
    stderr = None
    index = test_line - 2
    while index >= 0:
        raw = lines[index]
        if not raw.strip():
            break
        match = EXPECT_RE.match(raw)
        if not match:
            break
        stream, literal = match.groups()
        try:
            value = ast.literal_eval(literal)
        except Exception as exc:
            raise DiscoveryError("invalid stdout/stderr expectation") from exc
        if not isinstance(value, str):
            raise DiscoveryError("stdout/stderr expectation must be a string")
        if stream == "stdout":
            if stdout is not None:
                raise DiscoveryError("duplicate stdout expectation")
            stdout = value
        else:
            if stderr is not None:
                raise DiscoveryError("duplicate stderr expectation")
            stderr = value
        index -= 1
    return stdout, stderr


def parse_entrypoint_call(node: ast.AST, entrypoint: str) -> list[Any]:
    if not isinstance(node, ast.Call):
        raise DiscoveryError("expected entrypoint call")
    if not isinstance(node.func, ast.Name) or node.func.id != entrypoint:
        raise DiscoveryError("assertion must call the configured entrypoint")
    if node.keywords:
        raise DiscoveryError("keyword arguments are unsupported")
    return [literal_from_node(arg) for arg in node.args]


def parse_assert(node: ast.Assert, entrypoint: str, lines: list[str]) -> TestCase:
    test = node.test
    kind: str
    args: list[Any]
    expected: Any = None

    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        if isinstance(test.ops[0], ast.Eq):
            kind = "eq"
        elif isinstance(test.ops[0], ast.NotEq):
            kind = "neq"
        else:
            raise DiscoveryError("unsupported comparison assertion")
        args = parse_entrypoint_call(test.left, entrypoint)
        expected = literal_from_node(test.comparators[0])
    elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        kind = "falsy"
        args = parse_entrypoint_call(test.operand, entrypoint)
    else:
        kind = "truthy"
        args = parse_entrypoint_call(test, entrypoint)

    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind=kind,
        args=args,
        expected=expected,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


def parse_raise_any(node: ast.Try, entrypoint: str, lines: list[str]) -> TestCase:
    if node.orelse or node.finalbody or len(node.body) != 2 or len(node.handlers) != 1:
        raise DiscoveryError("unsupported try block")
    call_stmt, assert_stmt = node.body
    if not isinstance(call_stmt, ast.Expr):
        raise DiscoveryError("raise-any block must call entrypoint first")
    args = parse_entrypoint_call(call_stmt.value, entrypoint)
    if (
        not isinstance(assert_stmt, ast.Assert)
        or not isinstance(assert_stmt.test, ast.Constant)
        or assert_stmt.test.value is not False
    ):
        raise DiscoveryError("raise-any block must assert False after entrypoint call")
    handler = node.handlers[0]
    catches_exception = (
        isinstance(handler.type, ast.Name)
        and handler.type.id == "Exception"
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Pass)
    )
    if not catches_exception:
        raise DiscoveryError("raise-any block must catch Exception and pass")
    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind="raises",
        args=args,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


def discover_in_body(body: list[ast.stmt], entrypoint: str, lines: list[str]) -> list[TestCase]:
    discovered: list[TestCase] = []
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines))
        elif isinstance(stmt, ast.Assert):
            discovered.append(parse_assert(stmt, entrypoint, lines))
        elif isinstance(stmt, ast.Try):
            discovered.append(parse_raise_any(stmt, entrypoint, lines))
        elif isinstance(stmt, ast.Pass):
            continue
        else:
            raise DiscoveryError(f"unsupported code at line {getattr(stmt, 'lineno', '?')}")
    return discovered


def assign_ids(test_cases: list[TestCase]) -> list[TestCase]:
    counts: dict[int, int] = {}
    for test_case in test_cases:
        counts[test_case.line] = counts.get(test_case.line, 0) + 1

    seen: dict[int, int] = {}
    assigned: list[TestCase] = []
    for test_case in test_cases:
        line_seen = seen.get(test_case.line, 0)
        seen[test_case.line] = line_seen + 1
        test_id = f"tests.py:{test_case.line}"
        if counts[test_case.line] > 1:
            test_id = f"{test_id}#{line_seen}"
        assigned.append(
            TestCase(
                id=test_id,
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                expected=test_case.expected,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
            )
        )
    return assigned


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    tests_path = tests_dir / "tests.py"
    try:
        source = tests_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryError("could not read tests.py") from exc
    try:
        tree = ast.parse(source, filename="tests.py")
    except SyntaxError as exc:
        raise DiscoveryError("could not parse tests.py") from exc
    lines = source.splitlines()
    return assign_ids(discover_in_body(tree.body, entrypoint, lines))


def make_result(status: str, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "passed": passed or [], "failed": failed or []}


def print_result(result: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return {"pass": 0, "fail": 1, "error": 2}[result["status"]]


def normalize_for_compare(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, tuple | list):
        return [normalize_for_compare(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_for_compare(item) for key, item in value.items()}
    return value


def resolve_python_callable(solution_path: Path, entrypoint: str) -> Any:
    spec = importlib.util.spec_from_file_location("babel_code_goat_solution", solution_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load solution")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidate = getattr(module, entrypoint, None)
    if callable(candidate):
        return candidate

    for _, obj in inspect.getmembers(module, inspect.isclass):
        method = getattr(obj, entrypoint, None)
        if callable(method):
            try:
                instance = obj()
            except Exception:
                continue
            bound = getattr(instance, entrypoint, None)
            if callable(bound):
                return bound
    raise RuntimeError("entrypoint not found")


def execute_python_tests(solution_path: Path, entrypoint: str, tests: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        callable_under_test = resolve_python_callable(solution_path, entrypoint)
    except Exception:
        return make_result("fail", [], [test["id"] for test in tests])

    passed: list[str] = []
    failed: list[str] = []
    for test in tests:
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        ok = False
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                raised = False
                try:
                    actual = callable_under_test(*test["args"])
                except Exception:
                    raised = True
                    actual = None
                if test["kind"] == "raises":
                    ok = raised
                elif raised:
                    ok = False
                elif test["kind"] == "eq":
                    ok = normalize_for_compare(actual) == test["expected"]
                elif test["kind"] == "neq":
                    ok = normalize_for_compare(actual) != test["expected"]
                elif test["kind"] == "truthy":
                    ok = bool(actual)
                elif test["kind"] == "falsy":
                    ok = not bool(actual)
        except Exception:
            ok = False

        if test.get("expect_stdout") is not None and stdout_buffer.getvalue() != test["expect_stdout"]:
            ok = False
        if test.get("expect_stderr") is not None and stderr_buffer.getvalue() != test["expect_stderr"]:
            ok = False

        if ok:
            passed.append(test["id"])
        else:
            failed.append(test["id"])
    return make_result("pass" if not failed else "fail", passed, failed)


def python_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    return f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = os.environ.get("BABEL_CODE_GOAT_ROOT", str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from babel_code_goat import execute_python_tests, print_result

PAYLOAD = {payload!r}

def main():
    if len(sys.argv) != 2:
        return print_result({{"status": "error", "passed": [], "failed": []}})
    data = json.loads(PAYLOAD)
    result = execute_python_tests(Path(sys.argv[1]), data["entrypoint"], data["tests"])
    return print_result(result)

if __name__ == "__main__":
    raise SystemExit(main())
"""


def javascript_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    return f"""#!/usr/bin/env node
const path = require("path");
const {{ pathToFileURL }} = require("url");
const payload = {payload};

function normalize(value) {{
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {{
    const out = {{}};
    for (const key of Object.keys(value).sort()) out[key] = normalize(value[key]);
    return out;
  }}
  return value;
}}

function deepEqual(a, b) {{
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}}

function findCallable(moduleValue, entrypoint) {{
  if (typeof moduleValue === "function" && moduleValue.name === entrypoint) return moduleValue;
  if (typeof moduleValue === "function") {{
    try {{
      const instance = new moduleValue();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
  }}
  if (moduleValue && typeof moduleValue[entrypoint] === "function") return moduleValue[entrypoint].bind(moduleValue);
  if (moduleValue && moduleValue.default && typeof moduleValue.default === "function" && moduleValue.default.name === entrypoint) return moduleValue.default;
  if (moduleValue && moduleValue.default && typeof moduleValue.default === "function") {{
    try {{
      const instance = new moduleValue.default();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
  }}
  if (moduleValue && moduleValue.default && typeof moduleValue.default[entrypoint] === "function") return moduleValue.default[entrypoint].bind(moduleValue.default);
  for (const value of Object.values(moduleValue || {{}})) {{
    if (typeof value !== "function") continue;
    if (value.name === entrypoint) return value;
    try {{
      const instance = new value();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
    if (typeof value[entrypoint] === "function") return value[entrypoint].bind(value);
  }}
  throw new Error("entrypoint not found");
}}

async function loadSolution(solutionPath) {{
  try {{
    return require(solutionPath);
  }} catch (error) {{
    return await import(pathToFileURL(solutionPath).href);
  }}
}}

async function main() {{
  if (process.argv.length !== 3) {{
    console.log(JSON.stringify({{status: "error", passed: [], failed: []}}));
    return 2;
  }}
  const solutionPath = path.resolve(process.argv[2]);
  let fn;
  try {{
    fn = findCallable(await loadSolution(solutionPath), payload.entrypoint);
  }} catch (error) {{
    console.log(JSON.stringify({{status: "fail", passed: [], failed: payload.tests.map(test => test.id)}}));
    return 1;
  }}

  const passed = [];
  const failed = [];
  for (const test of payload.tests) {{
    let stdout = "";
    let stderr = "";
    const oldOut = process.stdout.write;
    const oldErr = process.stderr.write;
    process.stdout.write = function(chunk, encoding, cb) {{ stdout += String(chunk); if (typeof cb === "function") cb(); return true; }};
    process.stderr.write = function(chunk, encoding, cb) {{ stderr += String(chunk); if (typeof cb === "function") cb(); return true; }};
    let ok = false;
    try {{
      let actual;
      let raised = false;
      try {{
        actual = fn(...test.args);
        if (actual && typeof actual.then === "function") actual = await actual;
      }} catch (error) {{
        raised = true;
      }}
      if (test.kind === "raises") ok = raised;
      else if (raised) ok = false;
      else if (test.kind === "eq") ok = deepEqual(actual, test.expected);
      else if (test.kind === "neq") ok = !deepEqual(actual, test.expected);
      else if (test.kind === "truthy") ok = !!actual;
      else if (test.kind === "falsy") ok = !actual;
    }} catch (error) {{
      ok = false;
    }} finally {{
      process.stdout.write = oldOut;
      process.stderr.write = oldErr;
    }}
    if (test.expect_stdout !== null && stdout !== test.expect_stdout) ok = false;
    if (test.expect_stderr !== null && stderr !== test.expect_stderr) ok = false;
    (ok ? passed : failed).push(test.id);
  }}
  const status = failed.length === 0 ? "pass" : "fail";
  console.log(JSON.stringify({{status, passed, failed}}));
  return status === "pass" ? 0 : 1;
}}

main().then(code => process.exit(code)).catch(() => {{
  console.log(JSON.stringify({{status: "error", passed: [], failed: []}}));
  process.exit(2);
}});
"""


def generate_tester(lang: str, entrypoint: str, tests_dir: Path) -> None:
    tests = discover_tests(tests_dir, entrypoint)
    filename = SUPPORTED_LANGS[lang]["tester"]
    if lang == "python":
        source = python_tester_source(entrypoint, tests)
    else:
        source = javascript_tester_source(entrypoint, tests)

    destination = tests_dir / filename
    fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=tests_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(source)
        os.replace(temp_name, destination)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def extract_tester_payload(tester: Path, lang: str) -> dict[str, Any]:
    source = tester.read_text(encoding="utf-8")
    if lang == "python":
        tree = ast.parse(source, filename=str(tester))
        for stmt in tree.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "PAYLOAD"
            ):
                value = ast.literal_eval(stmt.value)
                return json.loads(value)
    else:
        match = re.search(r"const payload = (\{.*?\});", source, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise DiscoveryError("tester payload not found")


def command_generate(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED_LANGS:
        sys.stderr.write(f"error: unsupported language: {args.lang}\n")
        return 1
    try:
        generate_tester(args.lang, args.entrypoint, Path(args.tests_dir))
    except Exception as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


def command_test(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED_LANGS:
        return print_result(RESULT_ERROR)
    tests_dir = Path(args.tests_dir)
    tester = tests_dir / SUPPORTED_LANGS[args.lang]["tester"]
    if not tester.exists():
        return print_result(RESULT_ERROR)
    try:
        payload = extract_tester_payload(tester, args.lang)
        discovered = [test.to_jsonable() for test in discover_tests(tests_dir, payload["entrypoint"])]
        if discovered != payload["tests"]:
            return print_result(RESULT_ERROR)
    except Exception:
        return print_result(RESULT_ERROR)
    if args.lang == "python":
        command = [sys.executable, str(tester), str(Path(args.solution_path))]
    else:
        command = ["node", str(tester), str(Path(args.solution_path))]
    try:
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent)
        env["BABEL_CODE_GOAT_ROOT"] = root
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    except Exception:
        return print_result(RESULT_ERROR)

    stdout = completed.stdout
    if stdout.count("\n") != 1:
        return print_result(RESULT_ERROR)
    line = stdout.rstrip("\n")
    try:
        result = json.loads(line)
    except json.JSONDecodeError:
        return print_result(RESULT_ERROR)
    if (
        not isinstance(result, dict)
        or list(result.keys()) != ["status", "passed", "failed"]
        or result.get("status") not in {"pass", "fail", "error"}
        or not isinstance(result.get("passed"), list)
        or not isinstance(result.get("failed"), list)
    ):
        return print_result(RESULT_ERROR)
    return print_result(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="babel_code_goat.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("tests_dir")
    generate.add_argument("--entrypoint", required=True)
    generate.add_argument("--lang", required=True)
    generate.set_defaults(func=command_generate)

    test = subparsers.add_parser("test")
    test.add_argument("solution_path")
    test.add_argument("tests_dir")
    test.add_argument("--lang", required=True)
    test.set_defaults(func=command_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
