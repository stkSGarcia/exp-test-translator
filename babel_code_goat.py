#!/usr/bin/env python3
"""babel_code_goat.py — test-harness translation engine and runner.

Requires Python 3.9+.

Commands:
  generate <tests_dir> --entrypoint <name> --lang <python|javascript|typescript>
  test     <solution>  <tests_dir> --lang <python|javascript|typescript>
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: str                          # temporary: raw line number; final: "tests.py:<n>[#k]"
    kind: Literal["eq", "ne", "truthy", "falsy", "raises"]
    args: list[Any]
    expected: Any = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _ast_to_value(node: ast.expr) -> Any:
    """Evaluate a constant-valued AST node to a Python value."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_ast_to_value(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return [_ast_to_value(e) for e in node.elts]  # tuple → list (no tuple in JSON)
    if isinstance(node, ast.Dict):
        return {_ast_to_value(k): _ast_to_value(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _ast_to_value(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError(f"Unsupported value in tests.py: {ast.dump(node)}")


def _to_json_value(v: Any) -> Any:
    """Recursively normalise to JSON-safe form (tuple → list)."""
    if isinstance(v, (list, tuple)):
        return [_to_json_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_json_value(vv) for k, vv in v.items()}
    return v


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_ANNO_RE = re.compile(r"#\s*expect_(stdout|stderr):\s*(.+)")


def parse_tests(source: str, entrypoint: str) -> list[TestCase]:
    """Parse tests.py source and return a list of TestCase objects."""
    tree = ast.parse(source)
    lines = source.splitlines()
    raw: list[TestCase] = []
    _collect_stmts(tree.body, lines, entrypoint, raw)

    # Assign proper IDs: "tests.py:<line>" or "tests.py:<line>#N" for collisions.
    # tc.id is stored as str(lineno) initially.
    line_counts: dict[int, int] = {}
    for tc in raw:
        n = int(tc.id)
        line_counts[n] = line_counts.get(n, 0) + 1
    line_seen: dict[int, int] = {}
    for tc in raw:
        n = int(tc.id)
        if line_counts[n] == 1:
            tc.id = f"tests.py:{n}"
        else:
            idx = line_seen.get(n, 0)
            tc.id = f"tests.py:{n}#{idx}"
            line_seen[n] = idx + 1
    return raw


def _collect_stmts(
    stmts: list[ast.stmt], lines: list[str], ep: str, out: list[TestCase]
) -> None:
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_stmts(stmt.body, lines, ep, out)
        elif isinstance(stmt, ast.ClassDef):
            _collect_stmts(stmt.body, lines, ep, out)
        elif isinstance(stmt, ast.If):
            _collect_stmts(stmt.body + stmt.orelse, lines, ep, out)
        elif isinstance(stmt, (ast.For, ast.While)):
            _collect_stmts(stmt.body + stmt.orelse, lines, ep, out)
        elif isinstance(stmt, ast.With):
            _collect_stmts(stmt.body, lines, ep, out)
        elif isinstance(stmt, ast.Try):
            tc = _match_raises(stmt, ep)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)
            else:
                _collect_stmts(stmt.body, lines, ep, out)
                for h in stmt.handlers:
                    _collect_stmts(h.body, lines, ep, out)
        elif isinstance(stmt, ast.Assert):
            tc = _match_assert(stmt, ep)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)


def _is_ep_call(node: ast.expr, ep: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == ep
    )


def _match_raises(node: ast.Try, ep: str) -> TestCase | None:
    """Match: try: EP(args); assert False \\n except Exception: pass"""
    if len(node.body) != 2 or len(node.handlers) != 1:
        return None
    h = node.handlers[0]
    if not (isinstance(h.type, ast.Name) and h.type.id == "Exception"):
        return None
    if not (len(h.body) == 1 and isinstance(h.body[0], ast.Pass)):
        return None
    s0, s1 = node.body
    if not (isinstance(s0, ast.Expr) and _is_ep_call(s0.value, ep)):
        return None
    if not (
        isinstance(s1, ast.Assert)
        and isinstance(s1.test, ast.Constant)
        and s1.test.value is False
    ):
        return None
    args = [_ast_to_value(a) for a in s0.value.args]
    return TestCase(id=str(node.lineno), kind="raises", args=args)


def _match_assert(node: ast.Assert, ep: str) -> TestCase | None:
    test = node.test
    # assert EP(args) == expected   or   assert EP(args) != expected
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
        and _is_ep_call(test.left, ep)
    ):
        args = [_ast_to_value(a) for a in test.left.args]
        exp = _ast_to_value(test.comparators[0])
        if isinstance(test.ops[0], ast.Eq):
            return TestCase(id=str(node.lineno), kind="eq", args=args, expected=exp)
        if isinstance(test.ops[0], ast.NotEq):
            return TestCase(id=str(node.lineno), kind="ne", args=args, expected=exp)
    # assert EP(args)
    if _is_ep_call(test, ep):
        return TestCase(
            id=str(node.lineno), kind="truthy",
            args=[_ast_to_value(a) for a in test.args],
        )
    # assert not EP(args)
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and _is_ep_call(test.operand, ep)
    ):
        return TestCase(
            id=str(node.lineno), kind="falsy",
            args=[_ast_to_value(a) for a in test.operand.args],
        )
    return None


