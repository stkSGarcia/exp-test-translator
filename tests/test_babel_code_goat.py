from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter, defaultdict, deque
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "babel_code_goat.py"
sys.path.insert(0, str(ROOT))

import babel_code_goat as bcg  # noqa: E402


def write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def make_tests_dir(root: Path) -> Path:
    tests_dir = root / "tests"
    tests_dir.mkdir()
    return tests_dir


class BabelCodeGoatTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
        )

    def json_stdout(self, proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
        lines = proc.stdout.splitlines()
        self.assertEqual(lines, [proc.stdout.rstrip("\n")])
        return json.loads(lines[0])

    def assert_stats_object(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        stats = value
        assert isinstance(stats, dict)
        self.assertIsInstance(stats.get("mean"), (int, float))
        self.assertIsInstance(stats.get("std"), (int, float))

    def make_generated_case(self, lang: str, solution_name: str = "solution.py") -> tuple[Path, Path]:
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp)
        tests_dir = make_tests_dir(temp)
        write(
            tests_dir / "tests.py",
            """
            assert solve(2) == 3
            """,
        )
        solution = temp / solution_name
        return tests_dir, solution

    def generate(self, tests_dir: Path, lang: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "generate",
            str(tests_dir),
            "--entrypoint",
            "solve",
            "--lang",
            lang,
        )

    def test_generate_language_validation_and_tester_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")

            expected = {
                "python": "tester.py",
                "javascript": "tester.js",
                "typescript": "tester.ts",
                "cpp": "tester.cpp",
                "rust": "tester.rs",
            }
            for lang, filename in expected.items():
                with self.subTest(lang=lang):
                    proc = self.generate(tests_dir, lang)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    tester = tests_dir / filename
                    self.assertTrue(tester.exists())
                    metadata = bcg.read_tester_metadata(tester)
                    self.assertEqual(metadata["entrypoint"], "solve")
                    self.assertEqual(metadata["lang"], lang)

            sentinels = {
                tests_dir / "tester.py": "py sentinel",
                tests_dir / "tester.js": "js sentinel",
                tests_dir / "tester.ts": "ts sentinel",
                tests_dir / "tester.cpp": "cpp sentinel",
                tests_dir / "tester.rs": "rust sentinel",
            }
            for path, content in sentinels.items():
                path.write_text(content, encoding="utf-8")
            proc = self.generate(tests_dir, "ruby")
            self.assertNotEqual(proc.returncode, 0)
            for path, content in sentinels.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_generate_preserves_existing_tester_on_discovery_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "import os\n")
            tester = tests_dir / "tester.py"
            tester.write_text("sentinel", encoding="utf-8")

            proc = self.generate(tests_dir, "python")

            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(tester.read_text(encoding="utf-8"), "sentinel")

    def test_missing_tester_errors_and_does_not_create_files(self) -> None:
        filenames = {
            "python": "tester.py",
            "javascript": "tester.js",
            "typescript": "tester.ts",
            "cpp": "tester.cpp",
            "rust": "tester.rs",
        }
        for lang, filename in filenames.items():
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")
                solution = tests_dir / f"solution.{filename.rsplit('.', 1)[1]}"
                solution.write_text("", encoding="utf-8")

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", lang)

                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')
                self.assertFalse((tests_dir / filename).exists())

    def test_discovery_supports_allowed_constructs_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                def outer():
                    assert solve(1) == 2; assert solve(2) != 5
                    def inner():
                        # expect_stdout: "hi\\n"
                        # expect_stderr: "err\\n"
                        assert solve("io")
                try:
                    solve("boom")
                    assert False
                except Exception:
                    pass
                assert not solve(0)
                assert solve({"x": [1, (2,)]}) == {"x": [1, (2,)]}
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases[:2]],
                ["tests.py:2#0", "tests.py:2#1"],
            )
            self.assertEqual(cases[2].expect_stdout, "hi\n")
            self.assertEqual(cases[2].expect_stderr, "err\n")
            self.assertEqual([case.kind for case in cases], ["eq", "ne", "truthy", "raises", "not", "eq"])
            self.assertEqual(cases[-1].args, [{"x": [1, (2,)]}])

    def test_discovery_supports_rich_values_and_tolerance_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                import math
                import re
                import collections as c
                import decimal
                from collections import Counter, deque, defaultdict
                from decimal import Decimal

                assert solve({1: Decimal("1.0"), (2,): frozenset([3])}) == {
                    "set": set([2, 1]),
                    "frozen": frozenset([4, 3]),
                    "counter": Counter(["a", "a", "b"]),
                    "deque": deque([1, 2]),
                    "default": defaultdict(int, {"x": 1}),
                    "decimal": decimal.Decimal("2.50"),
                    "alias": c.Counter({"z": 2}),
                }
                assert math.isclose(solve(1), Decimal("1.01"), abs_tol=Decimal("0.02"))
                assert abs(Decimal("1.00") - solve(2)) <= Decimal("0.01")
                try:
                    solve(0)
                    assert False
                except ValueError as e:
                    assert re.search(r"bad", str(e))
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(cases[0].args, [{1: Decimal("1.0"), (2,): frozenset([3])}])
            self.assertEqual(cases[0].expected["set"], {1, 2})
            self.assertEqual(cases[0].expected["frozen"], frozenset([3, 4]))
            self.assertEqual(cases[0].expected["counter"], Counter({"a": 2, "b": 1}))
            self.assertEqual(cases[0].expected["deque"], deque([1, 2]))
            self.assertEqual(cases[0].expected["default"], defaultdict(int, {"x": 1}))
            self.assertEqual(cases[0].expected["decimal"], Decimal("2.50"))
            self.assertEqual(cases[0].expected["alias"], Counter({"z": 2}))
            self.assertEqual(cases[1].kind, "isclose")
            self.assertEqual(cases[1].abs_tol, Decimal("0.02"))
            self.assertEqual(cases[2].comparison, "abs_le")
            self.assertEqual(cases[2].abs_tol, Decimal("0.01"))
            self.assertEqual(cases[3].exception_type, "ValueError")
            self.assertEqual(cases[3].message_match, "regex")
            self.assertEqual(cases[3].message_pattern, "bad")

    def test_discovery_supports_single_call_expression_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert 3 == solve(1, 2)
                assert solve(1, 2) in [1, 2, 3]
                assert sorted(solve([3, 1, 2])) == [1, 2, 3]
                assert solve("abc").upper() == "ABC"
                assert len(solve([1, 2, 3])[1:]) == 2
                assert solve(3) + 1 > 3
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(len(cases), 6)
            self.assertEqual(cases[0].kind, "eq")
            self.assertEqual(cases[0].args, [1, 2])
            self.assertEqual(cases[0].expected, 3)
            self.assertEqual(cases[1].kind, "truthy")
            self.assertEqual(cases[1].actual_expr["op"], "compare")
            self.assertEqual(cases[1].actual_expr["operator"], "in")
            self.assertEqual(cases[2].actual_expr["op"], "call")
            self.assertEqual(cases[2].actual_expr["name"], "sorted")
            self.assertEqual(cases[3].actual_expr["op"], "method")
            self.assertEqual(cases[3].actual_expr["name"], "upper")
            self.assertEqual(cases[4].actual_expr["op"], "call")
            self.assertEqual(cases[5].actual_expr["op"], "compare")

    def test_discovery_rejects_multi_call_and_unsupported_helper_expressions(self) -> None:
        sources = [
            "assert solve(1) == solve(2)\n",
            "assert solve(1) + solve(2) == 3\n",
            "assert helper(solve(1)) == 2\n",
            "assert solve(helper(1)) == 2\n",
        ]
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", source)

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

    def test_discovery_rejects_unsupported_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", 'assert solve({[1]: "bad"}) == 1\n')

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

    def test_discovery_supports_loop_parameterization_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                cases = [((1, 2), 3), ((2, 3), 5)]
                for args, exp in cases:
                    assert solve(*args) == exp
                enum_cases = [(1, 2, 3), (4, 5, 9)]
                for _, (a, b, exp) in enumerate(enum_cases):
                    assert solve(a, b) == exp
                index_cases = [(1, 2, 3), (4, 5, 9)]
                for i in range(len(index_cases)):
                    a, b, exp = index_cases[i]
                    assert solve(a, b) == exp
                while_cases = [(1, 2), (3, 4)]
                i = 0
                while i < len(while_cases):
                    a, b = while_cases[i]
                    assert solve(a, b) == a + b
                    i += 1
                outer_cases = [[1, 2], [3]]
                for case in outer_cases:
                    for x in case:
                        assert solve(x, 0) == x
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                [
                    "tests.py:2",
                    "tests.py:3:0",
                    "tests.py:3:1",
                    "tests.py:5",
                    "tests.py:6:0",
                    "tests.py:6:1",
                    "tests.py:8",
                    "tests.py:10:0",
                    "tests.py:10:1",
                    "tests.py:13",
                    "tests.py:15:0",
                    "tests.py:15:1",
                    "tests.py:18",
                    "tests.py:19:0",
                    "tests.py:20:0:0",
                    "tests.py:20:0:1",
                    "tests.py:19:1",
                    "tests.py:20:1:0",
                ],
            )
            self.assertTrue(all(case.loop_pass for case in cases if case.kind == "loop"))
            self.assertEqual(cases[1].args, [1, 2])
            self.assertEqual(cases[1].expected, 3)
            self.assertEqual(cases[10].expected, 3)

    def test_discovery_rejects_multi_call_assertions_inside_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                for a, b in [(1, 2)]:
                    assert solve(a) == solve(b)
                """,
            )

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

    def test_discovery_supports_recursive_python_files_and_relative_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            nested = tests_dir / "nested"
            nested.mkdir()
            write(tests_dir / "alpha.py", "assert solve(1) == 2\n")
            write(nested / "test_more.py", "assert solve(2) == 3; assert solve(3) == 4\n")

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                ["alpha.py:1", "nested/test_more.py:1#0", "nested/test_more.py:1#1"],
            )
            self.assertEqual([case.source_path for case in cases], ["alpha.py", "nested/test_more.py", "nested/test_more.py"])

    def test_discovery_rejects_test_like_non_python_files_and_empty_discovery(self) -> None:
        test_like_names = ["test_cases.txt", "case_test.md", "tests.json", "case_tests.yaml"]
        for filename in test_like_names:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")
                write(tests_dir / filename, "not python\n")

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "notes.txt", "not a test\n")

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

    def test_discovery_supports_mutation_style_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                assert len(a) == 3
                value = 1
                result = solve(value)
                assert result == 2
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual([case.kind for case in cases], ["mutation", "mutation", "mutation"])
            self.assertEqual([case.id for case in cases], ["tests.py:3", "tests.py:4", "tests.py:7"])
            self.assertEqual(cases[0].mutation_arg_names, {"a": 0})
            self.assertIsNone(cases[0].mutation_assignment)
            self.assertEqual(cases[2].mutation_assignment, "result")

    def test_discovery_rejects_invalid_mutation_style_tests(self) -> None:
        sources = [
            """
            a = []
            solve(a)
            value = 1
            assert a == []
            """,
            """
            a = []
            solve(a)
            assert solve(a) == []
            """,
            """
            a = []
            solve(a)
            assert [] == []
            """,
        ]
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", source)

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

    def test_python_pass_fail_error_output_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 99
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(set(result), {"status", "passed", "failed"})
            self.assertEqual(result["status"], "fail")
            self.assertEqual(len(result["passed"]), 1)
            self.assertEqual(len(result["failed"]), 1)

            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            write(tests_dir / "tests.py", "import os\n")
            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_python_zero_iteration_loop_fails_without_body_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                for x in []:
                    assert solve(x, x) == 0
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(a, b):
                    return a + b
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout, '{"status":"fail","passed":[],"failed":["tests.py:1"]}\n')

    def test_python_output_expectations_and_callable_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                # expect_stdout: "hi\\n"
                assert solve("out") == 1
                # expect_stderr: "err\\n"
                assert solve("err") == 2
                assert solve(2) == 3
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                import sys

                class Solution:
                    @staticmethod
                    def solve(value):
                        if value == "out":
                            print("hi")
                            return 1
                        if value == "err":
                            print("err", file=sys.stderr)
                            return 2
                        return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    def test_python_instance_method_resolution(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            class Solution:
                def solve(self, value):
                    return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    def test_python_default_tolerance_and_invalid_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                from collections import defaultdict

                assert solve("nested") == [1.0, {"x": 2.005}]
                assert solve(defaultdict(int, {"x": 1})) == 0
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                from collections import defaultdict

                def solve(value):
                    if isinstance(value, defaultdict):
                        return value["missing"]
                    return [1.0, {"x": 2.0}]
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.json_stdout(proc)["status"], "fail")

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--tol", "0.01")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--tol", "nope")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_python_per_assert_tolerance_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                import math
                from decimal import Decimal

                assert math.isclose(solve("close"), 1.0, abs_tol=0.01)
                assert abs(solve("lt") - 1.0) < 0.01
                assert abs(Decimal("1.00") - solve("le")) <= Decimal("0.01")
                assert math.isclose(solve("override"), 1.0, abs_tol=0.01)
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                from decimal import Decimal

                def solve(value):
                    if value == "close":
                        return 1.005
                    if value == "lt":
                        return 1.005
                    if value == "le":
                        return Decimal("1.01")
                    return 1.1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--tol", "0.5")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(len(result["passed"]), 3)
            self.assertEqual(len(result["failed"]), 1)

    def test_python_typed_exception_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                import re

                try:
                    solve("substring")
                    assert False
                except ValueError as e:
                    assert "bad" in str(e)

                try:
                    solve("regex")
                    assert False
                except ValueError as e:
                    assert re.search(r"b.d", str(e))

                try:
                    solve("wrong")
                    assert False
                except ValueError as e:
                    assert "bad" in str(e)
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(value):
                    if value == "substring":
                        raise ValueError("bad input")
                    if value == "regex":
                        raise ValueError("bud input")
                    raise TypeError("bad input")
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(len(result["passed"]), 2)
            self.assertEqual(len(result["failed"]), 1)

    def test_python_single_call_expression_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            calls = tests_dir / "calls.txt"
            write(
                tests_dir / "tests.py",
                """
                assert sorted(solve("sort")) == [1, 2, 3]
                assert solve("member") in ["x", "y"]
                assert solve("string").upper() == "ABC"
                assert solve("index")[1] == "b"
                assert len(solve("slice")[1:]) == 2
                assert solve("arith") + 2 == 5
                assert solve("gt") > 4
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                f"""
                CALLS = {str(calls)!r}

                def solve(value):
                    with open(CALLS, "a", encoding="utf-8") as handle:
                        handle.write(value + "\\n")
                    if value == "sort":
                        return [3, 1, 2]
                    if value == "member":
                        return "x"
                    if value == "string":
                        return "abc"
                    if value == "index":
                        return ["a", "b", "c"]
                    if value == "slice":
                        return [1, 2, 3]
                    if value == "arith":
                        return 3
                    return 5
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")
            self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 7)

    def test_python_loop_execution_reports_loop_and_iteration_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                cases = [(1, 2), (2, 3), (3, 7)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], ["tests.py:2", "tests.py:3:0", "tests.py:3:1"])
            self.assertEqual(result["failed"], ["tests.py:3:2"])

    def test_mutation_style_execution_reports_pass_and_fail_for_supported_languages(self) -> None:
        cases = {
            "python": (
                "solution.py",
                """
                def solve(values):
                    if len(values) == 3:
                        values.sort()
                    return values
                """,
            ),
            "javascript": (
                "solution.js",
                """
                function solve(values) {
                  if (values.length === 3) {
                    values.sort((a, b) => a - b);
                  }
                  return values;
                }
                """,
            ),
            "typescript": (
                "solution.ts",
                """
                class Solution {
                  static solve(values: number[]): number[] {
                    if (values.length === 3) {
                      values.sort((a, b) => a - b);
                    }
                    return values;
                  }
                }
                """,
            ),
        }
        for lang, (solution_name, solution_source) in cases.items():
            if lang in {"javascript", "typescript"} and shutil.which("node") is None:
                self.skipTest("node is required for JavaScript and TypeScript mutation tests")
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(
                    tests_dir / "tests.py",
                    """
                    a = [2, 0, 1]
                    solve(a)
                    assert a == [0, 1, 2]
                    b = [3, 1]
                    solve(b)
                    assert b == [1, 3]
                    """,
                )
                solution = root / solution_name
                write(solution, solution_source)
                self.assertEqual(self.generate(tests_dir, lang).returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", lang)

                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                result = self.json_stdout(proc)
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["passed"], ["tests.py:3"])
                self.assertEqual(result["failed"], ["tests.py:6"])

    @unittest.skipIf(
        shutil.which("g++") is None and shutil.which("clang++") is None,
        "g++ or clang++ is required for C++ smoke tests",
    )
    def test_cpp_solution_execution(self) -> None:
        scenarios = [
            (
                "numeric_loop_tolerance",
                """
                import math

                cases = [(1, 2), (2, 3)]
                for value, expected in cases:
                    assert solve(value) == expected
                assert math.isclose(solve(1.0), 2.005, abs_tol=0.01)
                """,
                """
                long double solve(long double value) {
                    return value + 1.0L;
                }
                """,
                "pass",
            ),
            (
                "optional_nested_values",
                """
                assert solve([None, 1, 2]) == [None, 1, 3]
                """,
                """
                std::vector<std::optional<int>> solve(std::vector<std::optional<int>> values) {
                    values[2] = 3;
                    return values;
                }
                """,
                "pass",
            ),
            (
                "output_and_exception",
                """
                # expect_stdout: "hi\\n"
                assert solve("out") == "ok"
                try:
                    solve("boom")
                    assert False
                except ValueError as e:
                    assert "bad" in str(e)
                """,
                """
                std::string solve(std::string value) {
                    if (value == "out") {
                        std::cout << "hi\\n";
                        return "ok";
                    }
                    throw std::invalid_argument("bad input");
                }
                """,
                "pass",
            ),
            (
                "mutation",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                """,
                """
                void solve(std::vector<int>& values) {
                    std::sort(values.begin(), values.end());
                }
                """,
                "pass",
            ),
        ]
        for name, tests_source, solution_source, status in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(tests_dir / "tests.py", tests_source)
                solution = root / "solution.cpp"
                write(solution, solution_source)
                self.assertEqual(self.generate(tests_dir, "cpp").returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "cpp")

                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], status)

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust smoke tests")
    def test_rust_solution_execution(self) -> None:
        scenarios = [
            (
                "numeric_loop_tolerance",
                """
                import math

                cases = [(1, 2), (2, 3)]
                for value, expected in cases:
                    assert solve(value) == expected
                assert math.isclose(solve(1.0), 2.005, abs_tol=0.01)
                """,
                """
                fn solve(value: f64) -> f64 {
                    value + 1.0
                }
                """,
            ),
            (
                "optional_nested_values",
                """
                assert solve([None, 1, 2]) == [None, 1, 3]
                """,
                """
                fn solve(mut values: Vec<Option<i64>>) -> Vec<Option<i64>> {
                    values[2] = Some(3);
                    values
                }
                """,
            ),
            (
                "output_and_exception",
                """
                # expect_stdout: "hi\\n"
                assert solve("out") == "ok"
                try:
                    solve("boom")
                    assert False
                except Exception as e:
                    assert "bad" in str(e)
                """,
                """
                fn solve(value: String) -> String {
                    if value == "out" {
                        print!("hi\\n");
                        return String::from("ok");
                    }
                    panic!("bad input");
                }
                """,
            ),
            (
                "mutation",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                """,
                """
                fn solve(values: &mut Vec<i64>) {
                    values.sort();
                }
                """,
            ),
            (
                "owned_string_map_lookup",
                """
                data = {"items": [2, 0, 1]}
                solve(data)
                assert data == {"items": [0, 1, 2]}
                """,
                """
                fn solve(data: &mut HashMap<String, Vec<i64>>) {
                    data.get_mut(&String::from("items")).unwrap().sort();
                }
                """,
            ),
            (
                "deque_skip",
                """
                from collections import deque

                assert solve(deque([1, 2])) == deque([1, 2])
                """,
                """
                fn solve(values: Vec<i64>) -> Vec<i64> {
                    values
                }
                """,
            ),
        ]
        for name, tests_source, solution_source in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(tests_dir / "tests.py", tests_source)
                solution = root / "solution.rs"
                write(solution, solution_source)
                self.assertEqual(self.generate(tests_dir, "rust").returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "rust")

                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_solution_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("javascript", "solution.js")
        write(
            solution,
            """
            function solve(value) {
              return value + 1;
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_rich_comparison_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                import math
                import re

                assert solve("map") == {1: "one"}
                assert math.isclose(solve("tol"), 1.0, abs_tol=0.01)
                try:
                    solve("boom")
                    assert False
                except ValueError as e:
                    assert "bad" in str(e)
                """,
            )
            solution = tests_dir / "solution.js"
            write(
                solution,
                """
                class ValueError extends Error {
                  constructor(message) {
                    super(message);
                    this.name = "ValueError";
                  }
                }

                function solve(value) {
                  if (value === "map") {
                    return new Map([[1, "one"]]);
                  }
                  if (value === "tol") {
                    return 1.005;
                  }
                  throw new ValueError("bad input");
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_single_call_expression_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert sorted(solve("sort")) == [1, 2, 3]
                assert solve("member") in ["x", "y"]
                assert solve("string").upper() == "ABC"
                """,
            )
            solution = tests_dir / "solution.js"
            write(
                solution,
                """
                function solve(value) {
                  if (value === "sort") {
                    return [3, 1, 2];
                  }
                  if (value === "member") {
                    return "x";
                  }
                  return "abc";
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_loop_discovered_assertions_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                cases = [("a", "A"), ("b", "B")]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = tests_dir / "solution.js"
            write(
                solution,
                """
                function solve(value) {
                  return value.toUpperCase();
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript smoke tests")
    def test_typescript_solution_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("typescript", "solution.ts")
        write(
            solution,
            """
            class Solution {
              static solve(value: number): number {
                return value + 1;
              }
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "typescript").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "typescript")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript smoke tests")
    def test_typescript_single_call_expression_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert sorted(solve("sort")) == [1, 2, 3]
                assert solve("member") in ["x", "y"]
                assert solve("string").upper() == "ABC"
                """,
            )
            solution = tests_dir / "solution.ts"
            write(
                solution,
                """
                class Solution {
                  static solve(value: string): any {
                    if (value === "sort") {
                      return [3, 1, 2];
                    }
                    if (value === "member") {
                      return "x";
                    }
                    return "abc";
                  }
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "typescript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "typescript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript smoke tests")
    def test_typescript_loop_discovered_assertions_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                cases = [(1, 2), (2, 4)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = tests_dir / "solution.ts"
            write(
                solution,
                """
                class Solution {
                  static solve(value: number): number {
                    return value * 2;
                  }
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "typescript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "typescript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript smoke tests")
    def test_typescript_rich_comparison_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                import math
                import re

                assert solve("map") == {1: "one"}
                assert math.isclose(solve("tol"), 1.0, abs_tol=0.01)
                try:
                    solve("boom")
                    assert False
                except ValueError as e:
                    assert re.search(r"bad", str(e))
                """,
            )
            solution = tests_dir / "solution.ts"
            write(
                solution,
                """
                class ValueError extends Error {
                  constructor(message: string) {
                    super(message);
                    this.name = "ValueError";
                  }
                }

                class Solution {
                  static solve(value: string): any {
                    if (value === "map") {
                      return new Map([[1, "one"]]);
                    }
                    if (value === "tol") {
                      return 1.005;
                    }
                    throw new ValueError("bad input");
                  }
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "typescript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "typescript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    def test_test_list_tests_reports_ids_without_executing_solution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            marker = root / "executed.txt"
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 3
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                f"""
                from pathlib import Path

                Path({str(marker)!r}).write_text("executed", encoding="utf-8")

                def solve(value):
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--list-tests")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result, {"status": "pass", "passed": ["tests.py:1", "tests.py:2"], "failed": []})
            self.assertFalse(marker.exists())

    def test_test_run_selection_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(1) == 3
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:1")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc), {"status": "pass", "passed": ["tests.py:1"], "failed": []})

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:2")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.json_stdout(proc), {"status": "fail", "passed": [], "failed": ["tests.py:2"]})

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "missing.py:1")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--list-tests",
                "--run",
                "tests.py:1",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_test_timeout_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 1
                assert solve(2) == 2
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                import time

                def solve(value):
                    time.sleep(1)
                    return value
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:1", "--timeout-ms", "20")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.json_stdout(proc), {"status": "fail", "passed": [], "failed": ["tests.py:1"]})

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--total-timeout-ms", "20")
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--timeout-ms", "nope")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--total-timeout-ms", "0")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_language_and_tester_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = root / "solution.py"
            write(solution, "def solve(value):\n    return value + 1\n")

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "ruby")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')
            self.assertFalse((tests_dir / "tester.py").exists())

            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)
            tester = tests_dir / "tester.py"
            original = tester.read_text(encoding="utf-8")
            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(tester.read_text(encoding="utf-8"), original)

    def test_profile_default_trials_and_invalid_trial_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = root / "solution.py"
            write(solution, "def solve(value):\n    return value + 1\n")
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assert_stats_object(result["runtime_ns"])
            self.assertEqual(result["runtime_ns"]["std"], 0)

            for args in (
                ("-n", "0"),
                ("-n", "nope"),
                ("-n", "3", "--warmup", "3"),
                ("-n", "3", "--warmup", "-1"),
                ("-n", "3", "--warmup", "nope"),
            ):
                with self.subTest(args=args):
                    proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", *args)
                    self.assertEqual(proc.returncode, 2)
                    self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_list_tests_and_run_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            marker = root / "executed.txt"
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(1) == 3
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                f"""
                from pathlib import Path

                Path({str(marker)!r}).write_text("executed", encoding="utf-8")

                def solve(value):
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--list-tests")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(
                self.json_stdout(proc),
                {"status": "pass", "passed": ["tests.py:1", "tests.py:2"], "failed": []},
            )
            self.assertFalse(marker.exists())

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--run", "tests.py:1")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assert_stats_object(result["runtime_ns"])

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--run", "missing.py:1")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--list-tests",
                "--run",
                "tests.py:1",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_default_tolerance_and_invalid_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(tests_dir / "tests.py", "assert solve(1) == [1.0, {'x': 2.0}]\n")
            solution = root / "solution.py"
            write(solution, "def solve(value):\n    return [1.0, {'x': 2.005}]\n")
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--tol", "0.01")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--tol", "nope")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_runtime_warmup_failure_and_memory_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            counter = root / "counter.txt"
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = root / "solution.py"
            write(
                solution,
                f"""
                from pathlib import Path

                COUNTER = Path({str(counter)!r})

                def solve(value):
                    count = int(COUNTER.read_text(encoding="utf-8")) if COUNTER.exists() else 0
                    COUNTER.write_text(str(count + 1), encoding="utf-8")
                    if count == 0:
                        return 0
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "-n", "2", "--warmup", "1")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assert_stats_object(result["runtime_ns"])
            self.assertNotIn("memory_kb", result)
            self.assertEqual(counter.read_text(encoding="utf-8"), "2")

            counter.unlink()
            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "-n", "2")
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1"])
            self.assert_stats_object(result["runtime_ns"])

            counter.unlink()
            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--memory")
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assert_stats_object(result["runtime_ns"])
            self.assert_stats_object(result["memory_kb"])

    def test_profile_timeout_controls_include_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 1
                assert solve(2) == 2
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                import time

                def solve(value):
                    time.sleep(1)
                    return value
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--run",
                "tests.py:1",
                "--timeout-ms",
                "20",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1"])
            self.assert_stats_object(result["runtime_ns"])

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--total-timeout-ms", "20")
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])
            self.assert_stats_object(result["runtime_ns"])

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--timeout-ms", "nope")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--total-timeout-ms", "0")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_changes_preserve_test_command_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = root / "solution.py"
            write(solution, "def solve(value):\n    return value + 1\n")
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(proc.stdout, '{"status":"pass","passed":["tests.py:1"],"failed":[]}\n')

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "ruby")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_python_async_entrypoint_and_mutation_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = make_tests_dir(root)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                values = [2, 0, 1]
                solve(values)
                assert values == [0, 1, 2]
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                import asyncio

                async def solve(value):
                    await asyncio.sleep(0)
                    if isinstance(value, list):
                        value.sort()
                        return None
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript and TypeScript async tests")
    def test_node_targets_await_promise_entrypoints(self) -> None:
        cases = {
            "javascript": (
                "solution.js",
                """
                async function solve(value) {
                  return Promise.resolve(value + 1);
                }
                """,
            ),
            "typescript": (
                "solution.ts",
                """
                class Solution {
                  static async solve(value: number): Promise<number> {
                    return Promise.resolve(value + 1);
                  }
                }
                """,
            ),
        }
        for lang, (solution_name, source) in cases.items():
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")
                solution = root / solution_name
                write(solution, source)
                self.assertEqual(self.generate(tests_dir, lang).returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", lang)

                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(
        shutil.which("g++") is None and shutil.which("clang++") is None,
        "g++ or clang++ is required for C++ async tests",
    )
    def test_cpp_future_entrypoints_complete_before_assertions(self) -> None:
        scenarios = [
            (
                "value",
                "assert solve(1) == 2\n",
                """
                std::future<long long> solve(long long value) {
                    return std::async(std::launch::deferred, [value]() {
                        return value + 1;
                    });
                }
                """,
            ),
            (
                "mutation",
                """
                values = [2, 0, 1]
                solve(values)
                assert values == [0, 1, 2]
                """,
                """
                std::future<void> solve(std::vector<long long>& values) {
                    return std::async(std::launch::deferred, [&values]() {
                        std::sort(values.begin(), values.end());
                    });
                }
                """,
            ),
        ]
        for name, tests_source, solution_source in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(tests_dir / "tests.py", tests_source)
                solution = root / "solution.cpp"
                write(solution, solution_source)
                self.assertEqual(self.generate(tests_dir, "cpp").returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "cpp")

                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust async tests")
    def test_rust_async_entrypoints_complete_before_assertions(self) -> None:
        scenarios = [
            (
                "value",
                "assert solve(1) == 2\n",
                """
                async fn solve(value: i64) -> i64 {
                    value + 1
                }
                """,
            ),
            (
                "mutation",
                """
                values = [2, 0, 1]
                solve(values)
                assert values == [0, 1, 2]
                """,
                """
                async fn solve(values: &mut Vec<i64>) {
                    values.sort();
                }
                """,
            ),
        ]
        for name, tests_source, solution_source in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = make_tests_dir(root)
                write(tests_dir / "tests.py", tests_source)
                solution = root / "solution.rs"
                write(solution, solution_source)
                self.assertEqual(self.generate(tests_dir, "rust").returncode, 0)

                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "rust")

                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
