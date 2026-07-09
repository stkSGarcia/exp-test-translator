import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "babel_code_goat.py"
sys.path.insert(0, str(ROOT))

from babel_code_goat import DiscoveryError, discover_tests  # noqa: E402


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


def test_supported_languages_generate_expected_files(tmp_path):
    for lang, filename in {
        "python": "tester.py",
        "javascript": "tester.js",
        "typescript": "tester.ts",
        "cpp": "tester.cpp",
        "rust": "tester.rs",
    }.items():
        tests_dir = write_tests(tmp_path / lang, "def cases():\n    assert solve(1) == 1\n")

        completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", lang)

        assert completed.returncode == 0
        assert (tests_dir / filename).exists()


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
    for filename in ("tester.py", "tester.js", "tester.ts", "tester.cpp", "tester.rs"):
        path = tests_dir / filename
        path.write_text(f"old {filename}", encoding="utf-8")
        preserved[filename] = path.read_text(encoding="utf-8")

    completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python")

    assert completed.returncode != 0
    for filename, content in preserved.items():
        assert (tests_dir / filename).read_text(encoding="utf-8") == content


def test_missing_tester_errors_and_does_not_create_tester(tmp_path):
    for lang, solution_name, tester_name, source in (
        ("python", "solution.py", "tester.py", "def solve(x):\n    return x\n"),
        ("javascript", "solution.js", "tester.js", "function solve(x) { return x; }\nmodule.exports = {solve};\n"),
        ("typescript", "solution.js", "tester.ts", "function solve(x) { return x; }\nmodule.exports = {solve};\n"),
        ("cpp", "solution.cpp", "tester.cpp", "long long solve(long long x) { return x; }\n"),
        ("rust", "solution.rs", "tester.rs", "fn solve(x: i64) -> i64 { x }\n"),
    ):
        tests_dir = write_tests(tmp_path / lang, "def cases():\n    assert solve(1) == 1\n")
        solution = tmp_path / lang / solution_name
        solution.write_text(source, encoding="utf-8")

        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
        assert completed.returncode == 2
        assert not (tests_dir / tester_name).exists()


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


def test_discovery_recurses_and_uses_relative_path_ids(tmp_path):
    tests_dir = tmp_path / "tests"
    nested = tests_dir / "nested"
    nested.mkdir(parents=True)
    (tests_dir / "tests.py").write_text("def root():\n    assert solve(1) == 1\n", encoding="utf-8")
    (nested / "test_more.py").write_text(
        "def nested():\n    assert solve(2) == 2\n    assert solve(3); assert solve(4)\n",
        encoding="utf-8",
    )

    discovered = discover_tests(tests_dir, "solve")

    assert [test.id for test in discovered] == [
        "nested/test_more.py:2",
        "nested/test_more.py:3#0",
        "nested/test_more.py:3#1",
        "tests.py:2",
    ]
    assert {test.source_path for test in discovered} == {"nested/test_more.py", "tests.py"}


def test_discovery_rejects_empty_recursive_results_and_test_like_non_python_files(tmp_path):
    empty_tests = tmp_path / "empty" / "tests"
    empty_tests.mkdir(parents=True)
    (empty_tests / "helper.py").write_text("import math\n", encoding="utf-8")
    with pytest.raises(DiscoveryError):
        discover_tests(empty_tests, "solve")

    non_python_tests = tmp_path / "non_python" / "tests"
    non_python_tests.mkdir(parents=True)
    (non_python_tests / "tests.py").write_text("def cases():\n    assert solve(1) == 1\n", encoding="utf-8")
    (non_python_tests / "test_data.txt").write_text("not python", encoding="utf-8")
    with pytest.raises(DiscoveryError):
        discover_tests(non_python_tests, "solve")


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


def test_discovery_accepts_mutation_style_tests(tmp_path):
    tests_dir = write_tests(
        tmp_path,
        """def cases():
    a = [2, 0, 2, 1, 1, 0]
    sort_colors(a)
    assert a == [0, 0, 1, 1, 2, 2]
    assert a[0] == 0
    b = [1, 0]
    result = sort_colors(b)
    assert result == [0, 1]
""",
    )

    discovered = discover_tests(tests_dir, "sort_colors")

    assert [test.kind for test in discovered] == ["expr", "expr", "expr"]
    assert [test.id for test in discovered] == ["tests.py:4", "tests.py:5", "tests.py:8"]
    assert [test.args for test in discovered] == [
        [[2, 0, 2, 1, 1, 0]],
        [[2, 0, 2, 1, 1, 0]],
        [[1, 0]],
    ]
    assert [test.mutation_arg_index for test in discovered] == [0, 0, None]
    assert discovered[0].expression["op"] == "compare"
    assert discovered[1].expression["left"]["op"] == "index"