def _attach_annotations(tc: TestCase, lineno: int, lines: list[str]) -> None:
    """Scan backwards from the line before lineno for expect_stdout/stderr annotations."""
    i = lineno - 2  # 0-indexed line immediately before the test
    while i >= 0:
        m = _ANNO_RE.match(lines[i].strip())
        if not m:
            break
        kind, raw_val = m.group(1), m.group(2).strip()
        parsed: str = ast.literal_eval(raw_val)
        if kind == "stdout" and tc.expect_stdout is None:
            tc.expect_stdout = parsed
        elif kind == "stderr" and tc.expect_stderr is None:
            tc.expect_stderr = parsed
        i -= 1


# ---------------------------------------------------------------------------
# Code generators
# ---------------------------------------------------------------------------

def emit_python(cases: list[TestCase], entrypoint: str) -> str:
    cases_data = [
        [tc.id, tc.kind, _to_json_value(tc.args), _to_json_value(tc.expected),
         tc.expect_stdout, tc.expect_stderr]
        for tc in cases
    ]
    cases_repr = repr(json.dumps(cases_data))
    ep_repr = json.dumps(entrypoint)

    return f"""\
#!/usr/bin/env python3
import sys, json, os, io, contextlib, importlib.util

ENTRYPOINT = {ep_repr}
CASES = json.loads({cases_repr})

def _deep_eq(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_deep_eq(a[k], b[k]) for k in a)
    return a == b

def _load_fn(sol_path, name):
    spec = importlib.util.spec_from_file_location("_sol", sol_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    obj = getattr(mod, name)
    if isinstance(obj, type):
        return getattr(obj(), name)
    return obj

def _run():
    sol_path = sys.argv[1]
    results_path = os.environ["_BCG_RESULTS_FILE"]
    try:
        fn = _load_fn(sol_path, ENTRYPOINT)
    except Exception:
        with open(results_path, "w") as f:
            json.dump({{"passed": [], "failed": [c[0] for c in CASES]}}, f)
        return
    passed, failed = [], []
    for tid, kind, args, expected, exp_out, exp_err in CASES:
        try:
            if kind == "raises":
                try:
                    fn(*args)
                    failed.append(tid)
                except Exception:
                    passed.append(tid)
                continue
            out_buf, err_buf = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                result = fn(*args)
            ok = True
            if kind == "eq":
                ok = _deep_eq(result, expected)
            elif kind == "ne":
                ok = not _deep_eq(result, expected)
            elif kind == "truthy":
                ok = bool(result)
            elif kind == "falsy":
                ok = not bool(result)
            if ok and exp_out is not None:
                ok = out_buf.getvalue() == exp_out
            if ok and exp_err is not None:
                ok = err_buf.getvalue() == exp_err
            (passed if ok else failed).append(tid)
        except Exception:
            failed.append(tid)
    with open(results_path, "w") as f:
        json.dump({{"passed": passed, "failed": failed}}, f)

_run()
"""


