import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "babel_code_goat.py"
sys.path.insert(0, str(ROOT))

from babel_code_goat import DiscoveryError, discover_tests, extract_tester_payload  # noqa: E402


SUPPORTED_TESTERS = {
    "python": "tester.py",
    "javascript": "tester.js",
    "typescript": "tester.ts",
    "cpp": "tester.cpp",
    "rust": "tester.rs",
}

HAS_GXX = shutil.which("g++") is not None
HAS_RUSTC = shutil.which("rustc") is not None


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_result(completed):
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert list(result) == ["status", "passed", "failed"]
    return result


def write_tests(tmp_path, source):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "tests.py").write_text(source, encoding="utf-8")
    return tests_dir


def write_test_file(tmp_path, relative_path, source):
    tests_dir = tmp_path / "tests"
    path = tests_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return tests_dir


def test_supported_languages_generate_expected_files(tmp_path):
    for lang, filename in SUPPORTED_TESTERS.items():
        tests_dir = write_tests(tmp_path / lang, "def cases():\n    assert solve(1) == 1\n")

        completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang)

        assert completed.returncode == 0
        assert (tests_dir / filename).exists()


def test_compiled_tester_payloads_are_extractable(tmp_path):
    for lang, filename in {"cpp": "tester.cpp", "rust": "tester.rs"}.items():
        tests_dir = write_tests(tmp_path / lang, "def cases():\n    assert solve(1) == 1\n")

        completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang)
        payload = extract_tester_payload(tests_dir / filename, lang)

        assert completed.returncode == 0
        assert payload["entrypoint"] == "solve"
        assert payload["tests"][0]["id"] == "tests.py:2"


def test_unsupported_language_handling(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n")

    generate = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "ruby")
    test = run_cli("test", tmp_path / "solution.rb", tests_dir, "--lang", "ruby")

    assert generate.returncode != 0
    assert parse_result(test) == {"status": "error", "passed": [], "failed": []}
    assert test.returncode == 2


def test_failed_generate_preserves_existing_tester_files(tmp_path):
    tests_dir = write_tests(tmp_path, "import os\n")
    preserved = {}
    for filename in SUPPORTED_TESTERS.values():
        path = tests_dir / filename
        path.write_text(f"old {filename}", encoding="utf-8")
        preserved[filename] = path.read_text(encoding="utf-8")

    completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python")

    assert completed.returncode != 0
    for filename, content in preserved.items():
        assert (tests_dir / filename).read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    ("lang", "filename", "solution_name"),
    [
        ("python", "tester.py", "solution.py"),
        ("cpp", "tester.cpp", "solution.cpp"),
        ("rust", "tester.rs", "solution.rs"),
    ],
)
def test_missing_tester_errors_and_does_not_create_tester(tmp_path, lang, filename, solution_name):
    tests_dir = write_tests(tmp_path / lang, "def cases():\n    assert solve(1) == 1\n")
    solution = tmp_path / lang / solution_name
    solution.write_text("", encoding="utf-8")

    completed = run_cli("test", solution, tests_dir, "--lang", lang)

    assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
    assert completed.returncode == 2
    assert not (tests_dir / filename).exists()


