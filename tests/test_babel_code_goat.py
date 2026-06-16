from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter, defaultdict, deque
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "babel_code_goat.py"
sys.path.insert(0, str(ROOT))

import babel_code_goat as bcg  # noqa: E402


def write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


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

    def make_generated_case(self, lang: str, solution_name: str = "solution.py") -> tuple[Path, Path]:
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp)
        write(
            temp / "tests.py",
            """
            assert solve(2) == 3
            """,
        )
        solution = temp / solution_name
        return temp, solution

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
        filenames = {
            "python": "tester.py",
            "cpp": "tester.cpp",
            "rust": "tester.rs",
        }
        for lang, filename in filenames.items():
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", "import os\n")
                tester = tests_dir / filename
                tester.write_text("sentinel", encoding="utf-8")

                proc = self.generate(tests_dir, lang)

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

    def test_discovery_recurses_into_python_files_and_uses_relative_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            cases_dir = tests_dir / "cases"
            nested_dir = cases_dir / "nested"
            nested_dir.mkdir(parents=True)
            write(
                cases_dir / "sorting_tests.py",
                """
                assert solve(1) == 2; assert solve(2) == 3
                """,
            )
            write(
                nested_dir / "loop_tests.py",
                """
                values = [(3, 4), (4, 5)]
                for value, expected in values:
                    assert solve(value) == expected
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                [
                    "cases/nested/loop_tests.py:2",
                    "cases/nested/loop_tests.py:3:0",
                    "cases/nested/loop_tests.py:3:1",
                    "cases/sorting_tests.py:1#0",
                    "cases/sorting_tests.py:1#1",
                ],
            )

    def test_discovery_rejects_test_like_non_python_files_and_no_tests(self) -> None:
        test_like_names = [
            "test_cases.txt",
            "cases/api_test.md",
            "cases/tests.json",
            "cases/nested/parser_tests.yaml",
        ]
        for relative_name in test_like_names:
            with self.subTest(relative_name=relative_name), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                path = tests_dir / relative_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("not python", encoding="utf-8")
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "helpers.py", "VALUE = 1\n")

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

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

    def test_discovery_supports_mutation_style_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 2, 1, 1, 0]
                solve(a)
                assert a == [0, 0, 1, 1, 2, 2]
                items = [3, 1, 2]
                result = solve(items)
                assert result == [1, 2, 3]
                assert items == [1, 2, 3]
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual([case.id for case in cases], ["tests.py:3", "tests.py:6", "tests.py:7"])
            self.assertEqual([case.kind for case in cases], ["eq", "eq", "eq"])
            self.assertEqual(cases[0].args, [[2, 0, 2, 1, 1, 0]])
            self.assertEqual(cases[0].actual_expr, {"op": "arg", "index": 0})
            self.assertEqual(cases[1].actual_expr, {"op": "result"})
            self.assertEqual(cases[2].actual_expr, {"op": "arg", "index": 0})

    def test_python_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 2, 1, 1, 0]
                solve(a)
                assert a == [0, 0, 1, 1, 2, 2]
                items = [3, 1, 2]
                result = solve(items)
                assert result == [1, 2, 3]
                assert items == [1, 2, 3]
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                def solve(values):
                    values.sort()
                    return values
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:3", "tests.py:6", "tests.py:7"])

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

    def test_discovery_rejects_invalid_mutation_style_patterns(self) -> None:
        sources = [
            """
            a = [2, 1]
            solve(a)
            b = list(a)
            assert a == [1, 2]
            """,
            """
            a = [2, 1]
            solve(a)
            assert True
            """,
            """
            a = [2, 1]
            result = solve(a)
            assert len(a) == 2
            assert "independent"
            """,
            """
            solve([2, 1])
            """,
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

    def test_python_pass_fail_error_output_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 99
                """,
            )
            solution = tests_dir / "solution.py"
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
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                for x in []:
                    assert solve(x, x) == 0
                """,
            )
            solution = tests_dir / "solution.py"
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
            tests_dir = Path(tmp)
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
            solution = tests_dir / "solution.py"
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
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                from collections import defaultdict

                assert solve("nested") == [1.0, {"x": 2.005}]
                assert solve(defaultdict(int, {"x": 1})) == 0
                """,
            )
            solution = tests_dir / "solution.py"
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

    def test_test_flags_reject_invalid_timeout_values(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            def solve(value):
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        invalid_args = [
            ("--timeout-ms", "nope"),
            ("--timeout-ms", "0"),
            ("--total-timeout-ms", "-1"),
        ]
        for flag, value in invalid_args:
            with self.subTest(flag=flag, value=value):
                proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", flag, value)

                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_list_tests_reports_discovered_ids_without_running_solution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            marker = tests_dir / "called.txt"
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                cases = [(2, 3), (3, 4)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                f"""
                def solve(value):
                    with open({str(marker)!r}, "a", encoding="utf-8") as handle:
                        handle.write(str(value))
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--list-tests")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1", "tests.py:3", "tests.py:4:0", "tests.py:4:1"])
            self.assertEqual(result["failed"], [])
            self.assertFalse(marker.exists())

    def test_list_tests_discovery_failure_uses_error_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "import os\n")
            solution = tests_dir / "solution.py"
            solution.write_text("", encoding="utf-8")
            (tests_dir / "tester.py").write_text(
                '# Generated by babel_code_goat.py.\n# BABEL_CODE_GOAT_METADATA: {"version":1,"entrypoint":"solve","lang":"python"}\n',
                encoding="utf-8",
            )

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--list-tests")

            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_run_executes_only_selected_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            calls = tests_dir / "calls.txt"
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 99
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                f"""
                CALLS = {str(calls)!r}

                def solve(value):
                    with open(CALLS, "a", encoding="utf-8") as handle:
                        handle.write(str(value) + "\\n")
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:2")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:2"])
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), ["2"])

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:1")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])

    def test_run_unknown_test_id_uses_error_json(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            def solve(value):
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--run", "tests.py:99")

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_python_per_assert_tolerance_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
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
            solution = tests_dir / "solution.py"
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
            tests_dir = Path(tmp)
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
            solution = tests_dir / "solution.py"
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
            tests_dir = Path(tmp)
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
            solution = tests_dir / "solution.py"
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

    def test_python_async_entrypoint_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            import asyncio

            async def solve(value):
                await asyncio.sleep(0.01)
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["passed"], ["tests.py:1"])

    def test_python_per_test_timeout_fails_active_test(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            import time

            def solve(value):
                time.sleep(1)
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--timeout-ms", "100")

        self.assertEqual(proc.returncode, 1)
        result = self.json_stdout(proc)
        self.assertEqual(result["passed"], [])
        self.assertEqual(result["failed"], ["tests.py:1"])

    def test_python_total_timeout_fails_not_executed_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 3
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                import time

                def solve(value):
                    time.sleep(1)
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--total-timeout-ms", "100")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])

    def test_python_timeout_with_selected_test_reports_only_selected_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 3
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                import time

                def solve(value):
                    time.sleep(1)
                    return value + 1
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--run",
                "tests.py:2",
                "--timeout-ms",
                "100",
            )

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:2"])

    def test_profile_missing_tester_and_unsupported_language_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = tests_dir / "solution.py"
            solution.write_text("", encoding="utf-8")

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")

            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')
            self.assertFalse((tests_dir / "tester.py").exists())

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "ruby")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_success_output_and_warmup_exclusion(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            def solve(value):
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = self.json_stdout(proc)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["passed"], ["tests.py:1"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(set(result["runtime_ns"]), {"mean", "std"})
        self.assertIsInstance(result["runtime_ns"]["mean"], (int, float))
        self.assertEqual(result["runtime_ns"]["std"], 0)

        calls: list[bool] = []
        elapsed = [100.0, 200.0, 400.0]

        def fake_profile_trial(
            setup: bcg.CommandSetup,
            *,
            collect_memory: bool,
        ) -> tuple[dict[str, object], int, int]:
            calls.append(collect_memory)
            return (
                {"status": "pass", "passed": [case.id for case in setup.cases], "failed": []},
                int(elapsed[len(calls) - 1]),
                10,
            )

        original_profile_trial = bcg.profile_trial
        try:
            bcg.profile_trial = fake_profile_trial  # type: ignore[assignment]
            args = argparse.Namespace(
                tests_dir=str(tests_dir),
                solution_path=str(solution),
                lang="python",
                n="3",
                warmup="1",
                memory=True,
                tol=None,
                list_tests=False,
                run=None,
                timeout_ms=None,
                total_timeout_ms=None,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = bcg.command_profile(args)
        finally:
            bcg.profile_trial = original_profile_trial  # type: ignore[assignment]

        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(calls, [False, True, True])
        self.assertEqual(result["runtime_ns"], {"mean": 300.0, "std": 100.0})
        self.assertEqual(result["memory_kb"], {"mean": 10.0, "std": 0.0})

    def test_profile_rejects_invalid_flags(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            def solve(value):
                return value + 1
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        invalid_args = [
            ("-n", "nope"),
            ("-n", "0"),
            ("--warmup", "-1"),
            ("-n", "2", "--warmup", "2"),
            ("--timeout-ms", "0"),
            ("--total-timeout-ms", "nope"),
            ("--tol", "nope"),
        ]
        for extra in invalid_args:
            with self.subTest(extra=extra):
                proc = self.run_cli(
                    "profile",
                    str(tests_dir),
                    str(solution),
                    "--lang",
                    "python",
                    *extra,
                )

                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_list_run_and_tolerance_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            marker = tests_dir / "calls.txt"
            write(
                tests_dir / "tests.py",
                """
                assert solve("close") == 1.005
                assert solve("bad") == 99
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                f"""
                def solve(value):
                    with open({str(marker)!r}, "a", encoding="utf-8") as handle:
                        handle.write(value + "\\n")
                    if value == "close":
                        return 1.0
                    return 2
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--list-tests")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result, {"status": "pass", "passed": ["tests.py:1", "tests.py:2"], "failed": []})
            self.assertFalse(marker.exists())

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--run",
                "tests.py:2",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:2"])
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["bad"])

            marker.unlink()
            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--run",
                "tests.py:1",
                "--tol",
                "0.01",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["close"])

    def test_profile_memory_output(self) -> None:
        tests_dir, solution = self.make_generated_case("python")
        write(
            solution,
            """
            def solve(value):
                data = [0] * 1000
                return value + 1 + data[0]
            """,
        )
        self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

        proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--memory")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = self.json_stdout(proc)
        self.assertEqual(set(result["memory_kb"]), {"mean", "std"})
        self.assertIsInstance(result["memory_kb"]["mean"], (int, float))
        self.assertIsInstance(result["memory_kb"]["std"], (int, float))

    def test_profile_timeout_failures_include_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                assert solve(1) == 2
                assert solve(2) == 3
                """,
            )
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                import time

                def solve(value):
                    time.sleep(1)
                    return value + 1
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
                "100",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1"])
            self.assertIn("runtime_ns", result)

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--total-timeout-ms",
                "100",
                "--memory",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])
            self.assertIn("runtime_ns", result)
            self.assertIn("memory_kb", result)

    def test_python_loop_execution_reports_loop_and_iteration_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                cases = [(1, 2), (2, 3), (3, 7)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = tests_dir / "solution.py"
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
    def test_javascript_promise_entrypoint_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("javascript", "solution.js")
        write(
            solution,
            """
            function solve(value) {
              return new Promise((resolve) => {
                setTimeout(() => resolve(value + 1), 10);
              });
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["passed"], ["tests.py:1"])

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
    def test_typescript_promise_entrypoint_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("typescript", "solution.ts")
        write(
            solution,
            """
            class Solution {
              static async solve(value: number): Promise<number> {
                await new Promise((resolve) => setTimeout(resolve, 10));
                return value + 1;
              }
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "typescript").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "typescript")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["passed"], ["tests.py:1"])

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

    def test_cpp_generated_source_uses_native_idioms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                import math
                from decimal import Decimal

                assert solve(None) == None
                assert solve([3, 1, 2]) == [1, 2, 3]
                assert sorted(solve([3, 1, 2])) == [1, 2, 3]
                assert solve({"items": [1, 2]}) == {"items": [1, 2]}
                assert solve(set([2, 1])) == set([1, 2])
                assert math.isclose(solve("decimal"), Decimal("1.00"), abs_tol=Decimal("0.01"))
                assert solve("abc").upper() == "ABC"
                try:
                    solve("boom")
                    assert False
                except ValueError as e:
                    assert "bad" in str(e)
                """,
            )

            proc = self.generate(tests_dir, "cpp")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            source = (tests_dir / "tester.cpp").read_text(encoding="utf-8")
            self.assertIn("std::optional", source)
            self.assertIn("std::nullopt", source)
            self.assertIn("std::vector", source)
            self.assertIn("std::map", source)
            self.assertIn("std::unordered_map", source)
            self.assertIn("std::set", source)
            self.assertIn("long double", source)
            self.assertIn("std::string", source)
            self.assertIn("std::sort", source)
            self.assertIn("catch (const std::exception& e)", source)

    def test_rust_generated_source_uses_native_idioms_and_skips_deque(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                from collections import deque
                from decimal import Decimal

                assert solve(None) == None
                assert solve([3, 1, 2]) == [1, 2, 3]
                assert solve({"items": [1, 2]}) == {"items": [1, 2]}
                assert solve(set([2, 1])) == set([1, 2])
                assert solve("abc").lower() == "abc"
                assert solve("abc").find("b") == 1
                assert solve("decimal") == Decimal("1.0")
                assert solve(deque([1, 2])) == deque([1, 2])
                try:
                    solve("boom")
                    assert False
                except Exception:
                    pass
                """,
            )

            proc = self.generate(tests_dir, "rust")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            source = (tests_dir / "tester.rs").read_text(encoding="utf-8")
            self.assertIn("Option", source)
            self.assertIn("None", source)
            self.assertIn("Vec", source)
            self.assertIn("HashMap", source)
            self.assertIn("BTreeMap", source)
            self.assertIn("HashSet", source)
            self.assertIn("f64", source)
            self.assertIn("String::from", source)
            self.assertIn('String::from("items")', source)
            self.assertIn("to_lowercase", source)
            self.assertIn(".sort()", source)
            self.assertIn("catch_unwind", source)
            self.assertIn("skipped Rust deque test", source)

    @unittest.skipIf(
        shutil.which("g++") is None and shutil.which("clang++") is None,
        "g++ or clang++ is required for C++ smoke tests",
    )
    def test_cpp_solution_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("cpp", "solution.cpp")
        write(
            solution,
            """
            int solve(int value) {
              return value + 1;
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "cpp").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "cpp")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(
        shutil.which("g++") is None and shutil.which("clang++") is None,
        "g++ or clang++ is required for C++ smoke tests",
    )
    def test_cpp_timeout_reports_failed_ids(self) -> None:
        tests_dir, solution = self.make_generated_case("cpp", "solution.cpp")
        write(
            solution,
            """
            #include <chrono>
            #include <thread>

            int solve(int value) {
              std::this_thread::sleep_for(std::chrono::seconds(1));
              return value + 1;
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "cpp").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "cpp", "--timeout-ms", "100")

        self.assertEqual(proc.returncode, 1)
        result = self.json_stdout(proc)
        self.assertEqual(result["passed"], [])
        self.assertEqual(result["failed"], ["tests.py:1"])

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust smoke tests")
    def test_rust_solution_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("rust", "solution.rs")
        write(
            solution,
            """
            fn solve(value: i64) -> i64 {
                value + 1
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "rust").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "rust")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust smoke tests")
    def test_rust_timeout_reports_failed_ids(self) -> None:
        tests_dir, solution = self.make_generated_case("rust", "solution.rs")
        write(
            solution,
            """
            use std::{thread, time};

            fn solve(value: i64) -> i64 {
                thread::sleep(time::Duration::from_secs(1));
                value + 1
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "rust").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "rust", "--timeout-ms", "100")

        self.assertEqual(proc.returncode, 1)
        result = self.json_stdout(proc)
        self.assertEqual(result["passed"], [])
        self.assertEqual(result["failed"], ["tests.py:1"])


if __name__ == "__main__":
    unittest.main()
