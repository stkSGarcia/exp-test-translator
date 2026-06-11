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
    path.parent.mkdir(parents=True, exist_ok=True)
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
        tests_dir = temp / "tests"
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

    def test_compiled_target_test_preserves_existing_tester_files(self) -> None:
        solutions = {
            "cpp": (
                "solution.cpp",
                """
                int solve(int value) {
                  return value;
                }
                """,
            ),
            "rust": (
                "solution.rs",
                """
                fn solve(value: i32) -> i32 {
                    value
                }
                """,
            ),
        }
        for lang, (solution_name, solution_source) in solutions.items():
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tests_dir = root / "tests"
                write(tests_dir / "tests.py", "assert solve(1) == 1\n")
                self.assertEqual(self.generate(tests_dir, lang).returncode, 0)
                tester = tests_dir / bcg.tester_filename(lang)
                before = tester.read_text(encoding="utf-8")
                solution = root / solution_name
                write(solution, solution_source)

                self.run_cli("test", str(solution), str(tests_dir), "--lang", lang)

                self.assertEqual(tester.read_text(encoding="utf-8"), before)

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

    def test_recursive_discovery_and_path_based_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "alpha.py", "assert solve(0) == 1\n")
            write(
                tests_dir / "nested" / "loop_cases.py",
                """
                cases = [(1, 2), (2, 3)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            write(
                tests_dir / "nested" / "test_values.py",
                "assert solve(1) == 2; assert solve(2) == 3\n",
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                [
                    "alpha.py:1",
                    "nested/loop_cases.py:2",
                    "nested/loop_cases.py:3:0",
                    "nested/loop_cases.py:3:1",
                    "nested/test_values.py:1#0",
                    "nested/test_values.py:1#1",
                ],
            )

    def test_recursive_discovery_rejects_no_tests_and_test_like_non_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "notes.py", "# no tests here\n")

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

        filenames = [
            "test_data.json",
            "values_test.txt",
            "tests.yaml",
            "integration_tests.md",
        ]
        for filename in filenames:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")
                write(tests_dir / "tester.js", "// generated tester is ignored\n")
                write(tests_dir / "tester.ts", "// generated tester is ignored\n")
                write(tests_dir / "tester.cpp", "// generated tester is ignored\n")
                write(tests_dir / "tester.rs", "// generated tester is ignored\n")
                write(tests_dir / filename, "not python\n")

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

    def test_discovery_supports_mutation_style_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                mutate(a)
                assert a == [0, 1, 2]
                assert len(a) == 3
                b = [3, 1]
                result = mutate(b)
                assert result == [1, 3]
                """,
            )

            cases = bcg.discover_tests(tests_dir, "mutate")

            self.assertEqual([case.id for case in cases], ["tests.py:3", "tests.py:4", "tests.py:7"])
            self.assertEqual([case.kind for case in cases], ["eq", "eq", "eq"])
            self.assertEqual(cases[0].actual_expr, {"op": "arg", "index": 0})
            self.assertEqual(cases[1].actual_expr["op"], "call")
            self.assertEqual(cases[1].actual_expr["args"][0], {"op": "arg", "index": 0})
            self.assertEqual(cases[2].actual_expr, {"op": "result"})

    def test_discovery_rejects_invalid_mutation_style_patterns(self) -> None:
        sources = [
            """
            a = []
            mutate(a)
            """,
            """
            a = []
            mutate(a)
            assert mutate(a) == []
            """,
            """
            a = []
            expected = []
            mutate(a)
            assert expected == []
            """,
        ]
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", source)

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "mutate")

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
            root = Path(tmp)
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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
            tests_dir = root / "tests"
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

    def test_python_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                # expect_stdout: "done\\n"
                assert a == [0, 1, 2]
                assert len(a) == 3
                b = [3, 1, 2]
                result = solve(b)
                assert result == [1, 2, 3]
                """,
            )
            solution = root / "solution.py"
            write(
                solution,
                """
                def solve(values):
                    print("done")
                    values.sort()
                    return values
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(
                self.json_stdout(proc),
                {
                    "status": "pass",
                    "passed": ["tests.py:4", "tests.py:5", "tests.py:8"],
                    "failed": [],
                },
            )

    def test_python_loop_execution_reports_loop_and_iteration_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
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
            root = Path(tmp)
            tests_dir = root / "tests"
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
            solution = root / "solution.js"
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
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                assert sorted(solve("sort")) == [1, 2, 3]
                assert solve("member") in ["x", "y"]
                assert solve("string").upper() == "ABC"
                """,
            )
            solution = root / "solution.js"
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
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                cases = [("a", "A"), ("b", "B")]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = root / "solution.js"
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                """,
            )
            solution = root / "solution.js"
            write(
                solution,
                """
                function solve(values) {
                  values.sort((left, right) => left - right);
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
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                assert sorted(solve("sort")) == [1, 2, 3]
                assert solve("member") in ["x", "y"]
                assert solve("string").upper() == "ABC"
                """,
            )
            solution = root / "solution.ts"
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
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                cases = [(1, 2), (2, 4)]
                for value, expected in cases:
                    assert solve(value) == expected
                """,
            )
            solution = root / "solution.ts"
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
    def test_typescript_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                """,
            )
            solution = root / "solution.ts"
            write(
                solution,
                """
                class Solution {
                  static solve(values: number[]): void {
                    values.sort((left, right) => left - right);
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
            root = Path(tmp)
            tests_dir = root / "tests"
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
            solution = root / "solution.ts"
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

    @unittest.skipIf(
        shutil.which("g++") is None and shutil.which("clang++") is None,
        "a C++ compiler is required for C++ smoke tests",
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
        "a C++ compiler is required for C++ smoke tests",
    )
    def test_cpp_null_mutation_output_tolerance_and_exception_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            null_tests = root / "null_tests"
            write(
                null_tests / "tests.py",
                """
                assert solve(None) == None
                assert solve([1, None, 3]) == [1, None, 3]
                """,
            )
            null_solution = root / "null_solution.cpp"
            write(
                null_solution,
                """
                std::optional<int> solve(std::optional<int> value) {
                  return value;
                }

                std::vector<std::optional<int>> solve(std::vector<std::optional<int>> value) {
                  return value;
                }
                """,
            )
            self.assertEqual(self.generate(null_tests, "cpp").returncode, 0)
            proc = self.run_cli("test", str(null_solution), str(null_tests), "--lang", "cpp")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            behavior_tests = root / "behavior_tests"
            write(
                behavior_tests / "tests.py",
                """
                import math

                a = [3, 1, 2]
                solve(a)
                assert a == [1, 2, 3]
                separator = 1

                # expect_stdout: "hi\\n"
                assert solve(1) == 1
                assert math.isclose(solve(1.0), 1.0, abs_tol=0.01)
                try:
                    solve("boom")
                    assert False
                except RuntimeError as e:
                    assert "bad" in str(e)
                """,
            )
            behavior_solution = root / "behavior_solution.cpp"
            write(
                behavior_solution,
                """
                void solve(std::vector<int>& values) {
                  std::sort(values.begin(), values.end());
                }

                int solve(int value) {
                  std::cout << "hi\\n";
                  return value;
                }

                long double solve(long double) {
                  return 1.005L;
                }

                int solve(std::string) {
                  throw std::runtime_error("bad input");
                }
                """,
            )
            self.assertEqual(self.generate(behavior_tests, "cpp").returncode, 0)
            proc = self.run_cli("test", str(behavior_solution), str(behavior_tests), "--lang", "cpp")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            deque_tests = root / "deque_tests"
            write(
                deque_tests / "tests.py",
                """
                from collections import deque
                assert solve(deque([1, 2, 3])) == deque([1, 2, 3])
                """,
            )
            deque_solution = root / "deque_solution.cpp"
            write(
                deque_solution,
                """
                std::vector<int> solve(std::vector<int> value) {
                  return value;
                }
                """,
            )
            self.assertEqual(self.generate(deque_tests, "cpp").returncode, 0)
            proc = self.run_cli("test", str(deque_solution), str(deque_tests), "--lang", "cpp")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    def test_rust_deque_cases_are_detected_without_vecdeque_translation(self) -> None:
        case = bcg.TestCase(
            id="tests.py:1",
            line=1,
            source_path="tests.py",
            kind="eq",
            args=[deque([1, 2, 3])],
            expected=deque([1, 2, 3]),
        )

        self.assertTrue(bcg.case_contains_deque(case))
        self.assertFalse(bcg.run_rust_case(Path("solution.rs"), "solve", case, None))

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust smoke tests")
    def test_rust_solution_execution(self) -> None:
        tests_dir, solution = self.make_generated_case("rust", "solution.rs")
        write(
            solution,
            """
            fn solve(value: i32) -> i32 {
                value + 1
            }
            """,
        )
        self.assertEqual(self.generate(tests_dir, "rust").returncode, 0)

        proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "rust")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("rustc") is None, "rustc is required for Rust smoke tests")
    def test_rust_null_mutation_output_tolerance_and_panic_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            null_tests = root / "null_tests"
            write(null_tests / "tests.py", "assert solve(None) == None\n")
            null_solution = root / "null_solution.rs"
            write(
                null_solution,
                """
                fn solve(value: Option<i32>) -> Option<i32> {
                    value
                }
                """,
            )
            self.assertEqual(self.generate(null_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(null_solution), str(null_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            mutation_tests = root / "mutation_tests"
            write(
                mutation_tests / "tests.py",
                """
                a = [3, 1, 2]
                solve(a)
                assert a == [1, 2, 3]
                """,
            )
            mutation_solution = root / "mutation_solution.rs"
            write(
                mutation_solution,
                """
                fn solve(values: &mut Vec<i32>) {
                    values.sort();
                }
                """,
            )
            self.assertEqual(self.generate(mutation_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(mutation_solution), str(mutation_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            map_tests = root / "map_tests"
            write(
                map_tests / "tests.py",
                """
                data = {"items": [1, 2]}
                solve(data)
                assert data == {"items": [1, 2, 3]}
                """,
            )
            map_solution = root / "map_solution.rs"
            write(
                map_solution,
                """
                use std::collections::HashMap;

                fn solve(data: &mut HashMap<String, Vec<i32>>) {
                    data.get_mut(String::from("items")).unwrap().push(3);
                }
                """,
            )
            self.assertEqual(self.generate(map_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(map_solution), str(map_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            output_tests = root / "output_tests"
            write(
                output_tests / "tests.py",
                """
                # expect_stdout: "hi\\n"
                assert solve(1) == 1
                """,
            )
            output_solution = root / "output_solution.rs"
            write(
                output_solution,
                """
                fn solve(value: i32) -> i32 {
                    println!("hi");
                    value
                }
                """,
            )
            self.assertEqual(self.generate(output_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(output_solution), str(output_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            tolerance_tests = root / "tolerance_tests"
            write(
                tolerance_tests / "tests.py",
                """
                import math
                assert math.isclose(solve(1), 1.0, abs_tol=0.01)
                """,
            )
            tolerance_solution = root / "tolerance_solution.rs"
            write(
                tolerance_solution,
                """
                fn solve(_: i32) -> f64 {
                    1.005
                }
                """,
            )
            self.assertEqual(self.generate(tolerance_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(tolerance_solution), str(tolerance_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            panic_tests = root / "panic_tests"
            write(
                panic_tests / "tests.py",
                """
                try:
                    solve(1)
                    assert False
                except RuntimeError as e:
                    assert "bad" in str(e)
                """,
            )
            panic_solution = root / "panic_solution.rs"
            write(
                panic_solution,
                """
                fn solve(_: i32) {
                    panic!("bad input");
                }
                """,
            )
            self.assertEqual(self.generate(panic_tests, "rust").returncode, 0)
            proc = self.run_cli("test", str(panic_solution), str(panic_tests), "--lang", "rust")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
