import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "babel_code_goat.py"
sys.path.insert(0, str(ROOT))

from babel_code_goat import DiscoveryError, discover_tests


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
    for filename in ("tester.py", "tester.js", "tester.ts"):
        path = tests_dir / filename
        path.write_text(f"old {filename}", encoding="utf-8")
        preserved[filename] = path.read_text(encoding="utf-8")

    completed = run_cli("generate", tests_dir, "--entrypoint", "solve", "--lang", "python")

    assert completed.returncode != 0
    for filename, content in preserved.items():
        assert (tests_dir / filename).read_text(encoding="utf-8") == content


def test_missing_tester_errors_and_does_not_create_tester(tmp_path):
    tests_dir = write_tests(tmp_path, "def cases():\n    assert solve(1) == 1\n")
    solution = tmp_path / "solution.py"
    solution.write_text("def solve(x):\n    return x\n", encoding="utf-8")

    completed = run_cli("test", solution, tests_dir, "--lang", "python")

    assert parse_result(completed) == {"status": "error", "passed": [], "failed": []}
    assert completed.returncode == 2
    assert not (tests_dir / "tester.py").exists()


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
    unsupported_code = write_tests(tmp_path / "code", "value = 1\n")
    unsupported_literal = write_tests(
        tmp_path / "literal",
        "def cases():\n    assert solve({1: 'bad'}) == 1\n",
    )

    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_code, "solve")
    with pytest.raises(DiscoveryError):
        discover_tests(unsupported_literal, "solve")


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