def test_discovery_rejects_unsupported_mutation_patterns(tmp_path):
    cases = [
        "def cases():\n    a = []\n    sort_colors(a)\n",
        "def cases():\n    a = []\n    sort_colors(a)\n    b = 1\n    assert a == []\n",
        "def cases():\n    a = []\n    b = []\n    sort_colors(a)\n    assert b == []\n",
        "def cases():\n    a = []\n    sort_colors(a)\n    assert sort_colors(a) == []\n",
        "def cases():\n    a = []\n    sort_colors(a)\n    sort_colors(a)\n    assert a == []\n",
    ]

    for index, source in enumerate(cases):
        with pytest.raises(DiscoveryError):
            discover_tests(write_tests(tmp_path / str(index), source), "sort_colors")


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


def test_generated_testers_execute_mutation_style_tests_with_relative_ids(tmp_path):
    for lang, solution_name, solution_source in (
        (
            "python",
            "solution.py",
            "def sort_colors(values):\n    values.sort()\n    return values\n",
        ),
        (
            "javascript",
            "solution.js",
            "function sort_colors(values) {\n  values.sort((a, b) => a - b);\n  return values;\n}\nmodule.exports = {sort_colors};\n",
        ),
        (
            "typescript",
            "solution.js",
            "function sort_colors(values) {\n  values.sort((a, b) => a - b);\n  return values;\n}\nmodule.exports = {sort_colors};\n",
        ),
    ):
        tests_dir = tmp_path / lang / "tests"
        nested = tests_dir / "nested"
        nested.mkdir(parents=True)
        (nested / "test_mutation.py").write_text(
            """def cases():
    a = [2, 0, 2, 1, 1, 0]
    sort_colors(a)
    assert a == [0, 0, 1, 1, 2, 2]
    b = [1, 0]
    result = sort_colors(b)
    assert result == [0, 1]
""",
            encoding="utf-8",
        )
        solution = tmp_path / lang / solution_name
        solution.write_text(solution_source, encoding="utf-8")

        assert run_cli("generate", tests_dir, "--entrypoint", "sort_colors", "--lang", lang).returncode == 0
        completed = run_cli("test", solution, tests_dir, "--lang", lang)

        assert parse_result(completed) == {
            "status": "pass",
            "passed": ["nested/test_mutation.py:4", "nested/test_mutation.py:7"],
            "failed": [],
        }
        assert completed.returncode == 0