def emit_javascript(cases: list[TestCase], entrypoint: str) -> str:
    cases_json = json.dumps(
        [{"id": tc.id, "kind": tc.kind, "args": _to_json_value(tc.args),
          "expected": _to_json_value(tc.expected),
          "expectStdout": tc.expect_stdout, "expectStderr": tc.expect_stderr}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)

    return f"""\
'use strict';
const fs = require('fs');
const path = require('path');

const ENTRYPOINT = {ep_json};
const CASES = {cases_json};

function deepEq(a, b) {{
  if (Array.isArray(a) && Array.isArray(b)) {{
    return a.length === b.length && a.every((x, i) => deepEq(x, b[i]));
  }}
  if (a !== null && b !== null && typeof a === 'object' && !Array.isArray(a) &&
      typeof b === 'object' && !Array.isArray(b)) {{
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return ka.join('\\0') === kb.join('\\0') && ka.every(k => deepEq(a[k], b[k]));
  }}
  return a === b;
}}

function loadFn(sol, name) {{
  if (sol && typeof sol[name] === 'function') {{
    try {{
      const inst = new sol[name]();
      if (typeof inst[name] === 'function') return (...a) => inst[name](...a);
    }} catch (e) {{}}
    return (...a) => sol[name](...a);
  }}
  if (typeof sol === 'function') return (...a) => sol(...a);
  throw new Error('Cannot resolve entrypoint: ' + name);
}}

function captureCall(fn, args) {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  process.stdout.write = c => {{ stdout += c; return true; }};
  process.stderr.write = c => {{ stderr += c; return true; }};
  let result, threw = false;
  try {{ result = fn(...args); }} catch (e) {{ threw = true; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw }};
}}

function run() {{
  const solPath = process.argv[2];
  const resultsPath = process.env._BCG_RESULTS_FILE;
  const allIds = CASES.map(c => c.id);
  let fn;
  try {{
    const sol = require(path.resolve(solPath));
    fn = loadFn(sol, ENTRYPOINT);
  }} catch (e) {{
    fs.writeFileSync(resultsPath, JSON.stringify({{passed: [], failed: allIds}}));
    return;
  }}
  const passed = [], failed = [];
  for (const c of CASES) {{
    try {{
      if (c.kind === 'raises') {{
        let threw = false;
        try {{ fn(...c.args); }} catch (e) {{ threw = true; }}
        (threw ? passed : failed).push(c.id);
        continue;
      }}
      const {{ result, stdout, stderr, threw }} = captureCall(fn, c.args);
      if (threw) {{ failed.push(c.id); continue; }}
      let ok = true;
      if (c.kind === 'eq') ok = deepEq(result, c.expected);
      else if (c.kind === 'ne') ok = !deepEq(result, c.expected);
      else if (c.kind === 'truthy') ok = !!result;
      else if (c.kind === 'falsy') ok = !result;
      if (ok && c.expectStdout !== null) ok = stdout === c.expectStdout;
      if (ok && c.expectStderr !== null) ok = stderr === c.expectStderr;
      (ok ? passed : failed).push(c.id);
    }} catch (e) {{
      failed.push(c.id);
    }}
  }}
  fs.writeFileSync(resultsPath, JSON.stringify({{passed, failed}}));
}}

run();
"""


def emit_typescript(cases: list[TestCase], entrypoint: str) -> str:
    cases_json = json.dumps(
        [{"id": tc.id, "kind": tc.kind, "args": _to_json_value(tc.args),
          "expected": _to_json_value(tc.expected),
          "expectStdout": tc.expect_stdout, "expectStderr": tc.expect_stderr}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)

    return f"""\
import * as fs from 'fs';
import * as path from 'path';

const ENTRYPOINT: string = {ep_json};
interface Case {{
  id: string; kind: string; args: any[]; expected: any;
  expectStdout: string | null; expectStderr: string | null;
}}
const CASES: Case[] = {cases_json};

function deepEq(a: any, b: any): boolean {{
  if (Array.isArray(a) && Array.isArray(b)) {{
    return a.length === b.length && (a as any[]).every((x: any, i: number) => deepEq(x, b[i]));
  }}
  if (a !== null && b !== null && typeof a === 'object' && !Array.isArray(a) &&
      typeof b === 'object' && !Array.isArray(b)) {{
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return ka.join('\\0') === kb.join('\\0') && ka.every((k: string) => deepEq(a[k], b[k]));
  }}
  return a === b;
}}

function loadFn(sol: any, name: string): (...args: any[]) => any {{
  if (sol && typeof sol[name] === 'function') {{
    try {{
      const inst: any = new sol[name]();
      if (typeof inst[name] === 'function') return (...a: any[]) => inst[name](...a);
    }} catch (e) {{}}
    return (...a: any[]) => sol[name](...a);
  }}
  if (typeof sol === 'function') return (...a: any[]) => sol(...a);
  throw new Error('Cannot resolve entrypoint: ' + name);
}}

function captureCall(
  fn: (...a: any[]) => any, args: any[]
): {{ result: any; stdout: string; stderr: string; threw: boolean }} {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  (process.stdout as any).write = (c: any) => {{ stdout += c; return true; }};
  (process.stderr as any).write = (c: any) => {{ stderr += c; return true; }};
  let result: any, threw = false;
  try {{ result = fn(...args); }} catch (e) {{ threw = true; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw }};
}}

function run(): void {{
  const solPath: string = process.argv[2];
  const resultsPath: string = process.env['_BCG_RESULTS_FILE']!;
  const allIds: string[] = CASES.map((c: Case) => c.id);
  let fn: (...a: any[]) => any;
  try {{
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const sol = require(path.resolve(solPath));
    fn = loadFn(sol, ENTRYPOINT);
  }} catch (e) {{
    fs.writeFileSync(resultsPath, JSON.stringify({{passed: [], failed: allIds}}));
    return;
  }}
  const passed: string[] = [], failed: string[] = [];
  for (const c of CASES) {{
    try {{
      if (c.kind === 'raises') {{
        let threw = false;
        try {{ fn(...c.args); }} catch (e) {{ threw = true; }}
        (threw ? passed : failed).push(c.id);
        continue;
      }}
      const {{ result, stdout, stderr, threw }} = captureCall(fn, c.args);
      if (threw) {{ failed.push(c.id); continue; }}
      let ok = true;
      if (c.kind === 'eq') ok = deepEq(result, c.expected);
      else if (c.kind === 'ne') ok = !deepEq(result, c.expected);
      else if (c.kind === 'truthy') ok = !!result;
      else if (c.kind === 'falsy') ok = !result;
      if (ok && c.expectStdout !== null) ok = stdout === c.expectStdout;
      if (ok && c.expectStderr !== null) ok = stderr === c.expectStderr;
      (ok ? passed : failed).push(c.id);
    }} catch (e) {{
      failed.push(c.id);
    }}
  }}
  fs.writeFileSync(resultsPath, JSON.stringify({{passed, failed}}));
}}

run();
"""


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

_TESTER_NAMES = {
    "python": "tester.py",
    "javascript": "tester.js",
    "typescript": "tester.ts",
}

_EMITTERS = {
    "python": emit_python,
    "javascript": emit_javascript,
    "typescript": emit_typescript,
}


def cmd_generate(args: argparse.Namespace) -> int:
    tests_dir = Path(args.tests_dir)
    tests_py = tests_dir / "tests.py"
    if not tests_py.exists():
        print(f"error: {tests_py} not found", file=sys.stderr)
        return 1

    try:
        source = tests_py.read_text()
        cases = parse_tests(source, args.entrypoint)
    except Exception as e:
        print(f"error: failed to parse tests.py: {e}", file=sys.stderr)
        return 1

    code = _EMITTERS[args.lang](cases, args.entrypoint)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    tmp_path = tester_path.with_suffix(tester_path.suffix + ".tmp")
    try:
        tmp_path.write_text(code)
        tmp_path.replace(tester_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        print(f"error: failed to write tester: {e}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# test command
# ---------------------------------------------------------------------------

_ERROR_RESULT = json.dumps({"status": "error", "passed": [], "failed": []})

_SUBPROC = {
    "python": lambda tester, sol: [sys.executable, str(tester), str(sol)],
    "javascript": lambda tester, sol: ["node", str(tester), str(sol)],
    "typescript": lambda tester, sol: ["npx", "tsx", str(tester), str(sol)],
}


def _error_exit() -> int:
    print(_ERROR_RESULT)
    return 2


def cmd_test(args: argparse.Namespace) -> int:
    if args.lang not in _TESTER_NAMES:
        return _error_exit()

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    if not tester_path.exists():
        return _error_exit()

    sol_path = Path(args.solution_path)
    fd, results_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = _SUBPROC[args.lang](tester_path, sol_path)
        env = {**os.environ, "_BCG_RESULTS_FILE": results_file}
        try:
            subprocess.run(cmd, env=env, check=False)
        except FileNotFoundError as e:
            print(f"error: subprocess not found: {e}", file=sys.stderr)
            return _error_exit()

        try:
            with open(results_file) as f:
                data = json.load(f)
            passed: list[str] = data["passed"]
            failed: list[str] = data["failed"]
        except Exception:
            return _error_exit()

        status = "fail" if failed else "pass"
        print(json.dumps({"status": status, "passed": passed, "failed": failed}))
        return 0 if status == "pass" else 1
    finally:
        try:
            os.unlink(results_file)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_VALID_LANGS = frozenset(_TESTER_NAMES)


def _lang_type(value: str) -> str:
    if value not in _VALID_LANGS:
        raise argparse.ArgumentTypeError(
            f"lang must be python/javascript/typescript, got: {value!r}"
        )
    return value


def main() -> int:
    parser = argparse.ArgumentParser(prog="babel_code_goat")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate")
    gen.add_argument("tests_dir")
    gen.add_argument("--entrypoint", required=True)
    gen.add_argument("--lang", required=True, type=_lang_type)

    tst = sub.add_parser("test")
    tst.add_argument("solution_path")
    tst.add_argument("tests_dir")
    # lang validated manually inside cmd_test so we can emit error JSON
    tst.add_argument("--lang", required=True)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 1
    if args.command == "generate":
        return cmd_generate(args)
    return cmd_test(args)


if __name__ == "__main__":
    sys.exit(main())