def test_list_tests_reports_ids_without_executing_solution(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n    assert solve(2) == 2\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    raise RuntimeError('should not run')\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python", "--list-tests")

    assert parse_result(completed) == {
        "status": "pass",
        "passed": ["tests.py:2", "tests.py:3"],
        "failed": [],
    }
    assert completed.returncode == 0


def test_run_selects_only_requested_test_id(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n    assert solve(2) == 3\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    passing = run_cli("test", solution, tests_dir, "--lang", "python", "--run", "tests.py:2")
    failing = run_cli("test", solution, tests_dir, "--lang", "python", "--run", "tests.py:3")

    assert parse_result(passing) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}
    assert passing.returncode == 0
    assert parse_result(failing) == {"status": "fail", "passed": [], "failed": ["tests.py:3"]}
    assert failing.returncode == 1


def test_unknown_run_id_and_list_discovery_failure_are_errors(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    unknown = run_cli("test", solution, tests_dir, "--lang", "python", "--run", "missing.py:1")
    (tests_dir / "tests.py").write_text("not valid python", encoding="utf-8")
    listed = run_cli("test", solution, tests_dir, "--lang", "python", "--list-tests")

    assert parse_result(unknown) == {"status": "error", "passed": [], "failed": []}
    assert unknown.returncode == 2
    assert parse_result(listed) == {"status": "error", "passed": [], "failed": []}
    assert listed.returncode == 2


def test_timeout_flags_report_failed_selected_ids(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n    assert solve(2) == 2\n")
    solution = tmp_path / "solution.py"
    solution.write_text(
        """import time

def solve(x):
    if x == 1:
        return 1
    time.sleep(0.5)
    return x
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    per_test = run_cli("test", solution, tests_dir, "--lang", "python", "--timeout-ms", "250")
    selected = run_cli(
        "test", solution, tests_dir, "--lang", "python", "--run", "tests.py:3", "--timeout-ms", "250"
    )

    assert parse_result(per_test) == {"status": "fail", "passed": ["tests.py:2"], "failed": ["tests.py:3"]}
    assert parse_result(selected) == {"status": "fail", "passed": [], "failed": ["tests.py:3"]}

    solution.write_text(
        """import time

def solve(x):
    if x == 1:
        time.sleep(0.5)
    return x
""",
        encoding="utf-8",
    )
    total = run_cli(
        "test",
        solution,
        tests_dir,
        "--lang",
        "python",
        "--timeout-ms",
        "1000",
        "--total-timeout-ms",
        "100",
    )

    assert parse_result(total) == {"status": "fail", "passed": [], "failed": ["tests.py:2", "tests.py:3"]}


def test_python_async_entrypoints_are_awaited_and_async_errors_fail(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert solve(1) == 2
    try:
        solve("boom")
        assert False
    except ValueError:
        pass
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """import asyncio

async def solve(value):
    await asyncio.sleep(0)
    if value == "boom":
        raise ValueError("boom")
    return value + 1
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2", "tests.py:3"], "failed": []}


def test_javascript_and_typescript_promises_are_awaited_and_rejections_fail(tmp_path):
    for lang, suffix, source in [
        (
            "javascript",
            "js",
            """async function solve(value) {
  await Promise.resolve();
  if (value === "boom") throw new Error("boom");
  return value + 1;
}
module.exports = { solve };
""",
        ),
        (
            "typescript",
            "ts",
            """async function solve(value) {
  await Promise.resolve();
  if (value === "boom") throw new Error("boom");
  return value + 1;
}
module.exports = { solve };
""",
        ),
    ]:
        tests_dir = write_tests(
            tmp_path / lang,
            """def cases():
    assert solve(1) == 2
    try:
        solve("boom")
        assert False
    except Exception:
        pass
""",
        )
        solution = tmp_path / lang / f"solution.{suffix}"
        solution.write_text(source, encoding="utf-8")

        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2", "tests.py:3"], "failed": []}


def test_discovery_accepts_allowed_constructs_and_duplicate_line_ids(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def outer():
    def inner():
        assert solve(1) == 1
        assert solve(2) != 3
        assert solve(True)
        assert not solve(False)
        try:
            solve("boom")
            assert False
        except Exception:
            pass
assert solve(1); assert not solve(0)
# expect_stdout: "hello\\n"
# expect_stderr: "warn\\n"
assert solve("io") == "ok"
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == [
        "eq",
        "neq",
        "truthy",
        "falsy",
        "raises",
        "truthy",
        "falsy",
        "eq",
    ]
    assert "tests.py:12#0" in [test.id for test in discovered]
    assert "tests.py:12#1" in [test.id for test in discovered]
    assert discovered[-1].expect_stdout == "hello\n"
    assert discovered[-1].expect_stderr == "warn\n"


def test_discovery_rejects_unsupported_constructs_and_literals(tmp_path):
    unsupported_code = write_tests(tmp_path / "code", "print('nope')\n")
    unsupported_literal = write_tests(
        tmp_path / "literal",
        "def cases():\n    assert solve(object()) == 1\n",
    )

    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_code, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_literal, "solve")


def test_discovery_accepts_single_call_primitive_expressions(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert 3 == solve(1, 2)
    assert solve(1, 2) in [1, 2, 3]
    assert solve(2) + 1 == 4
    assert solve("items")[0] == "first"
    assert sorted(solve([3, 1, 2])) == [1, 2, 3]
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["expr", "expr", "expr", "expr", "expr"]
    assert [test.args for test in discovered] == [
        [1, 2],
        [1, 2],
        [2],
        ["items"],
        [[3, 1, 2]],
    ]
    assert discovered[0].expression["op"] == "compare"
    assert discovered[1].expression["operator"] == "in"
    assert discovered[2].expression["left"]["op"] == "binary"
    assert discovered[3].expression["left"]["op"] == "index"
    assert discovered[4].expression["left"]["function"] == "sorted"


def test_discovery_rejects_untraceable_or_multi_call_expressions(tmp_path):
    multiple_calls = write_tests(
        tmp_path / "multiple",
        "def cases():\n    assert solve(1) == solve(2)\n",
    )
    no_entrypoint = write_tests(
        tmp_path / "none",
        "def cases():\n    assert 3 == 3\n",
    )
    unsupported_helper = write_tests(
        tmp_path / "helper",
        "def cases():\n    assert normalize(solve(1)) == 1\n",
    )

    with pytest.raises(DiscoveryError):
        discover_tests(multiple_calls, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(no_entrypoint, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_helper, "solve")


def test_recursive_discovery_accepts_nested_python_without_root_tests(tmp_path):
    tests_dir = write_test_file(
        tmp_path,
        "nested/test_cases.py",
        """def cases():
    assert solve(1) == 1
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.id for test in discovered] == ["nested/test_cases.py:2"]
    assert discovered[0].kind == "eq"


def test_non_python_test_like_files_are_discovery_errors(tmp_path):
    tests_dir = write_tests(tmp_path, "assert solve(1) == 1\n")
    (tests_dir / "nested").mkdir()
    (tests_dir / "nested" / "test_cases.txt").write_text("assert solve(1) == 1\n", encoding="utf-8")

    with pytest.raises(DiscoveryError):
        discover_tests(tests_dir, "solve")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode != 0


def test_test_command_reports_error_when_rediscovery_hits_test_like_file(tmp_path):
    tests_dir = write_tests(tmp_path, "assert solve(1) == 1\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    (tests_dir / "extra_tests.txt").write_text("assert solve(2) == 2\n", encoding="utf-8")
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
    assert completed.returncode == 2


def test_empty_recursive_discovery_is_error(tmp_path):
    tests_dir = write_test_file(tmp_path, "helpers.py", "cases = []\n")

    with pytest.raises(DiscoveryError):
        discover_tests(tests_dir, "solve")

    completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python")
    assert completed.returncode != 0


def test_test_command_reports_error_when_rediscovery_finds_no_tests(tmp_path):
    tests_dir = write_tests(tmp_path, "assert solve(1) == 1\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    (tests_dir / "tests.py").write_text("cases = []\n", encoding="utf-8")
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
    assert completed.returncode == 2


def test_path_based_ids_are_grouped_by_source_file_and_line(tmp_path):
    tests_dir = write_tests(tmp_path, "assert solve(1); assert solve(2)\n")
    nested = tests_dir / "nested" / "test_ids.py"
    nested.parent.mkdir()
    nested.write_text(
        """def cases():
    assert solve(3); assert solve(4)
    for x in [5, 6]:
        assert solve(x) == x
""",
        encoding="utf-8",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.id for test in discovered] == [
        "nested/test_ids.py:2#0",
        "nested/test_ids.py:2#1",
        "nested/test_ids.py:3",
        "nested/test_ids.py:4:0",
        "nested/test_ids.py:4:1",
        "tests.py:1#0",
        "tests.py:1#1",
    ]


def test_standalone_mutation_call_discovers_and_executes_mutated_argument_assertions(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """items = [2, 0, 1]
solve(items)
assert items == [0, 1, 2]
assert items[0] == 0
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(items):\n    items.sort()\n", encoding="utf-8")

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["mutation", "mutation"]
    assert [test.id for test in discovered] == ["tests.py:3", "tests.py:4"]
    assert discovered[0].mutation_group == discovered[1].mutation_group
    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")
    assert parse_result(completed) == {
        "status": "pass",
        "passed": ["tests.py:3", "tests.py:4"],
        "failed": [],
    }
    assert completed.returncode == 0


def test_assignment_mutation_call_discovers_result_and_argument_assertions(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """items = [2, 0, 1]
result = solve(items)
assert result is None
assert items == [0, 1, 2]
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(items):\n    items.sort()\n", encoding="utf-8")

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["mutation", "mutation"]
    assert [test.id for test in discovered] == ["tests.py:3", "tests.py:4"]
    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")
    assert parse_result(completed) == {
        "status": "pass",
        "passed": ["tests.py:3", "tests.py:4"],
        "failed": [],
    }
    assert completed.returncode == 0


@pytest.mark.parametrize(
    "source",
    [
        "items = [2, 0, 1]\nsolve(items)\n",
        "items = [2, 0, 1]\nsolve(items)\nexpected = [0, 1, 2]\nassert items == expected\n",
        "items = [2, 0, 1]\nexpected = [0, 1, 2]\nsolve(items)\nassert expected == [0, 1, 2]\n",
        "items = [2, 0, 1]\nsolve(items)\nassert solve(items) == [0, 1, 2]\n",
    ],
)
def test_invalid_mutation_patterns_are_discovery_errors(tmp_path, source):
    tests_dir = write_tests(tmp_path, source)

    with pytest.raises(DiscoveryError):
        discover_tests(tests_dir, "solve")


def test_javascript_and_typescript_execute_mutation_groups_once(tmp_path):
    for lang, suffix in (("javascript", "js"), ("typescript", "ts")):
        tests_dir = write_tests(
            tmp_path / lang,
            """items = [2, 0, 1]
result = solve(items)
assert result is None
assert items == [0, 1, 2]
assert items[0] == 0
""",
        )
        solution = tmp_path / lang / f"solution.{suffix}"
        solution.write_text(
            """
let calls = 0;
exports.solve = function(items) {
  calls += 1;
  if (calls > 1) items.push(99);
  items.sort((a, b) => a - b);
};
""",
            encoding="utf-8",
        )

        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {
            "status": "pass",
            "passed": ["tests.py:3", "tests.py:4", "tests.py:5"],
            "failed": [],
        }
        assert completed.returncode == 0


def test_discovery_expands_non_empty_for_loop_tests(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    cases = [((1, 2), 3), ((2, 3), 5)]
    for args, exp in cases:
        assert solve(*args) == exp
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["loop", "eq", "eq"]
    assert [test.id for test in discovered] == ["tests.py:3", "tests.py:4:0", "tests.py:4:1"]
    assert discovered[0].expected is True
    assert [test.args for test in discovered[1:]] == [[1, 2], [2, 3]]
    assert [test.expected for test in discovered[1:]] == [3, 5]


@pytest.mark.parametrize(
    ("source", "loop_id"),
    [
        ("def cases():\n    for x in []:\n        assert solve(x) == x\n", "tests.py:2"),
        ("def cases():\n    for i in range(0):\n        assert solve(i) == i\n", "tests.py:2"),
        ("def cases():\n    for ch in \"\":\n        assert solve(ch) == ch\n", "tests.py:2"),
    ],
)
def test_zero_iteration_loops_report_fail_without_body_tests(tmp_path, source, loop_id):
    tests_dir = write_tests(tmp_path, source)
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "fail", "passed": [], "failed": [loop_id]}
    assert completed.returncode == 1


def test_loop_parameterization_patterns_execute(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    cases = [(1, 2, 3), (3, 4, 7)]
    for a, b, exp in cases:
        assert solve(a, b) == exp
    for _, (a, b, exp) in enumerate(cases):
        assert solve(a, b) == exp
    for i in range(len(cases)):
        a, b, exp = cases[i]
        assert solve(a, b) == exp
    i = 0
    while i < len(cases):
        a, b, exp = cases[i]
        assert solve(a, b) == exp
        i += 1
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(a, b):\n    return a + b\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")
    result = parse_result(completed)

    assert completed.returncode == 0
    assert result["status"] == "pass"
    assert result["failed"] == []
    assert result["passed"] == [
        "tests.py:3",
        "tests.py:4:0",
        "tests.py:4:1",
        "tests.py:5",
        "tests.py:6:0",
        "tests.py:6:1",
        "tests.py:7",
        "tests.py:9:0",
        "tests.py:9:1",
        "tests.py:11",
        "tests.py:13:0",
        "tests.py:13:1",
    ]


def test_nested_loops_report_loop_levels_and_nested_assertion_ids(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    groups = [[1, 2, 3]]
    for group in groups:
        for x in group:
            assert solve(x) == x
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["loop", "loop", "eq", "eq", "eq"]
    assert [test.id for test in discovered] == [
        "tests.py:3",
        "tests.py:4",
        "tests.py:5:0",
        "tests.py:5:1",
        "tests.py:5:2",
    ]


def test_loop_body_traceability_rejections(tmp_path):
    zero_calls = write_tests(
        tmp_path / "zero",
        "def cases():\n    for exp in [3]:\n        assert exp == 3\n",
    )
    multiple_calls = write_tests(
        tmp_path / "multiple",
        "def cases():\n    for a, b in [(1, 2)]:\n        assert solve(a, b) == solve(b, a)\n",
    )
    unsupported_helper = write_tests(
        tmp_path / "helper",
        "def cases():\n    for x in [1]:\n        assert normalize(solve(x)) == x\n",
    )

    with pytest.raises(DiscoveryError):
        discover_tests(zero_calls, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(multiple_calls, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_helper, "solve")


def test_discovery_accepts_rich_python_values_and_metadata(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """from collections import Counter, deque, defaultdict
from decimal import Decimal
import math
import re

def cases():
    assert solve({1: "one", (2, 3): set([Decimal("1.5")])}) == defaultdict(int, {Decimal("2.0"): Counter(["a", "a"]), "items": deque([1, 2]), "frozen": frozenset([3, 2])})
    assert math.isclose(solve("near"), Decimal("1.0"), abs_tol=0.01, rel_tol=0.0)
    assert abs(solve("strict") - 1.0) < 0.01
    try:
        solve("typed")
        assert False
    except ValueError as e:
        assert "bad" in str(e)
    try:
        solve("regex")
        assert False
    except ValueError as e:
        assert re.search(r"b.d", str(e))
""",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.kind for test in discovered] == ["eq", "eq", "eq", "raises", "raises"]
    assert discovered[0].args[0]["__bcg_type__"] == "dict"
    assert discovered[0].expected["__bcg_type__"] == "dict"
    assert discovered[1].tolerance == {"mode": "isclose", "abs": 0.01, "rel": 0.0}
    assert discovered[2].tolerance == {"mode": "absdiff", "abs": 0.01, "strict": True}
    assert discovered[3].expected_exception == "ValueError"
    assert discovered[3].message_match == {"mode": "contains", "pattern": "bad"}
    assert discovered[4].message_match == {"mode": "regex", "pattern": "b.d"}


def test_python_execution_reports_pass_fail_error_and_stream_expectations(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert solve(1, 2) == 3
    assert solve(2, 2) != 5
    assert solve([1, (2, 3)]) == [1, [2, 3]]
    assert solve("bad") == "good"
    try:
        solve("raise")
        assert False
    except Exception:
        pass
    # expect_stdout: "hello\\n"
    # expect_stderr: "warn\\n"
    assert solve("io") == "ok"
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """import sys

def solve(*args):
    if args == ("bad",):
        return "nope"
    if args == ("raise",):
        raise ValueError("expected")
    if args == ("io",):
        print("hello")
        print("warn", file=sys.stderr)
        return "ok"
    if args == ([1, [2, 3]],):
        return [1, (2, 3)]
    return sum(args)
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")
    result = parse_result(completed)

    assert completed.returncode == 1
    assert result["status"] == "fail"
    assert result["failed"] == ["tests.py:5"]
    assert set(result["passed"]) == {
        "tests.py:2",
        "tests.py:3",
        "tests.py:4",
        "tests.py:6",
        "tests.py:13",
    }


def test_python_execution_evaluates_primitive_expressions_once(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert 3 == solve("rhs")
    assert solve("member") in [1, 2, 3]
    assert solve("num") + 1 == 4
    assert solve("items")[0] == "first"
    assert sorted(solve("sort")) == [1, 2, 3]
    assert solve("fail") + 1 == 4
    assert solve("count") + 0 == 1
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """calls = {}

def solve(kind):
    calls[kind] = calls.get(kind, 0) + 1
    if kind == "rhs":
        return 3
    if kind == "member":
        return 2
    if kind == "num":
        return 3
    if kind == "items":
        return ["first", "second"]
    if kind == "sort":
        return [3, 1, 2]
    if kind == "fail":
        return 2
    if kind == "count":
        return calls[kind]
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {
        "status": "fail",
        "passed": ["tests.py:2", "tests.py:3", "tests.py:4", "tests.py:5", "tests.py:6", "tests.py:8"],
        "failed": ["tests.py:7"],
    }
    assert completed.returncode == 1


def test_python_execution_compares_rich_containers_and_default_tolerance(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """from collections import Counter, deque, defaultdict
from decimal import Decimal

def cases():
    assert solve("dict") == {1: "one", (2, 3): {"nested"}}
    assert solve("set") == frozenset([3, 1, 2])
    assert solve("counter") == Counter(["a", "b", "a"])
    assert solve("deque") == deque([1, 2, 3])
    assert solve("defaultdict") == defaultdict(int, {"x": 2})
    assert solve("decimal") == Decimal("1.00")
    assert solve("nested-floats") == {"values": [1.0, Decimal("2.0")]}
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """from collections import Counter, deque, defaultdict
from decimal import Decimal

def solve(kind):
    if kind == "dict":
        return {(2, 3): {"nested"}, 1: "one"}
    if kind == "set":
        return {2, 1, 3}
    if kind == "counter":
        return Counter({"a": 2, "b": 1})
    if kind == "deque":
        return deque([1, 2, 3])
    if kind == "defaultdict":
        return defaultdict(str, {"x": 2})
    if kind == "decimal":
        return Decimal("1.0")
    if kind == "nested-floats":
        return {"values": [1.0005, Decimal("2.0005")]}
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    without_tol = run_cli("test", solution, tests_dir, "--lang", "python")
    with_tol = run_cli("test", solution, tests_dir, "--lang", "python", "--tol", "0.001")

    assert parse_result(without_tol)["failed"] == ["tests.py:11"]
    assert parse_result(with_tol) == {
        "status": "pass",
        "passed": [f"tests.py:{line}" for line in range(5, 12)],
        "failed": [],
    }
    assert with_tol.returncode == 0


def test_javascript_and_typescript_execution_compare_map_set_and_tolerance(tmp_path):
    for lang in ("javascript", "typescript"):
        tests_dir = write_tests(
            tmp_path / lang,
            """def cases():
    assert solve("set") == set([3, 1, 2])
    assert solve("dict") == {1: "one", "two": 2}
    assert solve("nested") == {"values": [1.0]}
""",
        )
        solution = tmp_path / lang / "solution.js"
        solution.write_text(
            """function solve(kind) {
  if (kind === "set") return new Set([2, 3, 1]);
  if (kind === "dict") return new Map([[1, "one"], ["two", 2]]);
  if (kind === "nested") return {values: [1.0005]};
}
module.exports = {solve};
""",
            encoding="utf-8",
        )

        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang, "--tol", "0.001")

        assert parse_result(completed) == {
            "status": "pass",
            "passed": ["tests.py:2", "tests.py:3", "tests.py:4"],
            "failed": [],
        }
        assert completed.returncode == 0


def test_javascript_and_typescript_execution_evaluate_primitive_expressions(tmp_path):
    for lang in ("javascript", "typescript"):
        tests_dir = write_tests(
            tmp_path / lang,
            """def cases():
    assert 3 == solve("rhs")
    assert solve("member") in [1, 2, 3]
    assert sorted(solve("sort")) == [1, 2, 3]
    assert solve("num") + 1 == 4
    assert solve("items")[0] == "first"
""",
        )
        solution = tmp_path / lang / "solution.js"
        solution.write_text(
            """function solve(kind) {
  if (kind === "rhs") return 3;
  if (kind === "member") return 2;
  if (kind === "sort") return [3, 1, 2];
  if (kind === "num") return 3;
  if (kind === "items") return ["first", "second"];
}
module.exports = {solve};
""",
            encoding="utf-8",
        )

        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {
            "status": "pass",
            "passed": ["tests.py:2", "tests.py:3", "tests.py:4", "tests.py:5", "tests.py:6"],
            "failed": [],
        }
        assert completed.returncode == 0


def test_javascript_and_typescript_execution_handle_loop_tests(tmp_path):
    for lang in ("javascript", "typescript"):
        tests_dir = write_tests(
            tmp_path / lang,
            """def cases():
    for x in [1, 2]:
        assert solve(x) == x
    for y in []:
        assert solve(y) == y
""",
        )
        solution = tmp_path / lang / "solution.js"
        solution.write_text(
            """function solve(x) {
  return x;
}
module.exports = {solve};
""",
            encoding="utf-8",
        )

        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {
            "status": "fail",
            "passed": ["tests.py:2", "tests.py:3:0", "tests.py:3:1"],
            "failed": ["tests.py:4"],
        }
        assert completed.returncode == 1


@pytest.mark.skipif(not HAS_GXX, reason="g++ is required for C++ target tests")
def test_cpp_execution_handles_values_expressions_loops_and_raises(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert solve(1) == [2]
    assert sorted(solve(3)) == [1, 2, 3]
    for x, expected in [(4, [5]), (5, [6])]:
        assert solve(x) == expected
    try:
        solve(-1)
        assert False
    except RuntimeError as e:
        assert "negative" in str(e)
""",
    )
    solution = tmp_path / "solution.cpp"
    solution.write_text(
        """auto solve(int value) {
    if (value < 0) {
        throw std::runtime_error("negative input");
    }
    if (value == 3) {
        return std::vector<int>{3, 1, 2};
    }
    return std::vector<int>{value + 1};
}
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "cpp").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "cpp")

    assert parse_result(completed) == {
        "status": "pass",
        "passed": ["tests.py:2", "tests.py:3", "tests.py:4", "tests.py:5:0", "tests.py:5:1", "tests.py:6"],
        "failed": [],
    }
    assert completed.returncode == 0


@pytest.mark.skipif(not HAS_GXX, reason="g++ is required for C++ target tests")
def test_cpp_future_results_are_completed(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 2\n")
    solution = tmp_path / "solution.cpp"
    solution.write_text(
        """#include <future>

std::future<int> solve(int value) {
    return std::async(std::launch::async, [value]() { return value + 1; });
}
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "cpp").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "cpp")

    assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}


@pytest.mark.skipif(not HAS_GXX, reason="g++ is required for C++ target tests")
def test_cpp_execution_compares_rich_values_tolerance_streams_and_mutation(tmp_path):
    optional_tests = write_tests(
        tmp_path / "optional",
        """def cases():
    assert solve(0) == None
    assert solve(1) == 7
""",
    )
    optional_solution = tmp_path / "optional" / "solution.cpp"
    optional_solution.write_text(
        """std::optional<int> solve(int value) {
    if (value == 0) return std::nullopt;
    return 7;
}
""",
        encoding="utf-8",
    )

    map_tests = write_tests(tmp_path / "map", "def cases():\n    assert solve(1) == {1: \"one\"}\n")
    map_solution = tmp_path / "map" / "solution.cpp"
    map_solution.write_text(
        """std::map<int, std::string> solve(int value) {
    return std::map<int, std::string>{{1, "one"}};
}
""",
        encoding="utf-8",
    )

    set_tests = write_tests(tmp_path / "set", "def cases():\n    assert solve(1) == set([3, 1, 2])\n")
    set_solution = tmp_path / "set" / "solution.cpp"
    set_solution.write_text(
        """std::set<int> solve(int value) {
    return std::set<int>{2, 3, 1};
}
""",
        encoding="utf-8",
    )

    tolerance_tests = write_tests(
        tmp_path / "tol",
        """def cases():
    assert solve(1) == 1.0
""",
    )
    tolerance_solution = tmp_path / "tol" / "solution.cpp"
    tolerance_solution.write_text("long double solve(int value) { return 1.0005L; }\n", encoding="utf-8")

    stream_tests = write_tests(
        tmp_path / "streams",
        """def cases():
# expect_stdout: "hello\\n"
# expect_stderr: "warn\\n"
    assert solve(1) == 1
""",
    )
    stream_solution = tmp_path / "streams" / "solution.cpp"
    stream_solution.write_text(
        """int solve(int value) {
    std::cout << "hello\\n";
    std::cerr << "warn\\n";
    return value;
}
""",
        encoding="utf-8",
    )

    mutation_tests = write_tests(
        tmp_path / "mutation",
        """def cases():
    items = [2, 0, 1]
    solve(items)
    assert items == [0, 1, 2]
""",
    )
    mutation_solution = tmp_path / "mutation" / "solution.cpp"
    mutation_solution.write_text(
        """void solve(std::vector<int>& items) {
    std::sort(items.begin(), items.end());
}
""",
        encoding="utf-8",
    )

    scenarios = [
        (optional_tests, optional_solution, {"status": "pass", "passed": ["tests.py:2", "tests.py:3"], "failed": []}, []),
        (map_tests, map_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, []),
        (set_tests, set_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, []),
        (tolerance_tests, tolerance_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, ["--tol", "0.001"]),
        (stream_tests, stream_solution, {"status": "pass", "passed": ["tests.py:4"], "failed": []}, []),
        (mutation_tests, mutation_solution, {"status": "pass", "passed": ["tests.py:4"], "failed": []}, []),
    ]
    for tests_dir, solution, expected, extra_args in scenarios:
        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "cpp").returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", "cpp", *extra_args)
        assert parse_result(completed) == expected
        assert completed.returncode == 0


@pytest.mark.skipif(not HAS_GXX, reason="g++ is required for C++ target tests")
def test_cpp_test_command_does_not_modify_generated_tester(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 2\n")
    solution = tmp_path / "solution.cpp"
    solution.write_text("int solve(int value) { return value + 1; }\n", encoding="utf-8")

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "cpp").returncode == 0
    tester = tests_dir / "tester.cpp"
    before = tester.read_text(encoding="utf-8")
    completed = run_cli("test", solution, tests_dir, "--lang", "cpp")

    assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}
    assert completed.returncode == 0
    assert tester.read_text(encoding="utf-8") == before
    assert not any(path.name.startswith(".tester.cpp.") for path in tests_dir.iterdir())


@pytest.mark.skipif(not HAS_RUSTC, reason="rustc is required for Rust target tests")
def test_rust_execution_handles_values_expressions_loops_and_panics(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert solve(1) == [2]
    assert sorted(solve(3)) == [1, 2, 3]
    for x, expected in [(4, [5]), (5, [6])]:
        assert solve(x) == expected
    try:
        solve(-1)
        assert False
    except RuntimeError as e:
        assert "negative" in str(e)
""",
    )
    solution = tmp_path / "solution.rs"
    solution.write_text(
        """fn solve(value: i32) -> Vec<i32> {
    if value < 0 {
        panic!("negative input");
    }
    if value == 3 {
        return vec![3, 1, 2];
    }
    vec![value + 1]
}
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "rust").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "rust")

    assert parse_result(completed) == {
        "status": "pass",
        "passed": ["tests.py:2", "tests.py:3", "tests.py:4", "tests.py:5:0", "tests.py:5:1", "tests.py:6"],
        "failed": [],
    }
    assert completed.returncode == 0


@pytest.mark.skipif(not HAS_RUSTC, reason="rustc is required for Rust target tests")
def test_rust_future_results_are_completed(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 2\n")
    solution = tmp_path / "solution.rs"
    solution.write_text(
        """#[derive(Clone)]
struct ReadyI32(i32);

impl Future for ReadyI32 {
    type Output = i32;

    fn poll(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<Self::Output> {
        Poll::Ready(self.0)
    }
}

fn solve(value: i32) -> ReadyI32 {
    ReadyI32(value + 1)
}
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "rust").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "rust")

    assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}


@pytest.mark.skipif(not HAS_RUSTC, reason="rustc is required for Rust target tests")
def test_rust_execution_compares_options_maps_sets_tolerance_and_mutation(tmp_path):
    optional_tests = write_tests(
        tmp_path / "optional",
        """def cases():
    assert solve(0) == None
    assert solve(1) == 7
""",
    )
    optional_solution = tmp_path / "optional" / "solution.rs"
    optional_solution.write_text(
        """fn solve(value: i32) -> Option<i32> {
    if value == 0 { None } else { Some(7) }
}
""",
        encoding="utf-8",
    )

    map_tests = write_tests(tmp_path / "map", "def cases():\n    assert solve(1) == {\"items\": 2}\n")
    map_solution = tmp_path / "map" / "solution.rs"
    map_solution.write_text(
        """fn solve(_value: i32) -> std::collections::HashMap<String, i32> {
    std::collections::HashMap::from([(String::from("items"), 2)])
}
""",
        encoding="utf-8",
    )

    set_tests = write_tests(tmp_path / "set", "def cases():\n    assert solve(1) == set([3, 1, 2])\n")
    set_solution = tmp_path / "set" / "solution.rs"
    set_solution.write_text(
        """fn solve(_value: i32) -> std::collections::HashSet<i32> {
    std::collections::HashSet::from([2, 3, 1])
}
""",
        encoding="utf-8",
    )

    tolerance_tests = write_tests(tmp_path / "tol", "def cases():\n    assert solve(1) == 1.0\n")
    tolerance_solution = tmp_path / "tol" / "solution.rs"
    tolerance_solution.write_text("fn solve(_value: i32) -> f64 { 1.0005 }\n", encoding="utf-8")

    mutation_tests = write_tests(
        tmp_path / "mutation",
        """def cases():
    items = [2, 0, 1]
    solve(items)
    assert items == [0, 1, 2]
""",
    )
    mutation_solution = tmp_path / "mutation" / "solution.rs"
    mutation_solution.write_text(
        """fn solve(items: &mut Vec<i32>) {
    items.sort();
}
""",
        encoding="utf-8",
    )

    scenarios = [
        (optional_tests, optional_solution, {"status": "pass", "passed": ["tests.py:2", "tests.py:3"], "failed": []}, []),
        (map_tests, map_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, []),
        (set_tests, set_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, []),
        (tolerance_tests, tolerance_solution, {"status": "pass", "passed": ["tests.py:2"], "failed": []}, ["--tol", "0.001"]),
        (mutation_tests, mutation_solution, {"status": "pass", "passed": ["tests.py:4"], "failed": []}, []),
    ]
    for tests_dir, solution, expected, extra_args in scenarios:
        assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "rust").returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", "rust", *extra_args)
        assert parse_result(completed) == expected
        assert completed.returncode == 0


def test_test_tol_does_not_change_nonnumeric_equality(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    assert solve("num") == {"x": [1.0]}
    assert solve("str") == "same"
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """def solve(kind):
    if kind == "num":
        return {"x": [1.0005]}
    if kind == "str":
        return "sane"
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python", "--tol", "0.001")

    assert parse_result(completed) == {"status": "fail", "passed": ["tests.py:2"], "failed": ["tests.py:3"]}
    assert completed.returncode == 1


def test_per_assert_tolerance_overrides(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """import math

def cases():
    assert math.isclose(solve("isclose"), 1.0, abs_tol=0.01, rel_tol=0.0)
    assert abs(solve("strict-pass") - 1.0) < 0.01
    assert abs(solve("strict-fail") - 1.0) < 0.01
    assert abs(solve("inclusive") - 1.0) <= 0.01
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """def solve(kind):
    return {
        "isclose": 1.009,
        "strict-pass": 1.009,
        "strict-fail": 1.01,
        "inclusive": 1.01,
    }[kind]
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {
        "status": "fail",
        "passed": ["tests.py:4", "tests.py:5", "tests.py:7"],
        "failed": ["tests.py:6"],
    }
    assert completed.returncode == 1


def test_typed_raises_and_message_matching(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """import re

def cases():
    try:
        solve("typed-pass")
        assert False
    except ValueError as e:
        assert "bad" in str(e)
    try:
        solve("wrong-type")
        assert False
    except ValueError:
        pass
    try:
        solve("message-miss")
        assert False
    except ValueError as e:
        assert "bad" in str(e)
    try:
        solve("regex-pass")
        assert False
    except ValueError as e:
        assert re.search(r"b.d", str(e))
""",
    )
    solution = tmp_path / "solution.py"
    solution.write_text(
        """def solve(kind):
    if kind == "typed-pass":
        raise ValueError("bad input")
    if kind == "wrong-type":
        raise TypeError("bad input")
    if kind == "message-miss":
        raise ValueError("plain input")
    if kind == "regex-pass":
        raise ValueError("bed input")
""",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")
    result = parse_result(completed)

    assert result["status"] == "fail"
    assert result["passed"] == ["tests.py:4", "tests.py:19"]
    assert result["failed"] == ["tests.py:9", "tests.py:14"]
    assert completed.returncode == 1


def test_python_class_method_solution_and_passing_exit_code(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(2, 5) == 7\n")
    solution = tmp_path / "solution.py"
    solution.write_text(
        "class Solution:\n    def solve(self, a, b):\n        return a + b\n",
        encoding="utf-8",
    )

    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}
    assert completed.returncode == 0


def test_discovery_failure_output_is_error_json(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")
    assert run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python").returncode == 0
    (tests_dir / "tests.py").write_text("not valid python", encoding="utf-8")

    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
    assert completed.returncode == 2