def test_cpp_execution_handles_nulls_collections_sorting_and_exceptions(tmp_path):
    if shutil.which("g++") is None:
        pytest.skip("g++ is required for C++ target execution")

    nullable_tests = write_tests(
        tmp_path / "nullable",
        """def cases():
    assert solve([None, 2]) == [None, 3]
""",
    )
    nullable_solution = tmp_path / "nullable" / "solution.cpp"
    nullable_solution.write_text(
        """std::vector<std::optional<long long>> solve(std::vector<std::optional<long long>> values) {
  values[1] = 3;
  return values;
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", nullable_tests, "--entrypoint", "solve", "--lang", "cpp").returncode == 0
    nullable_result = run_cli("test", nullable_solution, nullable_tests, "--lang", "cpp")
    assert parse_result(nullable_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    collection_tests = write_tests(
        tmp_path / "collections",
        """def cases():
    assert counts("items") == {"a": 2, "b": 1}
    assert colors("items") == set([1, 2, 3])
""",
    )
    collection_solution = tmp_path / "collections" / "solution.cpp"
    collection_solution.write_text(
        """std::map<std::string, long long> counts(std::string) {
  return std::map<std::string, long long>{{"b", 1}, {"a", 2}};
}
""",
        encoding="utf-8",
    )
    (collection_tests / "tests.py").write_text(
        """def cases():
    assert counts("items") == {"a": 2, "b": 1}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", collection_tests, "--entrypoint", "counts", "--lang", "cpp").returncode == 0
    collection_result = run_cli("test", collection_solution, collection_tests, "--lang", "cpp")
    assert parse_result(collection_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    set_tests = write_tests(
        tmp_path / "sets",
        """def cases():
    assert colors("items") == set([1, 2, 3])
""",
    )
    set_solution = tmp_path / "sets" / "solution.cpp"
    set_solution.write_text(
        """std::set<long long> colors(std::string) {
  return std::set<long long>{3, 1, 2};
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", set_tests, "--entrypoint", "colors", "--lang", "cpp").returncode == 0
    set_result = run_cli("test", set_solution, set_tests, "--lang", "cpp")
    assert parse_result(set_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    mutation_tests = write_tests(
        tmp_path / "mutation",
        """def cases():
    values = [3, 1, 2]
    sort_colors(values)
    assert values == [1, 2, 3]
""",
    )
    mutation_solution = tmp_path / "mutation" / "solution.cpp"
    mutation_solution.write_text(
        """void sort_colors(std::vector<long long>& values) {
  std::sort(values.begin(), values.end());
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", mutation_tests, "--entrypoint", "sort_colors", "--lang", "cpp").returncode == 0
    mutation_result = run_cli("test", mutation_solution, mutation_tests, "--lang", "cpp")
    assert parse_result(mutation_result) == {"status": "pass", "passed": ["tests.py:4"], "failed": []}

    raises_tests = write_tests(
        tmp_path / "raises",
        """def cases():
    try:
        explode("bad")
        assert False
    except ValueError as e:
        assert "bad" in str(e)
""",
    )
    raises_solution = tmp_path / "raises" / "solution.cpp"
    raises_solution.write_text(
        """long long explode(std::string) {
  throw std::runtime_error("bad input");
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", raises_tests, "--entrypoint", "explode", "--lang", "cpp").returncode == 0
    raises_result = run_cli("test", raises_solution, raises_tests, "--lang", "cpp")
    assert parse_result(raises_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}


def test_rust_execution_handles_nulls_collections_sorting_exceptions_and_deque_skip(tmp_path):
    if shutil.which("rustc") is None:
        pytest.skip("rustc is required for Rust target execution")

    nullable_tests = write_tests(
        tmp_path / "nullable",
        """def cases():
    assert solve([None, 2]) == [None, 3]
""",
    )
    nullable_solution = tmp_path / "nullable" / "solution.rs"
    nullable_solution.write_text(
        """fn solve(mut values: Vec<Option<i64>>) -> Vec<Option<i64>> {
    values[1] = Some(3);
    values
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", nullable_tests, "--entrypoint", "solve", "--lang", "rust").returncode == 0
    nullable_result = run_cli("test", nullable_solution, nullable_tests, "--lang", "rust")
    assert parse_result(nullable_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    collection_tests = write_tests(
        tmp_path / "collections",
        """def cases():
    assert counts("items") == {"a": 2, "b": 1}
""",
    )
    collection_solution = tmp_path / "collections" / "solution.rs"
    collection_solution.write_text(
        """fn counts(_: String) -> std::collections::HashMap<String, i64> {
    let mut values = std::collections::HashMap::new();
    values.insert(String::from("a"), 1);
    if let Some(item) = values.get_mut(&String::from("a")) {
        *item += 1;
    }
    values.insert(String::from("b"), 1);
    values
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", collection_tests, "--entrypoint", "counts", "--lang", "rust").returncode == 0
    collection_result = run_cli("test", collection_solution, collection_tests, "--lang", "rust")
    assert parse_result(collection_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    mutation_tests = write_tests(
        tmp_path / "mutation",
        """def cases():
    values = [3, 1, 2]
    sort_colors(values)
    assert values == [1, 2, 3]
""",
    )
    mutation_solution = tmp_path / "mutation" / "solution.rs"
    mutation_solution.write_text(
        """fn sort_colors(values: &mut Vec<i64>) {
    values.sort();
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", mutation_tests, "--entrypoint", "sort_colors", "--lang", "rust").returncode == 0
    mutation_result = run_cli("test", mutation_solution, mutation_tests, "--lang", "rust")
    assert parse_result(mutation_result) == {"status": "pass", "passed": ["tests.py:4"], "failed": []}

    raises_tests = write_tests(
        tmp_path / "raises",
        """def cases():
    try:
        explode("bad")
        assert False
    except ValueError:
        pass
""",
    )
    raises_solution = tmp_path / "raises" / "solution.rs"
    raises_solution.write_text(
        """fn explode(_: String) -> i64 {
    panic!("bad input");
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", raises_tests, "--entrypoint", "explode", "--lang", "rust").returncode == 0
    raises_result = run_cli("test", raises_solution, raises_tests, "--lang", "rust")
    assert parse_result(raises_result) == {"status": "pass", "passed": ["tests.py:2"], "failed": []}

    deque_tests = write_tests(
        tmp_path / "deque",
        """from collections import deque

def cases():
    assert solve("items") == deque([1, 2])
""",
    )
    deque_solution = tmp_path / "deque" / "solution.rs"
    deque_solution.write_text(
        """fn solve(_: String) -> Vec<i64> {
    vec![9]
}
""",
        encoding="utf-8",
    )
    assert run_cli("generate", deque_tests, "--entrypoint", "solve", "--lang", "rust").returncode == 0
    deque_result = run_cli("test", deque_solution, deque_tests, "--lang", "rust")
    assert parse_result(deque_result) == {"status": "pass", "passed": ["tests.py:4"], "failed": []}


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
