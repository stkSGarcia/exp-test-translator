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
CPP_AVAILABLE = shutil.which("g++") is not None or shutil.which("clang++") is not None
RUST_AVAILABLE = shutil.which("rustc") is not None
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

    def assert_profile_stats(self, stats: object) -> None:
        self.assertIsInstance(stats, dict)
        assert isinstance(stats, dict)
        self.assertEqual(set(stats), {"mean", "std"})
        self.assertIsInstance(stats["mean"], (int, float))
        self.assertIsInstance(stats["std"], (int, float))
        self.assertGreaterEqual(stats["mean"], 0)
        self.assertGreaterEqual(stats["std"], 0)

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

    def run_generated_solution(
        self,
        lang: str,
        solution_name: str,
        tests_source: str,
        solution_source: str,
        *extra_args: str,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", tests_source)
            solution = tests_dir / solution_name
            write(solution, solution_source)
            generated = self.generate(tests_dir, lang)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            return self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                lang,
                *extra_args,
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
            "javascript": "tester.js",
            "typescript": "tester.ts",
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

    def test_recursive_discovery_supports_nested_files_and_no_root_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            (tests_dir / "nested").mkdir()
            write(tests_dir / "z_cases.py", "assert solve(2) == 3\n")
            write(tests_dir / "nested" / "cases.py", "assert solve(1) == 2\n")

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                ["nested/cases.py:1", "z_cases.py:1"],
            )
            self.assertEqual([case.source_path for case in cases], ["nested/cases.py", "z_cases.py"])

    def test_recursive_discovery_errors_for_no_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "empty.py", "\n")

            with self.assertRaises(bcg.DiscoveryError):
                bcg.discover_tests(tests_dir, "solve")

    def test_recursive_discovery_rejects_test_like_non_python_files(self) -> None:
        filenames = ["test_cases.txt", "value_test.json", "tests.yaml", "value_tests.md"]
        for filename in filenames:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                tests_dir = Path(tmp)
                write(tests_dir / "tests.py", "assert solve(1) == 2\n")
                (tests_dir / filename).write_text("not python", encoding="utf-8")

                with self.assertRaises(bcg.DiscoveryError):
                    bcg.discover_tests(tests_dir, "solve")

    def test_path_aware_ids_for_nested_same_line_and_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            nested = tests_dir / "nested"
            nested.mkdir()
            write(nested / "test_foo.py", "assert solve(1) == 2; assert solve(2) == 3\n")
            write(
                nested / "test_loop.py",
                """
                for value in [1, 2]:
                    assert solve(value) == value
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual(
                [case.id for case in cases],
                [
                    "nested/test_foo.py:1#0",
                    "nested/test_foo.py:1#1",
                    "nested/test_loop.py:1",
                    "nested/test_loop.py:2:0",
                    "nested/test_loop.py:2:1",
                ],
            )

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
                result = solve([3, 1])
                assert result == [1, 3]
                """,
            )

            cases = bcg.discover_tests(tests_dir, "solve")

            self.assertEqual([case.id for case in cases], ["tests.py:3", "tests.py:4", "tests.py:6"])
            self.assertEqual([case.kind for case in cases], ["eq", "eq", "eq"])
            self.assertEqual(cases[0].args, [[2, 0, 1]])
            self.assertEqual(cases[0].mutation_bindings, {"a": {"source": "arg", "index": 0}})
            self.assertEqual(cases[2].mutation_bindings, {"result": {"source": "result"}})
            self.assertEqual(cases[0].actual_expr, {"op": "var", "name": "a"})
            self.assertEqual(cases[1].actual_expr["op"], "call")

    def test_discovery_rejects_unsupported_mutation_patterns(self) -> None:
        sources = [
            """
            a = [2, 1]
            solve(a)
            expected = [1, 2]
            assert a == expected
            """,
            """
            a = [2, 1]
            expected = [1, 2]
            solve(a)
            assert expected == [1, 2]
            """,
            """
            a = [2, 1]
            solve(a)
            assert solve(a) == a
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

    def test_test_command_lists_selects_and_validates_timeout_flags(self) -> None:
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
                def solve(value):
                    raise RuntimeError("list mode must not execute")
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--list-tests")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(
                proc.stdout,
                '{"status":"pass","passed":["tests.py:1","tests.py:2"],"failed":[]}\n',
            )

            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--run",
                "tests.py:2",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(proc.stdout, '{"status":"pass","passed":["tests.py:2"],"failed":[]}\n')

            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--run",
                "missing.py:1",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--timeout-ms", "0")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--total-timeout-ms",
                "nope",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_python_timeout_flags_fail_timed_out_and_not_executed_tests(self) -> None:
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

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "python", "--timeout-ms", "50")

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])

            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--total-timeout-ms",
                "50",
            )

            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])

            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            proc = self.run_cli(
                "test",
                str(solution),
                str(tests_dir),
                "--lang",
                "python",
                "--run",
                "tests.py:2",
                "--timeout-ms",
                "500",
                "--total-timeout-ms",
                "1000",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(proc.stdout, '{"status":"pass","passed":["tests.py:2"],"failed":[]}\n')

    def test_profile_command_validation_output_shape_and_default_trial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                from pathlib import Path

                def solve(value):
                    counter = Path(__file__).with_name("count.txt")
                    current = int(counter.read_text()) if counter.exists() else 0
                    counter.write_text(str(current + 1))
                    return value + 1
                """,
            )

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "ruby")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "javascript")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)
            tester = tests_dir / "tester.py"
            before_tester = tester.read_text(encoding="utf-8")

            for extra_args in [
                ("-n", "0"),
                ("-n", "nope"),
                ("--warmup", "-1"),
                ("-n", "2", "--warmup", "2"),
            ]:
                with self.subTest(extra_args=extra_args):
                    proc = self.run_cli(
                        "profile",
                        str(tests_dir),
                        str(solution),
                        "--lang",
                        "python",
                        *extra_args,
                    )
                    self.assertEqual(proc.returncode, 2)
                    self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(set(result), {"status", "passed", "failed", "runtime_ns"})
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assert_profile_stats(result["runtime_ns"])
            self.assertEqual((tests_dir / "count.txt").read_text(encoding="utf-8"), "1")
            self.assertEqual(tester.read_text(encoding="utf-8"), before_tester)

    def test_profile_trials_warmup_and_memory_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(tests_dir / "tests.py", "assert solve(1) == 2\n")
            solution = tests_dir / "solution.py"
            write(
                solution,
                """
                from pathlib import Path

                def solve(value):
                    counter = Path(__file__).with_name("count.txt")
                    current = int(counter.read_text()) if counter.exists() else 0
                    counter.write_text(str(current + 1))
                    if current == 0:
                        return 0
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
                "-n",
                "2",
                "--warmup",
                "1",
                "--memory",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:1"])
            self.assertEqual(result["failed"], [])
            self.assert_profile_stats(result["runtime_ns"])
            self.assert_profile_stats(result["memory_kb"])
            self.assertEqual((tests_dir / "count.txt").read_text(encoding="utf-8"), "3")

    def test_profile_flag_parity_for_list_run_tolerance_and_invalid_flags(self) -> None:
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
                def solve(value):
                    raise RuntimeError("list mode must not execute")
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--list-tests")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(
                proc.stdout,
                '{"status":"pass","passed":["tests.py:1","tests.py:2"],"failed":[]}\n',
            )

            write(
                solution,
                """
                def solve(value):
                    return value + 1
                """,
            )
            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--run",
                "tests.py:2",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["passed"], ["tests.py:2"])
            self.assertEqual(result["failed"], [])
            self.assert_profile_stats(result["runtime_ns"])

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--run",
                "missing.py:1",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--timeout-ms", "0")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--total-timeout-ms",
                "nope",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

            write(tests_dir / "tests.py", 'assert solve(1) == [1.0, {"x": 2.005}]\n')
            write(
                solution,
                """
                def solve(value):
                    return [1.0, {"x": 2.0}]
                """,
            )
            self.assertEqual(self.generate(tests_dir, "python").returncode, 0)

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--tol", "0.01")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

            proc = self.run_cli("profile", str(tests_dir), str(solution), "--lang", "python", "--tol", "nope")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    def test_profile_timeout_failures_contribute_to_statistics(self) -> None:
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
                "--timeout-ms",
                "50",
                "--memory",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])
            self.assert_profile_stats(result["runtime_ns"])
            self.assertGreater(result["runtime_ns"]["mean"], 0)
            self.assert_profile_stats(result["memory_kb"])

            proc = self.run_cli(
                "profile",
                str(tests_dir),
                str(solution),
                "--lang",
                "python",
                "--total-timeout-ms",
                "50",
            )
            self.assertEqual(proc.returncode, 1)
            result = self.json_stdout(proc)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["failed"], ["tests.py:1", "tests.py:2"])
            self.assert_profile_stats(result["runtime_ns"])
            self.assertGreater(result["runtime_ns"]["mean"], 0)

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

    def test_python_async_entrypoint_result_is_awaited(self) -> None:
        proc = self.run_generated_solution(
            "python",
            "solution.py",
            """
            # expect_stdout: "ready\\n"
            assert solve(1) == 2
            """,
            """
            import asyncio

            async def solve(value):
                await asyncio.sleep(0)
                print("ready")
                return value + 1
            """,
        )

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

    def test_python_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 2, 1, 1, 0]
                solve(a)
                assert a == [0, 0, 1, 1, 2, 2]
                assert a[0] == 0
                result = solve([2, 1])
                assert result == [1, 2]
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
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not CPP_AVAILABLE, "C++ compiler is required for C++ smoke tests")
    def test_cpp_solution_execution_and_expression_wrappers(self) -> None:
        proc = self.run_generated_solution(
            "cpp",
            "solution.cpp",
            """
            assert sorted(solve([3, 1, 2])) == [1, 2, 3]
            assert solve("abc").upper() == "ABC"
            assert solve("abc")[1] == "b"
            """,
            """
            #include <string>
            #include <vector>

            std::vector<int> solve(std::vector<int> values) {
                return values;
            }

            std::string solve(std::string value) {
                return value;
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not CPP_AVAILABLE, "C++ compiler is required for C++ smoke tests")
    def test_cpp_rich_container_and_decimal_execution(self) -> None:
        proc = self.run_generated_solution(
            "cpp",
            "solution.cpp",
            """
            from collections import Counter, deque, defaultdict
            from decimal import Decimal

            assert solve({1: 2, 3: 4}) == {1: 2, 3: 4}
            assert solve(set([2, 1])) == set([1, 2])
            assert solve(Counter(["a", "a", "b"])) == Counter({"a": 2, "b": 1})
            assert solve(deque([1, 2])) == deque([1, 2])
            assert solve(defaultdict(int, {"x": 1})) == defaultdict(list, {"x": 1})
            assert solve(Decimal("1.25")) == Decimal("1.25")
            """,
            """
            #include <deque>
            #include <map>
            #include <set>
            #include <string>

            std::map<int, int> solve(std::map<int, int> value) {
                return value;
            }

            std::set<int> solve(std::set<int> value) {
                return value;
            }

            std::map<std::string, int> solve(std::map<std::string, int> value) {
                return value;
            }

            std::deque<int> solve(std::deque<int> value) {
                return value;
            }

            long double solve(long double value) {
                return value;
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not CPP_AVAILABLE, "C++ compiler is required for C++ smoke tests")
    def test_cpp_optional_mutation_output_tolerance_and_exception_execution(self) -> None:
        proc = self.run_generated_solution(
            "cpp",
            "solution.cpp",
            """
            from decimal import Decimal

            a = [2, 0, 1]
            solve(a)
            assert a == [0, 1, 2]
            sentinel = 0
            assert solve([None, 2]) == [None, 2]
            assert abs(Decimal("1.00") - solve(Decimal("1.01"))) <= Decimal("0.01")
            # expect_stdout: "hi\\n"
            assert solve(1) == 2
            try:
                solve("boom")
                assert False
            except ValueError as e:
                assert "bad" in str(e)
            """,
            """
            #include <algorithm>
            #include <iostream>
            #include <optional>
            #include <stdexcept>
            #include <string>
            #include <vector>

            class ValueError : public std::runtime_error {
            public:
                using std::runtime_error::runtime_error;
            };

            void solve(std::vector<int>& values) {
                std::sort(values.begin(), values.end());
            }

            std::vector<std::optional<int>> solve(std::vector<std::optional<int>> values) {
                return values;
            }

            long double solve(long double value) {
                return value;
            }

            int solve(int value) {
                std::cout << "hi\\n";
                return value + 1;
            }

            int solve(std::string) {
                throw ValueError("bad input");
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not CPP_AVAILABLE, "C++ compiler is required for C++ async smoke tests")
    def test_cpp_future_result_is_completed(self) -> None:
        proc = self.run_generated_solution(
            "cpp",
            "solution.cpp",
            """
            assert solve(2) == 3
            """,
            """
            #include <future>

            std::future<int> solve(int value) {
                return std::async(std::launch::deferred, [value]() {
                    return value + 1;
                });
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not RUST_AVAILABLE, "rustc is required for Rust smoke tests")
    def test_rust_solution_execution(self) -> None:
        proc = self.run_generated_solution(
            "rust",
            "solution.rs",
            """
            assert solve(2) == 3
            """,
            """
            fn solve(value: i32) -> i32 {
                value + 1
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(not RUST_AVAILABLE, "rustc is required for Rust async smoke tests")
    def test_rust_future_result_is_completed(self) -> None:
        proc = self.run_generated_solution(
            "rust",
            "solution.rs",
            """
            assert solve(2) == 3
            """,
            """
            async fn solve(value: i32) -> i32 {
                value + 1
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(RUST_AVAILABLE, "only checks the missing-rustc error path")
    def test_rust_execution_errors_when_compiler_is_unavailable(self) -> None:
        proc = self.run_generated_solution(
            "rust",
            "solution.rs",
            """
            assert solve(2) == 3
            """,
            """
            fn solve(value: i32) -> i32 {
                value + 1
            }
            """,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, '{"status":"error","passed":[],"failed":[]}\n')

    @unittest.skipIf(not RUST_AVAILABLE, "rustc is required for Rust smoke tests")
    def test_rust_option_map_mutation_output_and_panic_execution(self) -> None:
        cases = [
            (
                """
                assert solve([None, 2]) == [None, 2]
                """,
                """
                fn solve(value: Vec<Option<i32>>) -> Vec<Option<i32>> {
                    value
                }
                """,
            ),
            (
                """
                assert solve({"items": 1}) == {"items": 2}
                """,
                """
                use std::collections::HashMap;

                fn solve(mut value: HashMap<String, i32>) -> HashMap<String, i32> {
                    if let Some(item) = value.get_mut(&String::from("items")) {
                        *item += 1;
                    }
                    value
                }
                """,
            ),
            (
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                """,
                """
                fn solve(values: &mut Vec<i32>) {
                    values.sort();
                }
                """,
            ),
            (
                """
                # expect_stdout: "hi\\n"
                assert solve(1) == 2
                """,
                """
                fn solve(value: i32) -> i32 {
                    println!("hi");
                    value + 1
                }
                """,
            ),
            (
                """
                try:
                    solve("boom")
                    assert False
                except Exception:
                    pass
                """,
                """
                fn solve(_value: String) -> i32 {
                    panic!("bad input");
                }
                """,
            ),
        ]
        for tests_source, solution_source in cases:
            with self.subTest(tests_source=tests_source):
                proc = self.run_generated_solution("rust", "solution.rs", tests_source, solution_source)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skip("Rust deque-specific behavior is intentionally skipped until VecDeque mapping is specified")
    def test_rust_deque_specific_regression_is_skipped(self) -> None:
        self.fail("Rust deque-specific behavior should stay skipped")

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

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript smoke tests")
    def test_javascript_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                result = solve([2, 1])
                assert result == [1, 2]
                """,
            )
            solution = tests_dir / "solution.js"
            write(
                solution,
                """
                function solve(values) {
                  values.sort((a, b) => a - b);
                  return values;
                }
                """,
            )
            self.assertEqual(self.generate(tests_dir, "javascript").returncode, 0)

            proc = self.run_cli("test", str(solution), str(tests_dir), "--lang", "javascript")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for JavaScript async smoke tests")
    def test_javascript_async_entrypoint_result_is_awaited(self) -> None:
        proc = self.run_generated_solution(
            "javascript",
            "solution.js",
            """
            assert solve(2) == 3
            """,
            """
            async function solve(value) {
              await Promise.resolve();
              return value + 1;
            }
            """,
        )

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

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript async smoke tests")
    def test_typescript_async_entrypoint_result_is_awaited(self) -> None:
        proc = self.run_generated_solution(
            "typescript",
            "solution.ts",
            """
            assert solve(2) == 4
            """,
            """
            class Solution {
              static async solve(value: number): Promise<number> {
                await Promise.resolve();
                return value * 2;
              }
            }
            """,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_stdout(proc)["status"], "pass")

    @unittest.skipIf(shutil.which("node") is None, "node is required for TypeScript smoke tests")
    def test_typescript_mutation_style_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            write(
                tests_dir / "tests.py",
                """
                a = [2, 0, 1]
                solve(a)
                assert a == [0, 1, 2]
                result = solve([2, 1])
                assert result == [1, 2]
                """,
            )
            solution = tests_dir / "solution.ts"
            write(
                solution,
                """
                class Solution {
                  static solve(values: number[]): number[] {
                    values.sort((a, b) => a - b);
                    return values;
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


if __name__ == "__main__":
    unittest.main()
