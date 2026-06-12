#!/usr/bin/env python3
"""Generate and run translated test harnesses for a constrained tests.py format."""

from __future__ import annotations

import argparse
import ast
import inspect
import io
import json
import keyword
import math
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import Counter, defaultdict, deque
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is Unix-only.
    resource = None


SUPPORTED_LANGS = {
    "python": "tester.py",
    "javascript": "tester.js",
    "typescript": "tester.ts",
    "cpp": "tester.cpp",
    "rust": "tester.rs",
}
METADATA_MARKER = "BABEL_CODE_GOAT_METADATA:"
METADATA_VERSION = 1
ERROR_RESULT = {"status": "error", "passed": [], "failed": []}
EXPECT_RE = re.compile(r"#\s*(expect_stdout|expect_stderr):\s*(.+)\s*$")
TEST_LIKE_STEM_RE = re.compile(r"^(?:test.*|.*_test|tests|.*_tests)$")
MATH_ISCLOSE_REL_TOL = 1e-09
MATH_ISCLOSE_ABS_TOL = 0.0
LOOP_ITERATION_LIMIT = 10000
DEFAULT_CASE_TIMEOUT_SECONDS = 10.0
DEFAULT_COMPILE_TIMEOUT_SECONDS = 15.0
MIN_TIMEOUT_SECONDS = 0.001
HELPER_MODULES = {"math", "re", "collections", "decimal"}
COLLECTION_CONSTRUCTORS = {"Counter", "deque", "defaultdict"}
DECIMAL_CONSTRUCTORS = {"Decimal"}
DEFAULTDICT_FACTORIES = {"None", "bool", "dict", "float", "int", "list", "set", "str", "tuple"}
PRIMITIVE_FUNCTIONS = {
    "abs",
    "bool",
    "float",
    "frozenset",
    "int",
    "len",
    "list",
    "max",
    "min",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
}
STRING_METHODS = {
    "count",
    "endswith",
    "find",
    "join",
    "lower",
    "lstrip",
    "replace",
    "rstrip",
    "split",
    "startswith",
    "strip",
    "upper",
}
BINARY_OPERATORS = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mult",
    ast.Div: "truediv",
    ast.FloorDiv: "floordiv",
    ast.Mod: "mod",
    ast.Pow: "pow",
}
UNARY_OPERATORS = {
    ast.UAdd: "uadd",
    ast.USub: "usub",
    ast.Not: "not",
}
COMPARE_OPERATORS = {
    ast.Eq: "eq",
    ast.NotEq: "ne",
    ast.Lt: "lt",
    ast.LtE: "lte",
    ast.Gt: "gt",
    ast.GtE: "gte",
    ast.In: "in",
    ast.NotIn: "not_in",
}


class DiscoveryError(Exception):
    """Raised when tests.py cannot be interpreted as the supported subset."""


class MetadataError(Exception):
    """Raised when generated tester metadata is absent or invalid."""


class LoopEvaluationError(Exception):
    """Raised when a loop cannot be evaluated as a supported parameterization."""


class CommandError(Exception):
    """Raised when CLI input should produce the standard error JSON."""


def result_expr() -> dict[str, Any]:
    return {"op": "result"}


@dataclass(frozen=True)
class PendingTest:
    source_path: str
    line: int
    kind: str
    args: list[Any] = field(default_factory=list)
    iteration_path: tuple[int, ...] = ()
    actual_expr: dict[str, Any] = field(default_factory=result_expr)
    expected: Any = None
    comparison: str = "standard"
    loop_pass: bool | None = None
    abs_tol: Any = None
    rel_tol: Any = None
    exception_type: str | None = None
    message_match: str | None = None
    message_pattern: str | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    mutation_arg_names: dict[str, int] = field(default_factory=dict)
    mutation_assignment: str | None = None


@dataclass(frozen=True)
class TestCase:
    id: str
    source_path: str
    line: int
    kind: str
    args: list[Any] = field(default_factory=list)
    iteration_path: tuple[int, ...] = ()
    actual_expr: dict[str, Any] = field(default_factory=result_expr)
    expected: Any = None
    comparison: str = "standard"
    loop_pass: bool | None = None
    abs_tol: Any = None
    rel_tol: Any = None
    exception_type: str | None = None
    message_match: str | None = None
    message_pattern: str | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    mutation_arg_names: dict[str, int] = field(default_factory=dict)
    mutation_assignment: str | None = None


@dataclass(frozen=True)
class RunContext:
    solution_path: Path
    tests_dir: Path
    lang: str
    entrypoint: str
    cases: list[TestCase]
    default_abs_tol: float | None
    timeout_seconds: float | None
    total_timeout_seconds: float | None


def tester_filename(lang: str) -> str:
    return SUPPORTED_LANGS[lang]


def is_supported_lang(lang: str) -> bool:
    return lang in SUPPORTED_LANGS


def is_valid_entrypoint(entrypoint: str) -> bool:
    return entrypoint.isidentifier() and not keyword.iskeyword(entrypoint)


def json_line(result: dict[str, Any]) -> str:
    return json.dumps(result, separators=(",", ":"))


def print_json_result(result: dict[str, Any]) -> None:
    print(json_line(result))


def status_exit_code(status: str) -> int:
    return {"pass": 0, "fail": 1, "error": 2}[status]


def error_result() -> dict[str, Any]:
    return {"status": "error", "passed": [], "failed": []}


def parse_default_tolerance(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise DiscoveryError("invalid tolerance") from exc
    if value < 0 or not math.isfinite(value):
        raise DiscoveryError("invalid tolerance")
    return value


def parse_positive_timeout_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise DiscoveryError("invalid timeout") from exc
    if value <= 0:
        raise DiscoveryError("invalid timeout")
    return value / 1000.0


def parse_positive_int(raw: str | None) -> int:
    if raw is None:
        raise DiscoveryError("missing integer")
    try:
        value = int(raw)
    except ValueError as exc:
        raise DiscoveryError("invalid integer") from exc
    if value <= 0:
        raise DiscoveryError("invalid integer")
    return value


def parse_non_negative_int(raw: str | None) -> int:
    if raw is None:
        raise DiscoveryError("missing integer")
    try:
        value = int(raw)
    except ValueError as exc:
        raise DiscoveryError("invalid integer") from exc
    if value < 0:
        raise DiscoveryError("invalid integer")
    return value


def parse_profile_trials(trials_raw: str | None, warmup_raw: str | None) -> tuple[int, int]:
    trials = parse_positive_int(trials_raw)
    warmup = parse_non_negative_int(warmup_raw)
    if warmup >= trials:
        raise DiscoveryError("invalid warmup")
    return trials, warmup


def render_tester(lang: str, entrypoint: str) -> str:
    metadata = {
        "version": METADATA_VERSION,
        "entrypoint": entrypoint,
        "lang": lang,
    }
    prefix = "#" if lang == "python" else "//"
    return (
        f"{prefix} Generated by babel_code_goat.py.\n"
        f"{prefix} {METADATA_MARKER} {json_line(metadata)}\n"
    )


def write_atomic(path: Path, content: str) -> None:
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(content)
        os.replace(tmp_name, path)
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def read_tester_metadata(path: Path) -> dict[str, Any]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if METADATA_MARKER in line:
                payload = line.split(METADATA_MARKER, 1)[1].strip()
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise MetadataError("metadata is not an object")
                if data.get("version") != METADATA_VERSION:
                    raise MetadataError("unsupported metadata version")
                entrypoint = data.get("entrypoint")
                lang = data.get("lang")
                if not isinstance(entrypoint, str) or not is_valid_entrypoint(entrypoint):
                    raise MetadataError("invalid entrypoint metadata")
                if lang not in SUPPORTED_LANGS:
                    raise MetadataError("invalid language metadata")
                return data
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(str(exc)) from exc
    raise MetadataError("metadata marker not found")


def is_supported_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    return isinstance(value, (int, float, str, Decimal)) and not isinstance(value, bool)


def is_supported_value(value: Any) -> bool:
    if is_supported_scalar(value):
        return True
    if isinstance(value, list):
        return all(is_supported_value(item) for item in value)
    if isinstance(value, tuple):
        return all(is_supported_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return all(is_hashable_supported(item) for item in value)
    if isinstance(value, (dict, defaultdict, Counter)):
        return all(
            is_hashable_supported(key) and is_supported_value(item)
            for key, item in value.items()
        )
    if isinstance(value, deque):
        return all(is_supported_value(item) for item in value)
    return False


def is_hashable_supported(value: Any) -> bool:
    if is_supported_scalar(value):
        return True
    if isinstance(value, tuple):
        return all(is_hashable_supported(item) for item in value)
    if isinstance(value, frozenset):
        return all(is_hashable_supported(item) for item in value)
    return False


def require_hashable_key(value: Any, line_no: int) -> Any:
    if not is_hashable_supported(value):
        raise DiscoveryError(f"unsupported dictionary key at line {line_no}")
    return value


def parse_decimal_value(value: Any, line_no: int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise DiscoveryError(f"unsupported Decimal value at line {line_no}")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise DiscoveryError(f"invalid Decimal value at line {line_no}") from exc
    raise DiscoveryError(f"unsupported Decimal value at line {line_no}")


def as_iterable_items(value: Any, line_no: int, constructor: str) -> list[Any]:
    if isinstance(value, (list, tuple, set, frozenset, deque)):
        return list(value)
    if isinstance(value, str):
        return list(value)
    raise DiscoveryError(f"{constructor} requires a supported iterable at line {line_no}")


def default_factory_from_name(name: str, line_no: int) -> Any:
    if name not in DEFAULTDICT_FACTORIES:
        raise DiscoveryError(f"unsupported defaultdict factory at line {line_no}")
    if name == "None":
        return None
    return {
        "bool": bool,
        "dict": dict,
        "float": float,
        "int": int,
        "list": list,
        "set": set,
        "str": str,
        "tuple": tuple,
    }[name]


def parse_expectation_value(raw: str, line_no: int) -> str:
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise DiscoveryError(f"invalid output expectation at line {line_no}") from exc
    if not isinstance(value, str):
        raise DiscoveryError(f"output expectation at line {line_no} must be a string")
    return value


class TestDiscoverer:
    def __init__(self, entrypoint: str, source_lines: list[str], source_path: str) -> None:
        self.entrypoint = entrypoint
        self.source_lines = source_lines
        self.source_path = source_path
        self.module_aliases: dict[str, str] = {}
        self.constructor_aliases: dict[str, str] = {}
        self.env: dict[str, Any] = {}
        self.active_path: tuple[int, ...] = ()
        self.pending: list[PendingTest] = []

    def discover(self, tree: ast.Module) -> list[TestCase]:
        self.collect_imports(tree.body)
        self.visit_body(tree.body)
        return assign_test_ids(self.pending)

    def visit_body(self, body: list[ast.stmt]) -> None:
        self.collect_imports(body)
        index = 0
        while index < len(body):
            stmt = body[index]
            if isinstance(stmt, ast.FunctionDef):
                self.visit_function(stmt)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                pass
            elif isinstance(stmt, ast.Assert):
                self.visit_assert(stmt)
            elif isinstance(stmt, ast.Try):
                self.visit_raise_expectation(stmt)
            elif self.is_mutation_call_statement(stmt):
                index = self.visit_mutation_group(body, index)
                continue
            elif isinstance(stmt, ast.Assign):
                self.visit_assign(stmt)
            elif isinstance(stmt, ast.AugAssign):
                self.visit_aug_assign(stmt)
            elif isinstance(stmt, ast.For):
                self.visit_for_loop(stmt)
            elif isinstance(stmt, ast.While):
                self.visit_while_loop(stmt)
            else:
                raise DiscoveryError(
                    f"unsupported statement at line {getattr(stmt, 'lineno', '?')}"
                )
            index += 1

    def is_mutation_call_statement(self, stmt: ast.stmt) -> bool:
        if isinstance(stmt, ast.Expr):
            return self.is_entrypoint_call(stmt.value)
        if isinstance(stmt, ast.Assign):
            return self.is_entrypoint_call(stmt.value)
        return False

    def is_entrypoint_call(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == self.entrypoint
        )

    def visit_mutation_group(self, body: list[ast.stmt], index: int) -> int:
        stmt = body[index]
        assignment_name: str | None = None
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                raise DiscoveryError(f"unsupported mutation assignment at line {stmt.lineno}")
            assignment_name = stmt.targets[0].id
            if assignment_name == self.entrypoint:
                raise DiscoveryError(f"assignment to entrypoint is unsupported at line {stmt.lineno}")
            call = stmt.value
        elif isinstance(stmt, ast.Expr):
            call = stmt.value
        else:
            raise DiscoveryError(f"unsupported mutation statement at line {getattr(stmt, 'lineno', '?')}")
        if not isinstance(call, ast.Call):
            raise DiscoveryError(f"unsupported mutation statement at line {getattr(stmt, 'lineno', '?')}")

        args, arg_names = self.parse_mutation_call_args(call)
        mutation_names = set(arg_names)
        if assignment_name is not None:
            mutation_names.add(assignment_name)

        assert_index = index + 1
        assertions: list[ast.Assert] = []
        while assert_index < len(body) and isinstance(body[assert_index], ast.Assert):
            assertions.append(body[assert_index])
            assert_index += 1
        if not assertions:
            raise DiscoveryError(f"mutation call must be immediately followed by assertions at line {stmt.lineno}")

        for assertion in assertions:
            self.add_mutation_assertion(assertion, args, arg_names, assignment_name, mutation_names)
        return assert_index

    def parse_mutation_call_args(self, call: ast.Call) -> tuple[list[Any], dict[str, int]]:
        line_no = getattr(call, "lineno", 0)
        if call.keywords:
            raise DiscoveryError(f"keyword arguments are unsupported at line {line_no}")
        args: list[Any] = []
        arg_names: dict[str, int] = {}
        for arg in call.args:
            if isinstance(arg, ast.Starred):
                args.extend(as_iterable_items(self.parse_value(arg.value), line_no, "starred argument"))
                continue
            if isinstance(arg, ast.Name) and arg.id not in arg_names:
                arg_names[arg.id] = len(args)
            args.append(self.parse_value(arg))
        return args, arg_names

    def add_mutation_assertion(
        self,
        stmt: ast.Assert,
        args: list[Any],
        arg_names: dict[str, int],
        assignment_name: str | None,
        mutation_names: set[str],
    ) -> None:
        if stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {stmt.lineno}")
        if self.count_entrypoint_calls(stmt.test) != 0:
            raise DiscoveryError(f"mutation assertion must not call {self.entrypoint} at line {stmt.lineno}")
        assertion_names = {
            node.id
            for node in ast.walk(stmt.test)
            if isinstance(node, ast.Name)
        }
        if not assertion_names.intersection(mutation_names):
            raise DiscoveryError(f"mutation assertion must reference a mutation variable at line {stmt.lineno}")
        expr = self.parse_expression(stmt.test, [], mutation_names)
        self.add_test(
            stmt.lineno,
            "mutation",
            list(args),
            actual_expr=expr,
            mutation_arg_names=dict(arg_names),
            mutation_assignment=assignment_name,
        )

    def visit_function(self, stmt: ast.FunctionDef) -> None:
        if stmt.decorator_list:
            raise DiscoveryError(f"decorators are unsupported at line {stmt.lineno}")
        module_aliases = self.module_aliases.copy()
        constructor_aliases = self.constructor_aliases.copy()
        env = self.env.copy()
        try:
            self.visit_body(stmt.body)
        finally:
            self.module_aliases = module_aliases
            self.constructor_aliases = constructor_aliases
            self.env = env

    def visit_assign(self, stmt: ast.Assign) -> None:
        if len(stmt.targets) != 1:
            raise DiscoveryError(f"multiple assignment targets are unsupported at line {stmt.lineno}")
        value = self.parse_value(stmt.value)
        self.bind_target(stmt.targets[0], value, stmt.lineno)

    def visit_aug_assign(self, stmt: ast.AugAssign) -> None:
        if not isinstance(stmt.target, ast.Name):
            raise DiscoveryError(f"unsupported assignment target at line {stmt.lineno}")
        if stmt.target.id not in self.env:
            raise DiscoveryError(f"unknown assignment target at line {stmt.lineno}")
        left = self.env[stmt.target.id]
        right = self.parse_value(stmt.value)
        try:
            if isinstance(stmt.op, ast.Add):
                value = left + right
            elif isinstance(stmt.op, ast.Sub):
                value = left - right
            else:
                raise DiscoveryError(f"unsupported augmented assignment at line {stmt.lineno}")
        except TypeError as exc:
            raise DiscoveryError(f"unsupported augmented assignment at line {stmt.lineno}") from exc
        if not is_supported_value(value):
            raise DiscoveryError(f"unsupported assignment value at line {stmt.lineno}")
        self.env[stmt.target.id] = value

    def bind_target(self, target: ast.AST, value: Any, line_no: int) -> None:
        if isinstance(target, ast.Name):
            if target.id == self.entrypoint:
                raise DiscoveryError(f"assignment to entrypoint is unsupported at line {line_no}")
            self.env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            items = as_iterable_items(value, line_no, "assignment")
            if len(items) != len(target.elts):
                raise DiscoveryError(f"assignment unpacking mismatch at line {line_no}")
            for child, item in zip(target.elts, items):
                self.bind_target(child, item, line_no)
            return
        raise DiscoveryError(f"unsupported assignment target at line {line_no}")

    def collect_imports(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, ast.Import):
                self.visit_import(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                self.visit_import_from(stmt)

    def visit_import(self, stmt: ast.Import) -> None:
        for alias in stmt.names:
            if alias.name not in HELPER_MODULES:
                raise DiscoveryError(f"unsupported import at line {stmt.lineno}")
            self.module_aliases[alias.asname or alias.name] = alias.name

    def visit_import_from(self, stmt: ast.ImportFrom) -> None:
        if stmt.level != 0:
            raise DiscoveryError(f"unsupported import at line {stmt.lineno}")
        if stmt.module == "collections":
            allowed = COLLECTION_CONSTRUCTORS
        elif stmt.module == "decimal":
            allowed = DECIMAL_CONSTRUCTORS
        else:
            raise DiscoveryError(f"unsupported import at line {stmt.lineno}")
        for alias in stmt.names:
            if alias.name == "*" or alias.name not in allowed:
                raise DiscoveryError(f"unsupported import at line {stmt.lineno}")
            self.constructor_aliases[alias.asname or alias.name] = alias.name

    def visit_for_loop(self, stmt: ast.For) -> None:
        if stmt.orelse:
            self.add_loop_test(stmt.lineno, False)
            return
        loop_path = self.active_path
        before_env = self.env.copy()
        try:
            items = self.parse_loop_iterable(stmt.iter)
        except (DiscoveryError, LoopEvaluationError):
            self.add_loop_test(stmt.lineno, False)
            return
        if not items:
            self.add_loop_test(stmt.lineno, False)
            return

        body_pending: list[PendingTest] = []
        original_pending = self.pending
        self.pending = body_pending
        try:
            for index, item in enumerate(items):
                self.env = before_env.copy()
                self.bind_target(stmt.target, item, stmt.lineno)
                self.active_path = loop_path + (index,)
                self.visit_body(stmt.body)
        finally:
            self.pending = original_pending
            self.env = before_env
            self.active_path = loop_path
        self.add_loop_test(stmt.lineno, True)
        self.pending.extend(body_pending)

    def visit_while_loop(self, stmt: ast.While) -> None:
        if stmt.orelse:
            self.add_loop_test(stmt.lineno, False)
            return
        loop_path = self.active_path
        before_env = self.env.copy()
        body_pending: list[PendingTest] = []
        original_pending = self.pending
        self.pending = body_pending
        iterations = 0
        failed = False
        try:
            while True:
                if iterations >= LOOP_ITERATION_LIMIT:
                    failed = True
                    break
                try:
                    should_iterate = self.eval_condition(stmt.test)
                except (DiscoveryError, LoopEvaluationError):
                    failed = True
                    break
                if not should_iterate:
                    break
                self.active_path = loop_path + (iterations,)
                self.visit_body(stmt.body)
                iterations += 1
        finally:
            self.pending = original_pending
            self.env = before_env
            self.active_path = loop_path

        if iterations and not failed:
            self.add_loop_test(stmt.lineno, True)
            self.pending.extend(body_pending)
        else:
            self.add_loop_test(stmt.lineno, False)

    def parse_loop_iterable(self, node: ast.AST) -> list[Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords:
                raise LoopEvaluationError("loop helper keywords are unsupported")
            if node.func.id == "enumerate":
                if len(node.args) != 1:
                    raise LoopEvaluationError("enumerate requires one argument")
                value = self.parse_value(node.args[0])
                return list(enumerate(as_iterable_items(value, line_no, "enumerate")))
            if node.func.id == "range":
                values = [self.parse_integer_value(arg) for arg in node.args]
                if len(values) not in {1, 2, 3}:
                    raise LoopEvaluationError("range requires one to three arguments")
                try:
                    return list(range(*values))
                except ValueError as exc:
                    raise LoopEvaluationError("invalid range") from exc
        value = self.parse_value(node)
        return as_iterable_items(value, line_no, "for loop")

    def parse_integer_value(self, node: ast.AST) -> int:
        value = self.parse_value(node)
        if isinstance(value, bool) or not isinstance(value, int):
            raise LoopEvaluationError("expected integer loop value")
        return value

    def eval_condition(self, node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp):
            values = [self.eval_condition(item) for item in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise LoopEvaluationError("unsupported boolean operator")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self.eval_condition(node.operand)
        if isinstance(node, ast.Compare):
            left = self.parse_value(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self.parse_value(comparator)
                if not self.compare_values(operator, left, right):
                    return False
                left = right
            return True
        return bool(self.parse_value(node))

    def compare_values(self, operator: ast.cmpop, left: Any, right: Any) -> bool:
        try:
            if isinstance(operator, ast.Eq):
                return left == right
            if isinstance(operator, ast.NotEq):
                return left != right
            if isinstance(operator, ast.Lt):
                return left < right
            if isinstance(operator, ast.LtE):
                return left <= right
            if isinstance(operator, ast.Gt):
                return left > right
            if isinstance(operator, ast.GtE):
                return left >= right
            if isinstance(operator, ast.In):
                return left in right
            if isinstance(operator, ast.NotIn):
                return left not in right
        except TypeError as exc:
            raise LoopEvaluationError("unsupported comparison") from exc
        raise LoopEvaluationError("unsupported comparison operator")

    def visit_assert(self, stmt: ast.Assert) -> None:
        if stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {stmt.lineno}")

        test = stmt.test
        if isinstance(test, ast.Compare):
            if self.visit_absdiff_assert(stmt, test):
                return
            self.visit_comparison_assert(stmt, test)
            return

        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            args, actual_expr = self.parse_actual_expression(test.operand, stmt.lineno)
            self.add_test(stmt.lineno, "not", args, actual_expr=actual_expr)
            return

        if isinstance(test, ast.Call):
            if self.call_name(test.func) == "math.isclose":
                self.visit_isclose_assert(stmt, test)
                return
        args, actual_expr = self.parse_actual_expression(test, stmt.lineno)
        self.add_test(stmt.lineno, "truthy", args, actual_expr=actual_expr)

    def visit_comparison_assert(self, stmt: ast.Assert, test: ast.Compare) -> None:
        if len(test.ops) != 1 or len(test.comparators) != 1:
            raise DiscoveryError(f"unsupported comparison at line {stmt.lineno}")
        operator = test.ops[0]
        if type(operator) not in COMPARE_OPERATORS:
            raise DiscoveryError(f"unsupported comparison operator at line {stmt.lineno}")

        left_calls = self.count_entrypoint_calls(test.left)
        right = test.comparators[0]
        right_calls = self.count_entrypoint_calls(right)
        total_calls = left_calls + right_calls
        if total_calls != 1:
            raise DiscoveryError(
                f"assertion must call {self.entrypoint} exactly once at line {stmt.lineno}"
            )

        if isinstance(operator, (ast.Eq, ast.NotEq)):
            if left_calls == 1:
                args, actual_expr = self.parse_actual_expression(test.left, stmt.lineno)
                expected = self.parse_value(right)
            else:
                args, actual_expr = self.parse_actual_expression(right, stmt.lineno)
                expected = self.parse_value(test.left)
            self.add_test(
                stmt.lineno,
                "eq" if isinstance(operator, ast.Eq) else "ne",
                args,
                expected,
                actual_expr=actual_expr,
            )
            return

        args, actual_expr = self.parse_actual_expression(test, stmt.lineno)
        self.add_test(stmt.lineno, "truthy", args, actual_expr=actual_expr)

    def visit_isclose_assert(self, stmt: ast.Assert, call: ast.Call) -> None:
        if len(call.args) != 2:
            raise DiscoveryError(f"math.isclose requires two operands at line {stmt.lineno}")
        args, expected = self.parse_entrypoint_expected_pair(call.args[0], call.args[1], stmt.lineno)
        abs_tol: Any = MATH_ISCLOSE_ABS_TOL
        rel_tol: Any = MATH_ISCLOSE_REL_TOL
        seen: set[str] = set()
        for keyword_arg in call.keywords:
            if keyword_arg.arg not in {"abs_tol", "rel_tol"} or keyword_arg.arg in seen:
                raise DiscoveryError(f"unsupported math.isclose keyword at line {stmt.lineno}")
            seen.add(keyword_arg.arg)
            value = self.parse_numeric_value(keyword_arg.value)
            if value < 0:
                raise DiscoveryError(f"negative tolerance at line {stmt.lineno}")
            if keyword_arg.arg == "abs_tol":
                abs_tol = value
            else:
                rel_tol = value
        self.add_test(
            stmt.lineno,
            "isclose",
            args,
            expected,
            comparison="isclose",
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )

    def visit_absdiff_assert(self, stmt: ast.Assert, test: ast.Compare) -> bool:
        if len(test.ops) != 1 or len(test.comparators) != 1:
            return False
        operator = test.ops[0]
        if not isinstance(operator, (ast.Lt, ast.LtE)):
            return False
        if not (
            isinstance(test.left, ast.Call)
            and isinstance(test.left.func, ast.Name)
            and test.left.func.id == "abs"
            and len(test.left.args) == 1
            and not test.left.keywords
            and isinstance(test.left.args[0], ast.BinOp)
            and isinstance(test.left.args[0].op, ast.Sub)
        ):
            return False
        difference = test.left.args[0]
        args, expected = self.parse_entrypoint_expected_pair(difference.left, difference.right, stmt.lineno)
        abs_tol = self.parse_numeric_value(test.comparators[0])
        if abs_tol < 0:
            raise DiscoveryError(f"negative tolerance at line {stmt.lineno}")
        self.add_test(
            stmt.lineno,
            "absdiff",
            args,
            expected,
            comparison="abs_le" if isinstance(operator, ast.LtE) else "abs_lt",
            abs_tol=abs_tol,
        )
        return True

    def visit_raise_expectation(self, stmt: ast.Try) -> None:
        if stmt.orelse or stmt.finalbody:
            raise DiscoveryError(f"unsupported try block at line {stmt.lineno}")
        if len(stmt.body) != 2:
            raise DiscoveryError(f"raise expectation requires two try statements at line {stmt.lineno}")

        call_stmt, assert_stmt = stmt.body
        if not isinstance(call_stmt, ast.Expr):
            raise DiscoveryError(f"raise expectation must call entrypoint at line {stmt.lineno}")
        args = self.parse_entrypoint_call(call_stmt.value, stmt.lineno)

        if not isinstance(assert_stmt, ast.Assert):
            raise DiscoveryError(f"raise expectation must assert False at line {stmt.lineno}")
        if assert_stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {assert_stmt.lineno}")
        if not (
            isinstance(assert_stmt.test, ast.Constant)
            and assert_stmt.test.value is False
        ):
            raise DiscoveryError(f"raise expectation must assert False at line {assert_stmt.lineno}")

        if len(stmt.handlers) != 1:
            raise DiscoveryError(f"raise expectation needs one handler at line {stmt.lineno}")
        handler = stmt.handlers[0]
        if not isinstance(handler.type, ast.Name):
            raise DiscoveryError(f"unsupported exception handler at line {stmt.lineno}")

        if handler.type.id == "Exception" and handler.name is None:
            if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Pass):
                raise DiscoveryError(f"raise expectation must catch Exception and pass at line {stmt.lineno}")
            self.add_test(stmt.lineno, "raises", args)
            return

        message_match, message_pattern = self.parse_exception_message_match(handler, stmt.lineno)
        self.add_test(
            stmt.lineno,
            "raises",
            args,
            comparison="exception",
            exception_type=handler.type.id,
            message_match=message_match,
            message_pattern=message_pattern,
        )

    def parse_exception_message_match(
        self,
        handler: ast.ExceptHandler,
        line_no: int,
    ) -> tuple[str | None, str | None]:
        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
            return None, None
        if handler.name is None:
            raise DiscoveryError(f"exception message checks require a bound name at line {line_no}")
        if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Assert):
            raise DiscoveryError(f"unsupported exception handler body at line {line_no}")
        assertion = handler.body[0]
        if assertion.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {assertion.lineno}")
        test = assertion.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.In)
            and len(test.comparators) == 1
            and isinstance(test.left, ast.Constant)
            and isinstance(test.left.value, str)
            and self.is_str_call_for_name(test.comparators[0], handler.name)
        ):
            return "contains", test.left.value
        if (
            isinstance(test, ast.Call)
            and self.call_name(test.func) == "re.search"
            and len(test.args) == 2
            and not test.keywords
            and self.is_str_call_for_name(test.args[1], handler.name)
        ):
            pattern = self.parse_value(test.args[0])
            if not isinstance(pattern, str):
                raise DiscoveryError(f"regex pattern must be a string at line {assertion.lineno}")
            return "regex", pattern
        raise DiscoveryError(f"unsupported exception message check at line {line_no}")

    def parse_entrypoint_call(self, node: ast.AST, line_no: int) -> list[Any]:
        args = self.maybe_parse_entrypoint_call(node, line_no)
        if args is None:
            raise DiscoveryError(f"expected call to {self.entrypoint} at line {line_no}")
        return args

    def maybe_parse_entrypoint_call(self, node: ast.AST, line_no: int) -> list[Any] | None:
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == self.entrypoint
        ):
            return None
        if node.keywords:
            raise DiscoveryError(f"keyword arguments are unsupported at line {line_no}")
        return self.parse_call_args(node.args, line_no)

    def parse_call_args(self, args: list[ast.expr], line_no: int) -> list[Any]:
        parsed: list[Any] = []
        for arg in args:
            if isinstance(arg, ast.Starred):
                parsed.extend(as_iterable_items(self.parse_value(arg.value), line_no, "starred argument"))
            else:
                parsed.append(self.parse_value(arg))
        return parsed

    def parse_entrypoint_expected_pair(
        self,
        left: ast.AST,
        right: ast.AST,
        line_no: int,
    ) -> tuple[list[Any], Any]:
        left_args = self.maybe_parse_entrypoint_call(left, line_no)
        if left_args is not None:
            return left_args, self.parse_value(right)
        right_args = self.maybe_parse_entrypoint_call(right, line_no)
        if right_args is not None:
            return right_args, self.parse_value(left)
        raise DiscoveryError(f"expected one operand to call {self.entrypoint} at line {line_no}")

    def count_entrypoint_calls(self, node: ast.AST) -> int:
        return sum(
            1
            for child in ast.walk(node)
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == self.entrypoint
            )
        )

    def parse_actual_expression(
        self,
        node: ast.AST,
        line_no: int,
    ) -> tuple[list[Any], dict[str, Any]]:
        if self.count_entrypoint_calls(node) != 1:
            raise DiscoveryError(
                f"assertion must call {self.entrypoint} exactly once at line {line_no}"
            )
        entrypoint_args: list[list[Any]] = []
        expr = self.parse_expression(node, entrypoint_args)
        if len(entrypoint_args) != 1:
            raise DiscoveryError(
                f"assertion must call {self.entrypoint} exactly once at line {line_no}"
            )
        return entrypoint_args[0], expr

    def parse_expression(
        self,
        node: ast.AST,
        entrypoint_args: list[list[Any]],
        runtime_names: set[str] | None = None,
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return {"op": "value", "value": node.value}
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            if runtime_names is not None and node.id in runtime_names:
                return {"op": "var", "name": node.id}
            return {"op": "value", "value": self.resolve_name(node.id, line_no)}
        if isinstance(node, ast.List):
            return {
                "op": "list",
                "items": [
                    self.parse_expression(item, entrypoint_args, runtime_names)
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Tuple):
            return {
                "op": "tuple",
                "items": [
                    self.parse_expression(item, entrypoint_args, runtime_names)
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Set):
            return {
                "op": "set",
                "items": [
                    self.parse_expression(item, entrypoint_args, runtime_names)
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Dict):
            entries: list[list[dict[str, Any]]] = []
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise DiscoveryError(f"dictionary unpacking is unsupported at line {line_no}")
                entries.append(
                    [
                        self.parse_expression(key_node, entrypoint_args, runtime_names),
                        self.parse_expression(value_node, entrypoint_args, runtime_names),
                    ]
                )
            return {"op": "dict", "entries": entries}
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return {
                "op": "unary",
                "operator": UNARY_OPERATORS[type(node.op)],
                "operand": self.parse_expression(node.operand, entrypoint_args, runtime_names),
            }
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return {
                "op": "binary",
                "operator": BINARY_OPERATORS[type(node.op)],
                "left": self.parse_expression(node.left, entrypoint_args, runtime_names),
                "right": self.parse_expression(node.right, entrypoint_args, runtime_names),
            }
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise DiscoveryError(f"unsupported comparison at line {line_no}")
            operator = node.ops[0]
            if type(operator) not in COMPARE_OPERATORS:
                raise DiscoveryError(f"unsupported comparison operator at line {line_no}")
            return {
                "op": "compare",
                "operator": COMPARE_OPERATORS[type(operator)],
                "left": self.parse_expression(node.left, entrypoint_args, runtime_names),
                "right": self.parse_expression(node.comparators[0], entrypoint_args, runtime_names),
            }
        if isinstance(node, ast.Subscript):
            return self.parse_subscript_expression(node, entrypoint_args, runtime_names)
        if isinstance(node, ast.Call):
            return self.parse_call_expression(node, entrypoint_args, runtime_names)
        raise DiscoveryError(f"unsupported expression at line {line_no}")

    def parse_call_expression(
        self,
        node: ast.Call,
        entrypoint_args: list[list[Any]],
        runtime_names: set[str] | None = None,
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == self.entrypoint
        ):
            if node.keywords:
                raise DiscoveryError(f"keyword arguments are unsupported at line {line_no}")
            if entrypoint_args:
                raise DiscoveryError(
                    f"assertion must call {self.entrypoint} exactly once at line {line_no}"
                )
            entrypoint_args.append(self.parse_call_args(node.args, line_no))
            return result_expr()

        if isinstance(node.func, ast.Name) and node.func.id in PRIMITIVE_FUNCTIONS:
            if node.keywords:
                raise DiscoveryError(f"primitive call keywords are unsupported at line {line_no}")
            self.validate_primitive_call(node.func.id, len(node.args), line_no)
            return {
                "op": "call",
                "name": node.func.id,
                "args": [
                    self.parse_expression(arg, entrypoint_args, runtime_names)
                    for arg in node.args
                ],
            }

        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHODS:
            if node.keywords:
                raise DiscoveryError(f"method call keywords are unsupported at line {line_no}")
            self.validate_string_method_call(node.func.attr, len(node.args), line_no)
            return {
                "op": "method",
                "name": node.func.attr,
                "receiver": self.parse_expression(node.func.value, entrypoint_args, runtime_names),
                "args": [
                    self.parse_expression(arg, entrypoint_args, runtime_names)
                    for arg in node.args
                ],
            }

        raise DiscoveryError(f"unsupported function call at line {line_no}")

    def validate_primitive_call(self, name: str, argc: int, line_no: int) -> None:
        single_arg = {
            "abs",
            "bool",
            "float",
            "frozenset",
            "int",
            "len",
            "list",
            "set",
            "sorted",
            "str",
            "sum",
            "tuple",
        }
        if name in single_arg and argc != 1:
            raise DiscoveryError(f"{name} requires one argument at line {line_no}")
        if name in {"min", "max"} and argc < 1:
            raise DiscoveryError(f"{name} requires at least one argument at line {line_no}")

    def validate_string_method_call(self, name: str, argc: int, line_no: int) -> None:
        if name in {"upper", "lower"} and argc != 0:
            raise DiscoveryError(f"{name} takes no arguments at line {line_no}")
        if name in {"strip", "lstrip", "rstrip"} and argc not in {0, 1}:
            raise DiscoveryError(f"unsupported {name} arguments at line {line_no}")
        if name in {"startswith", "endswith", "count", "find"} and argc != 1:
            raise DiscoveryError(f"{name} requires one argument at line {line_no}")
        if name == "replace" and argc != 2:
            raise DiscoveryError(f"replace requires two arguments at line {line_no}")
        if name == "split" and argc not in {0, 1, 2}:
            raise DiscoveryError(f"unsupported split arguments at line {line_no}")
        if name == "join" and argc != 1:
            raise DiscoveryError(f"join requires one argument at line {line_no}")

    def parse_subscript_expression(
        self,
        node: ast.Subscript,
        entrypoint_args: list[list[Any]],
        runtime_names: set[str] | None = None,
    ) -> dict[str, Any]:
        value = self.parse_expression(node.value, entrypoint_args, runtime_names)
        if isinstance(node.slice, ast.Slice):
            return {
                "op": "slice",
                "value": value,
                "lower": self.parse_expression(node.slice.lower, entrypoint_args, runtime_names)
                if node.slice.lower is not None
                else None,
                "upper": self.parse_expression(node.slice.upper, entrypoint_args, runtime_names)
                if node.slice.upper is not None
                else None,
                "step": self.parse_expression(node.slice.step, entrypoint_args, runtime_names)
                if node.slice.step is not None
                else None,
            }
        return {
            "op": "subscript",
            "value": value,
            "index": self.parse_expression(node.slice, entrypoint_args, runtime_names),
        }

    def resolve_name(self, name: str, line_no: int) -> Any:
        if name in self.env:
            return self.env[name]
        raise DiscoveryError(f"unknown name at line {line_no}")

    def apply_binary_value(self, operator: str, left: Any, right: Any, line_no: int) -> Any:
        try:
            if operator == "add":
                return left + right
            if operator == "sub":
                return left - right
            if operator == "mult":
                return left * right
            if operator == "truediv":
                return left / right
            if operator == "floordiv":
                return left // right
            if operator == "mod":
                return left % right
            if operator == "pow":
                return left ** right
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise DiscoveryError(f"unsupported value expression at line {line_no}") from exc
        raise DiscoveryError(f"unsupported value expression at line {line_no}")

    def parse_subscript_value(self, node: ast.Subscript) -> Any:
        line_no = getattr(node, "lineno", 0)
        value = self.parse_value(node.value)
        try:
            if isinstance(node.slice, ast.Slice):
                lower = self.parse_value(node.slice.lower) if node.slice.lower is not None else None
                upper = self.parse_value(node.slice.upper) if node.slice.upper is not None else None
                step = self.parse_value(node.slice.step) if node.slice.step is not None else None
                return value[slice(lower, upper, step)]
            index = self.parse_value(node.slice)
            return value[index]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DiscoveryError(f"unsupported subscript at line {line_no}") from exc

    def apply_primitive_value_call(self, name: str, args: list[Any], line_no: int) -> Any:
        try:
            if name == "abs":
                return abs(args[0])
            if name == "bool":
                return bool(args[0])
            if name == "float":
                return float(args[0])
            if name == "int":
                return int(args[0])
            if name == "len":
                return len(args[0])
            if name == "list":
                return list(as_iterable_items(args[0], line_no, "list"))
            if name == "tuple":
                return tuple(as_iterable_items(args[0], line_no, "tuple"))
            if name == "set":
                return set(require_hashable_key(item, line_no) for item in as_iterable_items(args[0], line_no, "set"))
            if name == "frozenset":
                return frozenset(require_hashable_key(item, line_no) for item in as_iterable_items(args[0], line_no, "frozenset"))
            if name == "sorted":
                return sorted(as_iterable_items(args[0], line_no, "sorted"))
            if name == "str":
                return str(args[0])
            if name == "sum":
                return sum(as_iterable_items(args[0], line_no, "sum"))
            if name == "max":
                values = args if len(args) > 1 else as_iterable_items(args[0], line_no, "max")
                return max(values)
            if name == "min":
                values = args if len(args) > 1 else as_iterable_items(args[0], line_no, "min")
                return min(values)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise DiscoveryError(f"unsupported primitive call at line {line_no}") from exc
        raise DiscoveryError(f"unsupported primitive call at line {line_no}")

    def parse_value(self, node: ast.AST) -> Any:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return node.value
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id, line_no)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self.parse_value(node.operand)
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                raise DiscoveryError(f"unsupported unary value at line {line_no}")
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            left = self.parse_value(node.left)
            right = self.parse_value(node.right)
            value = self.apply_binary_value(BINARY_OPERATORS[type(node.op)], left, right, line_no)
            if not is_supported_value(value):
                raise DiscoveryError(f"unsupported value expression at line {line_no}")
            return value
        if isinstance(node, ast.List):
            return [self.parse_value(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.parse_value(item) for item in node.elts)
        if isinstance(node, ast.Set):
            return set(require_hashable_key(self.parse_value(item), line_no) for item in node.elts)
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise DiscoveryError(f"dictionary unpacking is unsupported at line {line_no}")
                key = require_hashable_key(self.parse_value(key_node), line_no)
                result[key] = self.parse_value(value_node)
            return result
        if isinstance(node, ast.Subscript):
            return self.parse_subscript_value(node)
        if isinstance(node, ast.Call):
            if self.call_name(node.func) is not None:
                return self.parse_constructor_call(node)
            if isinstance(node.func, ast.Name) and node.func.id in PRIMITIVE_FUNCTIONS:
                if node.keywords:
                    raise DiscoveryError(f"primitive call keywords are unsupported at line {line_no}")
                self.validate_primitive_call(node.func.id, len(node.args), line_no)
                args = [self.parse_value(arg) for arg in node.args]
                return self.apply_primitive_value_call(node.func.id, args, line_no)
            return self.parse_constructor_call(node)
        raise DiscoveryError(f"unsupported value expression at line {line_no}")

    def parse_numeric_value(self, node: ast.AST) -> Any:
        value = self.parse_value(node)
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise DiscoveryError(f"expected numeric value at line {getattr(node, 'lineno', '?')}")
        return value

    def parse_constructor_call(self, node: ast.Call) -> Any:
        line_no = getattr(node, "lineno", 0)
        name = self.call_name(node.func)
        if name is None:
            raise DiscoveryError(f"unsupported constructor at line {line_no}")
        if node.keywords:
            raise DiscoveryError(f"constructor keywords are unsupported at line {line_no}")

        if name in {"set", "frozenset"}:
            if len(node.args) > 1:
                raise DiscoveryError(f"{name} accepts at most one argument at line {line_no}")
            items = [] if not node.args else as_iterable_items(self.parse_value(node.args[0]), line_no, name)
            values = [require_hashable_key(item, line_no) for item in items]
            return set(values) if name == "set" else frozenset(values)

        if name == "Counter":
            if len(node.args) > 1:
                raise DiscoveryError(f"Counter accepts at most one argument at line {line_no}")
            if not node.args:
                return Counter()
            seed = self.parse_value(node.args[0])
            if isinstance(seed, (dict, defaultdict, Counter)):
                return Counter(dict(seed))
            return Counter(as_iterable_items(seed, line_no, "Counter"))

        if name == "deque":
            if len(node.args) > 1:
                raise DiscoveryError(f"deque accepts at most one argument at line {line_no}")
            items = [] if not node.args else as_iterable_items(self.parse_value(node.args[0]), line_no, "deque")
            return deque(items)

        if name == "defaultdict":
            if len(node.args) > 2:
                raise DiscoveryError(f"defaultdict accepts at most two arguments at line {line_no}")
            factory = None
            mapping: dict[Any, Any] = {}
            if node.args:
                factory = self.parse_defaultdict_factory(node.args[0])
            if len(node.args) == 2:
                seed = self.parse_value(node.args[1])
                if not isinstance(seed, (dict, defaultdict, Counter)):
                    raise DiscoveryError(f"defaultdict mapping must be a dictionary at line {line_no}")
                mapping = dict(seed)
            return defaultdict(factory, mapping)

        if name == "Decimal":
            if len(node.args) != 1:
                raise DiscoveryError(f"Decimal requires one argument at line {line_no}")
            return parse_decimal_value(self.parse_value(node.args[0]), line_no)

        raise DiscoveryError(f"unsupported constructor at line {line_no}")

    def parse_defaultdict_factory(self, node: ast.AST) -> Any:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant) and node.value is None:
            return None
        if isinstance(node, ast.Name):
            return default_factory_from_name(node.id, line_no)
        raise DiscoveryError(f"unsupported defaultdict factory at line {line_no}")

    def call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in {"set", "frozenset"}:
                return node.id
            return self.constructor_aliases.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = self.module_aliases.get(node.value.id)
            if module == "collections" and node.attr in COLLECTION_CONSTRUCTORS:
                return node.attr
            if module == "decimal" and node.attr in DECIMAL_CONSTRUCTORS:
                return node.attr
            if module == "math" and node.attr == "isclose":
                return "math.isclose"
            if module == "re" and node.attr == "search":
                return "re.search"
        return None

    def is_str_call_for_name(self, node: ast.AST, name: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == name
        )

    def add_test(
        self,
        line_no: int,
        kind: str,
        args: list[Any],
        expected: Any = None,
        *,
        actual_expr: dict[str, Any] | None = None,
        comparison: str = "standard",
        abs_tol: Any = None,
        rel_tol: Any = None,
        exception_type: str | None = None,
        message_match: str | None = None,
        message_pattern: str | None = None,
        mutation_arg_names: dict[str, int] | None = None,
        mutation_assignment: str | None = None,
    ) -> None:
        expectations = self.expectations_for(line_no)
        self.pending.append(
            PendingTest(
                source_path=self.source_path,
                line=line_no,
                kind=kind,
                args=args,
                iteration_path=self.active_path,
                actual_expr=result_expr() if actual_expr is None else actual_expr,
                expected=expected,
                comparison=comparison,
                abs_tol=abs_tol,
                rel_tol=rel_tol,
                exception_type=exception_type,
                message_match=message_match,
                message_pattern=message_pattern,
                expect_stdout=expectations.get("expect_stdout"),
                expect_stderr=expectations.get("expect_stderr"),
                mutation_arg_names={} if mutation_arg_names is None else mutation_arg_names,
                mutation_assignment=mutation_assignment,
            )
        )

    def add_loop_test(self, line_no: int, passed: bool) -> None:
        self.pending.append(
            PendingTest(
                source_path=self.source_path,
                line=line_no,
                kind="loop",
                iteration_path=self.active_path,
                loop_pass=passed,
            )
        )

    def expectations_for(self, test_line: int) -> dict[str, str]:
        expectations: dict[str, str] = {}
        line_no = test_line - 1
        while line_no >= 1:
            text = self.source_lines[line_no - 1].strip()
            if not text:
                break
            if not text.startswith("#"):
                break
            match = EXPECT_RE.fullmatch(text)
            if match is None:
                if text.startswith("# expect_stdout:") or text.startswith("# expect_stderr:"):
                    raise DiscoveryError(f"invalid output expectation at line {line_no}")
                break
            key = match.group(1)
            if key in expectations:
                raise DiscoveryError(f"duplicate {key} expectation at line {line_no}")
            expectations[key] = parse_expectation_value(match.group(2), line_no)
            line_no -= 1
        return expectations


def assign_test_ids(pending: list[PendingTest]) -> list[TestCase]:
    bases = [test_id_base(test.source_path, test.line, test.iteration_path) for test in pending]
    counts = Counter(bases)
    seen: defaultdict[str, int] = defaultdict(int)
    cases: list[TestCase] = []
    for test, base in zip(pending, bases):
        if counts[base] > 1:
            index = seen[base]
            seen[base] += 1
            test_id = f"{base}#{index}"
        else:
            test_id = base
        cases.append(
            TestCase(
                id=test_id,
                source_path=test.source_path,
                line=test.line,
                kind=test.kind,
                args=test.args,
                iteration_path=test.iteration_path,
                actual_expr=test.actual_expr,
                expected=test.expected,
                comparison=test.comparison,
                loop_pass=test.loop_pass,
                abs_tol=test.abs_tol,
                rel_tol=test.rel_tol,
                exception_type=test.exception_type,
                message_match=test.message_match,
                message_pattern=test.message_pattern,
                expect_stdout=test.expect_stdout,
                expect_stderr=test.expect_stderr,
                mutation_arg_names=test.mutation_arg_names,
                mutation_assignment=test.mutation_assignment,
            )
        )
    return cases


def test_id_base(source_path: str, line_no: int, iteration_path: tuple[int, ...]) -> str:
    suffix = "".join(f":{index}" for index in iteration_path)
    return f"{source_path}:{line_no}{suffix}"


def is_test_like_non_python(path: Path) -> bool:
    return path.suffix != ".py" and bool(TEST_LIKE_STEM_RE.fullmatch(path.stem))


def discover_tests(tests_dir: Path | str, entrypoint: str) -> list[TestCase]:
    root = Path(tests_dir)
    if not root.is_dir():
        raise DiscoveryError("tests_dir is required")
    cases: list[TestCase] = []
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        if path.name in set(SUPPORTED_LANGS.values()):
            continue
        if path.suffix != ".py":
            if is_test_like_non_python(path):
                raise DiscoveryError(f"non-python test file is unsupported: {relative_path}")
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
        except (OSError, SyntaxError) as exc:
            raise DiscoveryError(f"cannot read or parse {relative_path}") from exc
        cases.extend(TestDiscoverer(entrypoint, source.splitlines(), relative_path).discover(tree))
    if not cases:
        raise DiscoveryError("no tests discovered")
    return cases


def tag_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def default_factory_name(factory: Any) -> str | None:
    if factory is None:
        return None
    name = getattr(factory, "__name__", None)
    if isinstance(name, str) and name in DEFAULTDICT_FACTORIES and name != "None":
        return name
    return None


def encode_value(value: Any) -> dict[str, Any]:
    if value is None or isinstance(value, bool):
        return {"type": "scalar", "value": value}
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return {"type": "scalar", "value": value}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, list):
        return {"type": "list", "items": [encode_value(item) for item in value]}
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [encode_value(item) for item in value]}
    if isinstance(value, defaultdict):
        entries = [[encode_value(key), encode_value(item)] for key, item in value.items()]
        return {
            "type": "defaultdict",
            "factory": default_factory_name(value.default_factory),
            "entries": sorted(entries, key=lambda entry: tag_sort_key(entry[0])),
        }
    if isinstance(value, Counter):
        entries = [[encode_value(key), encode_value(count)] for key, count in value.items()]
        return {
            "type": "counter",
            "entries": sorted(entries, key=lambda entry: tag_sort_key(entry[0])),
        }
    if isinstance(value, dict):
        entries = [[encode_value(key), encode_value(item)] for key, item in value.items()]
        return {
            "type": "dict",
            "entries": sorted(entries, key=lambda entry: tag_sort_key(entry[0])),
        }
    if isinstance(value, deque):
        return {"type": "deque", "items": [encode_value(item) for item in value]}
    if isinstance(value, frozenset):
        items = [encode_value(item) for item in value]
        return {"type": "frozenset", "items": sorted(items, key=tag_sort_key)}
    if isinstance(value, set):
        items = [encode_value(item) for item in value]
        return {"type": "set", "items": sorted(items, key=tag_sort_key)}
    raise DiscoveryError(f"unsupported value for execution: {value!r}")


def encode_optional_value(value: Any) -> dict[str, Any] | None:
    return None if value is None else encode_value(value)


def encode_expr(expr: dict[str, Any]) -> dict[str, Any]:
    op = expr["op"]
    if op == "value":
        return {"op": "value", "value": encode_value(expr["value"])}
    if op == "var":
        return {"op": "var", "name": expr["name"]}
    if op == "result":
        return {"op": "result"}
    if op in {"list", "tuple", "set"}:
        return {"op": op, "items": [encode_expr(item) for item in expr["items"]]}
    if op == "dict":
        return {
            "op": "dict",
            "entries": [
                [encode_expr(key), encode_expr(value)]
                for key, value in expr["entries"]
            ],
        }
    if op == "unary":
        return {
            "op": "unary",
            "operator": expr["operator"],
            "operand": encode_expr(expr["operand"]),
        }
    if op == "binary":
        return {
            "op": "binary",
            "operator": expr["operator"],
            "left": encode_expr(expr["left"]),
            "right": encode_expr(expr["right"]),
        }
    if op == "compare":
        return {
            "op": "compare",
            "operator": expr["operator"],
            "left": encode_expr(expr["left"]),
            "right": encode_expr(expr["right"]),
        }
    if op == "call":
        return {
            "op": "call",
            "name": expr["name"],
            "args": [encode_expr(arg) for arg in expr["args"]],
        }
    if op == "method":
        return {
            "op": "method",
            "name": expr["name"],
            "receiver": encode_expr(expr["receiver"]),
            "args": [encode_expr(arg) for arg in expr["args"]],
        }
    if op == "subscript":
        return {
            "op": "subscript",
            "value": encode_expr(expr["value"]),
            "index": encode_expr(expr["index"]),
        }
    if op == "slice":
        return {
            "op": "slice",
            "value": encode_expr(expr["value"]),
            "lower": encode_expr(expr["lower"]) if expr["lower"] is not None else None,
            "upper": encode_expr(expr["upper"]) if expr["upper"] is not None else None,
            "step": encode_expr(expr["step"]) if expr["step"] is not None else None,
        }
    raise DiscoveryError(f"unsupported expression operation: {op}")


def case_to_json(case: TestCase, default_abs_tol: float | None = None) -> dict[str, Any]:
    return {
        "id": case.id,
        "kind": case.kind,
        "comparison": case.comparison,
        "args": [encode_value(arg) for arg in case.args],
        "actual_expr": encode_expr(case.actual_expr),
        "expected": encode_optional_value(case.expected),
        "abs_tol": encode_optional_value(case.abs_tol),
        "rel_tol": encode_optional_value(case.rel_tol),
        "default_abs_tol": encode_optional_value(default_abs_tol),
        "exception_type": case.exception_type,
        "message_match": case.message_match,
        "message_pattern": case.message_pattern,
        "expect_stdout": case.expect_stdout,
        "expect_stderr": case.expect_stderr,
        "mutation_arg_names": case.mutation_arg_names,
        "mutation_assignment": case.mutation_assignment,
    }


def tag_is_scalar(tag: dict[str, Any], expected_type: type | tuple[type, ...] | None = None) -> bool:
    if not isinstance(tag, dict) or tag.get("type") != "scalar":
        return False
    if expected_type is None:
        return True
    return isinstance(tag.get("value"), expected_type)


def tag_is_numeric(tag: dict[str, Any]) -> bool:
    if not isinstance(tag, dict):
        return False
    if tag.get("type") == "decimal":
        return True
    if tag.get("type") != "scalar":
        return False
    value = tag.get("value")
    return not isinstance(value, bool) and isinstance(value, (int, float))


def tag_to_decimal(tag: dict[str, Any]) -> Decimal:
    if tag.get("type") == "decimal":
        return Decimal(str(tag.get("value")))
    return Decimal(str(tag.get("value")))


def runtime_numeric_close(
    left: dict[str, Any],
    right: dict[str, Any],
    abs_tol: Any = None,
    rel_tol: Any = None,
) -> bool:
    if not tag_is_numeric(left) or not tag_is_numeric(right):
        return False
    abs_value = Decimal("0") if abs_tol is None else Decimal(str(abs_tol))
    rel_value = Decimal("0") if rel_tol is None else Decimal(str(rel_tol))
    left_value = tag_to_decimal(left)
    right_value = tag_to_decimal(right)
    diff = abs(left_value - right_value)
    limit = max(abs_value, rel_value * max(abs(left_value), abs(right_value)))
    return diff <= limit


def tag_entries(tag: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return list(tag.get("entries") or [])


def tag_items(tag: dict[str, Any]) -> list[dict[str, Any]]:
    return list(tag.get("items") or [])


def tag_unordered_equal(
    left_items: list[dict[str, Any]],
    right_items: list[dict[str, Any]],
    abs_tol: Any = None,
    rel_tol: Any = None,
) -> bool:
    unmatched = list(right_items)
    for left_item in left_items:
        for index, right_item in enumerate(unmatched):
            if tag_deep_equal(left_item, right_item, abs_tol, rel_tol):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def tag_mapping_equal(
    left: dict[str, Any],
    right: dict[str, Any],
    abs_tol: Any = None,
    rel_tol: Any = None,
) -> bool:
    left_entries = tag_entries(left)
    right_entries = tag_entries(right)
    if len(left_entries) != len(right_entries):
        return False
    unmatched = list(right_entries)
    for left_key, left_value in left_entries:
        for index, (right_key, right_value) in enumerate(unmatched):
            if tag_deep_equal(left_key, right_key, abs_tol, rel_tol) and tag_deep_equal(
                left_value, right_value, abs_tol, rel_tol
            ):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def tag_deep_equal(
    left: dict[str, Any],
    right: dict[str, Any],
    abs_tol: Any = None,
    rel_tol: Any = None,
) -> bool:
    if tag_is_numeric(left) and tag_is_numeric(right):
        if abs_tol is not None or rel_tol is not None:
            return runtime_numeric_close(left, right, abs_tol, rel_tol)
        return tag_to_decimal(left) == tag_to_decimal(right)

    left_type = left.get("type")
    right_type = right.get("type")
    if left_type == "scalar" or right_type == "scalar":
        return left_type == right_type and left.get("value") == right.get("value")

    mapping_types = {"dict", "defaultdict", "counter"}
    if left_type in mapping_types or right_type in mapping_types:
        return left_type in mapping_types and right_type in mapping_types and tag_mapping_equal(
            left, right, abs_tol, rel_tol
        )

    sequence_types = {"list", "tuple", "deque"}
    if left_type in sequence_types or right_type in sequence_types:
        if left_type != right_type:
            return False
        left_items = tag_items(left)
        right_items = tag_items(right)
        return len(left_items) == len(right_items) and all(
            tag_deep_equal(left_item, right_items[index], abs_tol, rel_tol)
            for index, left_item in enumerate(left_items)
        )

    set_types = {"set", "frozenset"}
    if left_type in set_types or right_type in set_types:
        return left_type in set_types and right_type in set_types and len(tag_items(left)) == len(
            tag_items(right)
        ) and tag_unordered_equal(tag_items(left), tag_items(right), abs_tol, rel_tol)

    if left_type == "decimal" or right_type == "decimal":
        return left_type == right_type and left.get("value") == right.get("value")
    return left == right


def tag_truthy(tag: dict[str, Any]) -> bool:
    kind = tag.get("type")
    if kind == "scalar":
        return bool(tag.get("value"))
    if kind == "decimal":
        return tag_to_decimal(tag) != 0
    if kind in {"list", "tuple", "deque", "set", "frozenset"}:
        return bool(tag_items(tag))
    if kind in {"dict", "defaultdict", "counter"}:
        return bool(tag_entries(tag))
    return True


def effective_case_abs_tol(case: TestCase, default_abs_tol: float | None) -> Any:
    return case.abs_tol if case.abs_tol is not None else default_abs_tol


def target_message_matches(case: TestCase, message: str) -> bool:
    if case.message_match is None:
        return True
    pattern = case.message_pattern or ""
    if case.message_match == "contains":
        return pattern in message
    if case.message_match == "regex":
        try:
            return re.search(pattern, message) is not None
        except re.error:
            return False
    return False


def target_exception_matches(case: TestCase, result: dict[str, Any]) -> bool:
    if not result.get("raised"):
        return False
    expected_type = case.exception_type
    actual_type = str(result.get("exception_type") or "Exception")
    if expected_type is not None and expected_type != "Exception" and actual_type != expected_type:
        return False
    return target_message_matches(case, str(result.get("message") or ""))


def target_case_matches(
    case: TestCase,
    result: dict[str, Any],
    default_abs_tol: float | None,
) -> bool:
    if case.kind == "raises":
        passed = target_exception_matches(case, result)
    elif result.get("raised"):
        passed = False
    else:
        actual = result.get("actual")
        if not isinstance(actual, dict):
            passed = False
        elif case.kind == "mutation":
            passed = tag_truthy(actual)
        elif case.kind == "eq":
            passed = tag_deep_equal(actual, encode_value(case.expected), effective_case_abs_tol(case, default_abs_tol), case.rel_tol)
        elif case.kind == "ne":
            passed = not tag_deep_equal(actual, encode_value(case.expected), effective_case_abs_tol(case, default_abs_tol), case.rel_tol)
        elif case.kind == "isclose":
            passed = runtime_numeric_close(actual, encode_value(case.expected), case.abs_tol, case.rel_tol)
        elif case.kind == "absdiff":
            expected = encode_value(case.expected)
            if not tag_is_numeric(actual) or not tag_is_numeric(expected):
                passed = False
            else:
                diff = abs(tag_to_decimal(actual) - tag_to_decimal(expected))
                tolerance = Decimal(str(case.abs_tol))
                passed = diff < tolerance if case.comparison == "abs_lt" else diff <= tolerance
        elif case.kind == "truthy":
            passed = tag_truthy(actual)
        elif case.kind == "not":
            passed = not tag_truthy(actual)
        else:
            passed = False

    if case.expect_stdout is not None:
        passed = passed and result.get("stdout") == case.expect_stdout
    if case.expect_stderr is not None:
        passed = passed and result.get("stderr") == case.expect_stderr
    return bool(passed)


def split_top_level(text: str, separator: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string: str | None = None
    escaped = False
    pairs = {"<": ">", "(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for index, char in enumerate(text):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in {"'", '"'}:
            in_string = char
            continue
        if char in pairs:
            depth += 1
            continue
        if char in closing and depth > 0:
            depth -= 1
            continue
        if char == separator and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def strip_top_level_default(param: str) -> str:
    depth = 0
    for index, char in enumerate(param):
        if char in "<([{":
            depth += 1
        elif char in ">)]}" and depth > 0:
            depth -= 1
        elif char == "=" and depth == 0:
            return param[:index].strip()
    return param.strip()


def json_source_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def cpp_string_literal(value: str) -> str:
    return json_source_string(value)


def rust_string_literal(value: str) -> str:
    return json_source_string(value)


def normalize_cpp_type(type_text: str | None) -> str | None:
    if type_text is None:
        return None
    text = re.sub(r"\bconst\b", "", type_text).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" &", "&").replace("& ", "&").replace(" *", "*").replace("* ", "*")
    while text.endswith("&") or text.endswith("*"):
        text = text[:-1].strip()
    return text or None


def normalize_rust_type(type_text: str | None) -> str | None:
    if type_text is None:
        return None
    text = type_text.strip()
    while text.startswith("&"):
        text = text[1:].strip()
        if text.startswith("'"):
            text = text.split(maxsplit=1)[1] if " " in text else ""
        if text.startswith("mut "):
            text = text[4:].strip()
    return text or None


def template_args(type_text: str | None, names: tuple[str, ...]) -> list[str] | None:
    if type_text is None:
        return None
    compact = normalize_cpp_type(type_text) or type_text.strip()
    for name in names:
        for prefix in (f"std::{name}<", f"{name}<"):
            if not compact.startswith(prefix):
                continue
            args_start = len(prefix)
            depth = 1
            for index in range(args_start, len(compact)):
                char = compact[index]
                if char == "<":
                    depth += 1
                elif char == ">":
                    depth -= 1
                    if depth == 0:
                        return split_top_level(compact[args_start:index])
    return None


def rust_template_args(type_text: str | None, names: tuple[str, ...]) -> list[str] | None:
    if type_text is None:
        return None
    compact = normalize_rust_type(type_text) or type_text.strip()
    for name in names:
        for prefix in (f"std::collections::{name}<", f"{name}<"):
            if not compact.startswith(prefix):
                continue
            args_start = len(prefix)
            depth = 1
            for index in range(args_start, len(compact)):
                char = compact[index]
                if char == "<":
                    depth += 1
                elif char == ">":
                    depth -= 1
                    if depth == 0:
                        return split_top_level(compact[args_start:index])
    return None


def cpp_optional_inner(type_text: str | None) -> str | None:
    args = template_args(type_text, ("optional",))
    return args[0] if args else None


def rust_option_inner(type_text: str | None) -> str | None:
    args = rust_template_args(type_text, ("Option",))
    return args[0] if args else None


def cpp_sequence_inner(type_text: str | None) -> tuple[str, str] | None:
    for name, concrete in (("vector", "std::vector"), ("deque", "std::deque"), ("list", "std::vector")):
        args = template_args(type_text, (name,))
        if args:
            return concrete, args[0]
    return None


def cpp_set_inner(type_text: str | None) -> tuple[str, str] | None:
    for name, concrete in (("set", "std::set"), ("unordered_set", "std::unordered_set")):
        args = template_args(type_text, (name,))
        if args:
            return concrete, args[0]
    return None


def cpp_map_args(type_text: str | None) -> tuple[str, str, str] | None:
    for name, concrete in (("unordered_map", "std::unordered_map"), ("map", "std::map")):
        args = template_args(type_text, (name,))
        if args and len(args) >= 2:
            return concrete, args[0], args[1]
    return None


def rust_vec_inner(type_text: str | None) -> str | None:
    args = rust_template_args(type_text, ("Vec",))
    return args[0] if args else None


def rust_set_inner(type_text: str | None) -> tuple[str, str] | None:
    for name in ("HashSet", "BTreeSet"):
        args = rust_template_args(type_text, (name,))
        if args:
            return name, args[0]
    return None


def rust_map_args(type_text: str | None) -> tuple[str, str, str] | None:
    for name in ("HashMap", "BTreeMap"):
        args = rust_template_args(type_text, (name,))
        if args and len(args) >= 2:
            return name, args[0], args[1]
    return None


def cpp_unify_types(types: list[str]) -> str:
    concrete = [item for item in types if item != "std::nullopt_t"]
    if not concrete:
        return "std::optional<long long>"
    if any(item.startswith("std::optional<") for item in concrete) or len(concrete) != len(types):
        inner = cpp_unify_types([item[14:-1] if item.startswith("std::optional<") else item for item in concrete])
        return f"std::optional<{inner}>"
    if any(item in {"long double", "double", "float"} for item in concrete):
        return "long double"
    first = concrete[0]
    if all(item == first for item in concrete):
        return first
    if all(item in {"int", "long", "long long"} for item in concrete):
        return "long long"
    return first


def cpp_type_for_value(value: Any, context_type: str | None = None) -> str:
    normalized = normalize_cpp_type(context_type)
    optional_inner = cpp_optional_inner(normalized)
    if optional_inner is not None:
        return f"std::optional<{optional_inner}>"
    if value is None:
        return "std::nullopt_t"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "long long"
    if isinstance(value, (float, Decimal)):
        return "long double"
    if isinstance(value, str):
        return "std::string"
    sequence = cpp_sequence_inner(normalized)
    if isinstance(value, (list, tuple, deque)):
        inner = sequence[1] if sequence else cpp_unify_types([cpp_type_for_value(item) for item in value])
        container = sequence[0] if sequence else ("std::deque" if isinstance(value, deque) else "std::vector")
        if isinstance(value, tuple):
            item_types = [cpp_type_for_value(item) for item in value]
            return f"std::tuple<{', '.join(item_types)}>"
        return f"{container}<{inner}>"
    map_context = cpp_map_args(normalized)
    if isinstance(value, (dict, defaultdict, Counter)):
        entries = list(value.items())
        key_type = map_context[1] if map_context else cpp_unify_types([cpp_type_for_value(key) for key, _ in entries] or ["std::string"])
        value_type = map_context[2] if map_context else (
            "long long" if isinstance(value, Counter) else cpp_unify_types([cpp_type_for_value(item) for _, item in entries] or ["long long"])
        )
        container = map_context[0] if map_context else "std::map"
        return f"{container}<{key_type}, {value_type}>"
    set_context = cpp_set_inner(normalized)
    if isinstance(value, (set, frozenset)):
        inner = set_context[1] if set_context else cpp_unify_types([cpp_type_for_value(item) for item in value] or ["long long"])
        container = set_context[0] if set_context else "std::set"
        return f"{container}<{inner}>"
    return "auto"


def render_cpp_value(value: Any, context_type: str | None = None) -> str:
    normalized = normalize_cpp_type(context_type)
    optional_inner = cpp_optional_inner(normalized)
    if optional_inner is not None:
        if value is None:
            return f"std::optional<{optional_inner}>{{}}"
        return f"std::optional<{optional_inner}>{{{render_cpp_value(value, optional_inner)}}}"
    if value is None:
        return "std::nullopt"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return f"std::stold({cpp_string_literal(str(value))})"
    if isinstance(value, str):
        return f"std::string({cpp_string_literal(value)})"
    if isinstance(value, tuple):
        item_types = [cpp_type_for_value(item) for item in value]
        items = ", ".join(render_cpp_value(item, item_type) for item, item_type in zip(value, item_types))
        return f"std::tuple<{', '.join(item_types)}>{{{items}}}"
    sequence = cpp_sequence_inner(normalized)
    if isinstance(value, (list, deque)):
        value_type = cpp_type_for_value(value, normalized)
        inner = sequence[1] if sequence else template_args(value_type, ("vector", "deque"))[0]  # type: ignore[index]
        items = ", ".join(render_cpp_value(item, inner) for item in value)
        return f"{value_type}{{{items}}}"
    map_context = cpp_map_args(normalized)
    if isinstance(value, (dict, defaultdict, Counter)):
        value_type = cpp_type_for_value(value, normalized)
        key_type = map_context[1] if map_context else (cpp_map_args(value_type) or ("", "std::string", "long long"))[1]
        item_type = map_context[2] if map_context else (cpp_map_args(value_type) or ("", "std::string", "long long"))[2]
        entries = list(value.items())
        rendered = ", ".join(
            "{" + render_cpp_value(key, key_type) + ", " + render_cpp_value(count if isinstance(value, Counter) else item, item_type) + "}"
            for key, item in entries
            for count in ([item] if isinstance(value, Counter) else [None])
        )
        return f"{value_type}{{{rendered}}}"
    set_context = cpp_set_inner(normalized)
    if isinstance(value, (set, frozenset)):
        value_type = cpp_type_for_value(value, normalized)
        inner = set_context[1] if set_context else (cpp_set_inner(value_type) or ("", "long long"))[1]
        items = ", ".join(render_cpp_value(item, inner) for item in value)
        return f"{value_type}{{{items}}}"
    raise DiscoveryError(f"unsupported C++ value: {value!r}")


def render_rust_value(value: Any, context_type: str | None = None) -> str:
    normalized = normalize_rust_type(context_type)
    option_inner = rust_option_inner(normalized)
    if option_inner is not None:
        if value is None:
            return f"None::<{option_inner}>"
        return f"Some({render_rust_value(value, option_inner)})"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        if normalized in {"f32", "f64"}:
            return f"{value}.0"
        return str(value)
    if isinstance(value, (float, Decimal)):
        return str(value)
    if isinstance(value, str):
        if normalized in {"&str", "str"}:
            return rust_string_literal(value)
        return f"String::from({rust_string_literal(value)})"
    if isinstance(value, tuple):
        items = ", ".join(render_rust_value(item) for item in value)
        comma = "," if len(value) == 1 else ""
        return f"({items}{comma})"
    inner_context = rust_vec_inner(normalized)
    if isinstance(value, (list, deque)):
        items = ", ".join(render_rust_value(item, inner_context) for item in value)
        return f"vec![{items}]"
    map_context = rust_map_args(normalized)
    if isinstance(value, (dict, defaultdict, Counter)):
        container = map_context[0] if map_context else "HashMap"
        key_type = map_context[1] if map_context else None
        item_type = map_context[2] if map_context else None
        entries = list(value.items())
        lines = [f"let mut __bcg_map = std::collections::{container}::new();"]
        for key, item in entries:
            value_item = item
            lines.append(
                f"__bcg_map.insert({render_rust_value(key, key_type)}, {render_rust_value(value_item, item_type)});"
            )
        lines.append("__bcg_map")
        return "{ " + " ".join(lines) + " }"
    set_context = rust_set_inner(normalized)
    if isinstance(value, (set, frozenset)):
        container = set_context[0] if set_context else "HashSet"
        inner_type = set_context[1] if set_context else None
        lines = [f"let mut __bcg_set = std::collections::{container}::new();"]
        for item in value:
            lines.append(f"__bcg_set.insert({render_rust_value(item, inner_type)});")
        lines.append("__bcg_set")
        return "{ " + " ".join(lines) + " }"
    raise DiscoveryError(f"unsupported Rust value: {value!r}")


def parse_cpp_param_types(solution_source: str, entrypoint: str) -> list[str]:
    pattern = re.compile(
        rf"(?:^|[;\n}}])\s*(?:template\s*<[^>]+>\s*)?(?:[\w:<>~,\s*&]+?)\s+{re.escape(entrypoint)}\s*\(([^)]*)\)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(solution_source)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw or raw == "void":
        return []
    params: list[str] = []
    for param in split_top_level(raw):
        cleaned = strip_top_level_default(param)
        cleaned = re.sub(r"\s+[A-Za-z_][A-Za-z0-9_]*\s*(?:\[[^\]]*\])?$", "", cleaned).strip()
        params.append(cleaned)
    return params


def parse_rust_param_types(solution_source: str, entrypoint: str) -> list[str]:
    pattern = re.compile(rf"(?:pub\s+)?(?:async\s+)?fn\s+{re.escape(entrypoint)}\s*\((.*?)\)", re.DOTALL)
    match = pattern.search(solution_source)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    params: list[str] = []
    for param in split_top_level(raw):
        if ":" not in param:
            continue
        params.append(param.split(":", 1)[1].strip())
    return params


def rust_entrypoint_returns_future(solution_source: str, entrypoint: str) -> bool:
    if re.search(rf"(?:pub\s+)?async\s+fn\s+{re.escape(entrypoint)}\s*\(", solution_source):
        return True
    signature = re.search(
        rf"(?:pub\s+)?fn\s+{re.escape(entrypoint)}\s*\([^)]*\)\s*->\s*([^{{;]+)",
        solution_source,
        re.DOTALL,
    )
    return bool(signature and "Future" in signature.group(1))


def value_contains_deque(value: Any) -> bool:
    if isinstance(value, deque):
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(value_contains_deque(item) for item in value)
    if isinstance(value, (dict, defaultdict, Counter)):
        return any(value_contains_deque(key) or value_contains_deque(item) for key, item in value.items())
    return False


def expr_contains_deque(expr: dict[str, Any]) -> bool:
    op = expr.get("op")
    if op == "value":
        return value_contains_deque(expr.get("value"))
    if op in {"list", "tuple", "set"}:
        return any(expr_contains_deque(item) for item in expr.get("items", []))
    if op == "dict":
        return any(expr_contains_deque(key) or expr_contains_deque(value) for key, value in expr.get("entries", []))
    for key in ("operand", "left", "right", "receiver", "value", "index", "lower", "upper", "step"):
        item = expr.get(key)
        if isinstance(item, dict) and expr_contains_deque(item):
            return True
    return any(expr_contains_deque(item) for item in expr.get("args", []))


def case_requires_deque(case: TestCase) -> bool:
    return (
        any(value_contains_deque(arg) for arg in case.args)
        or value_contains_deque(case.expected)
        or expr_contains_deque(case.actual_expr)
    )


def render_cpp_expr(expr: dict[str, Any], variables: dict[str, str]) -> str:
    op = expr["op"]
    if op == "result":
        return "__bcg_result"
    if op == "var":
        return variables[expr["name"]]
    if op == "value":
        return render_cpp_value(expr["value"])
    if op in {"list", "tuple", "set"}:
        values = [render_cpp_expr(item, variables) for item in expr["items"]]
        if op == "tuple":
            return f"std::make_tuple({', '.join(values)})"
        container = "std::set" if op == "set" else "std::vector"
        return f"{container}{{{', '.join(values)}}}"
    if op == "dict":
        entries = [
            "{" + render_cpp_expr(key, variables) + ", " + render_cpp_expr(value, variables) + "}"
            for key, value in expr["entries"]
        ]
        return f"std::map{{{', '.join(entries)}}}"
    if op == "unary":
        operand = render_cpp_expr(expr["operand"], variables)
        if expr["operator"] == "uadd":
            return f"(+({operand}))"
        if expr["operator"] == "usub":
            return f"(-({operand}))"
        if expr["operator"] == "not":
            return f"(!__bcg_truthy({operand}))"
    if op == "binary":
        left = render_cpp_expr(expr["left"], variables)
        right = render_cpp_expr(expr["right"], variables)
        operator = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }.get(expr["operator"])
        if operator is not None:
            return f"(({left}) {operator} ({right}))"
        if expr["operator"] == "pow":
            return f"std::pow(({left}), ({right}))"
    if op == "compare":
        left = render_cpp_expr(expr["left"], variables)
        right = render_cpp_expr(expr["right"], variables)
        operator = expr["operator"]
        if operator == "eq":
            return f"__bcg_deep_equal(({left}), ({right}))"
        if operator == "ne":
            return f"(!__bcg_deep_equal(({left}), ({right})))"
        if operator == "lt":
            return f"(({left}) < ({right}))"
        if operator == "lte":
            return f"(({left}) <= ({right}))"
        if operator == "gt":
            return f"(({left}) > ({right}))"
        if operator == "gte":
            return f"(({left}) >= ({right}))"
        if operator == "in":
            return f"__bcg_contains(({right}), ({left}))"
        if operator == "not_in":
            return f"(!__bcg_contains(({right}), ({left})))"
    if op == "call":
        args = [render_cpp_expr(arg, variables) for arg in expr["args"]]
        name = expr["name"]
        if name == "abs":
            return f"std::abs({args[0]})"
        if name == "bool":
            return f"__bcg_truthy({args[0]})"
        if name == "float":
            return f"static_cast<long double>({args[0]})"
        if name == "int":
            return f"static_cast<long long>({args[0]})"
        if name == "len":
            return f"__bcg_len({args[0]})"
        if name in {"list", "tuple"}:
            return f"__bcg_to_vector({args[0]})"
        if name in {"set", "frozenset"}:
            return f"__bcg_to_set({args[0]})"
        if name == "sorted":
            return f"__bcg_sorted({args[0]})"
        if name == "str":
            return f"__bcg_stringify({args[0]})"
        if name == "sum":
            return f"__bcg_sum({args[0]})"
        if name == "max":
            return f"__bcg_max({', '.join(args)})"
        if name == "min":
            return f"__bcg_min({', '.join(args)})"
    if op == "method":
        receiver = render_cpp_expr(expr["receiver"], variables)
        args = [render_cpp_expr(arg, variables) for arg in expr["args"]]
        joined = ", ".join([receiver] + args)
        return f"__bcg_str_{expr['name']}({joined})"
    if op == "subscript":
        return f"__bcg_subscript({render_cpp_expr(expr['value'], variables)}, {render_cpp_expr(expr['index'], variables)})"
    if op == "slice":
        lower = "std::nullopt" if expr["lower"] is None else render_cpp_expr(expr["lower"], variables)
        upper = "std::nullopt" if expr["upper"] is None else render_cpp_expr(expr["upper"], variables)
        step = "std::nullopt" if expr["step"] is None else render_cpp_expr(expr["step"], variables)
        return f"__bcg_slice({render_cpp_expr(expr['value'], variables)}, {lower}, {upper}, {step})"
    raise DiscoveryError(f"unsupported C++ expression operation: {op}")


def rust_call_arg(name: str, param_type: str | None) -> str:
    stripped = (param_type or "").strip()
    if stripped.startswith("&mut"):
        return f"&mut {name}"
    if stripped.startswith("&"):
        return f"&{name}"
    return name


def render_rust_expr(expr: dict[str, Any], variables: dict[str, str]) -> str:
    op = expr["op"]
    if op == "result":
        return "__bcg_result"
    if op == "var":
        return variables[expr["name"]]
    if op == "value":
        return render_rust_value(expr["value"])
    if op in {"list", "tuple", "set"}:
        values = [render_rust_expr(item, variables) for item in expr["items"]]
        if op == "tuple":
            comma = "," if len(values) == 1 else ""
            return f"({', '.join(values)}{comma})"
        if op == "set":
            return "{ let mut __bcg_set = std::collections::HashSet::new(); " + " ".join(
                f"__bcg_set.insert({value});" for value in values
            ) + " __bcg_set }"
        return f"vec![{', '.join(values)}]"
    if op == "dict":
        lines = ["let mut __bcg_map = std::collections::HashMap::new();"]
        for key, value in expr["entries"]:
            lines.append(f"__bcg_map.insert({render_rust_expr(key, variables)}, {render_rust_expr(value, variables)});")
        lines.append("__bcg_map")
        return "{ " + " ".join(lines) + " }"
    if op == "unary":
        operand = render_rust_expr(expr["operand"], variables)
        if expr["operator"] == "uadd":
            return f"({operand})"
        if expr["operator"] == "usub":
            return f"(-({operand}))"
        if expr["operator"] == "not":
            return f"(!__bcg_truthy(&({operand})))"
    if op == "binary":
        left = render_rust_expr(expr["left"], variables)
        right = render_rust_expr(expr["right"], variables)
        operator = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }.get(expr["operator"])
        if operator is not None:
            return f"(({left}) {operator} ({right}))"
        if expr["operator"] == "pow":
            return f"(({left}).powf(({right}) as f64))"
    if op == "compare":
        left = render_rust_expr(expr["left"], variables)
        right = render_rust_expr(expr["right"], variables)
        operator = expr["operator"]
        if operator == "eq":
            return f"__bcg_deep_equal(&({left}), &({right}))"
        if operator == "ne":
            return f"(!__bcg_deep_equal(&({left}), &({right})))"
        if operator == "lt":
            return f"(({left}) < ({right}))"
        if operator == "lte":
            return f"(({left}) <= ({right}))"
        if operator == "gt":
            return f"(({left}) > ({right}))"
        if operator == "gte":
            return f"(({left}) >= ({right}))"
        if operator == "in":
            return f"__bcg_contains(&({right}), &({left}))"
        if operator == "not_in":
            return f"(!__bcg_contains(&({right}), &({left})))"
    if op == "call":
        args = [render_rust_expr(arg, variables) for arg in expr["args"]]
        name = expr["name"]
        if name == "abs":
            return f"({args[0]}).abs()"
        if name == "bool":
            return f"__bcg_truthy(&({args[0]}))"
        if name == "float":
            return f"(({args[0]}) as f64)"
        if name == "int":
            return f"(({args[0]}) as i64)"
        if name == "len":
            return f"__bcg_len(&({args[0]}))"
        if name in {"list", "tuple"}:
            return f"__bcg_to_vec(&({args[0]}))"
        if name in {"set", "frozenset"}:
            return f"__bcg_to_set(&({args[0]}))"
        if name == "sorted":
            return f"__bcg_sorted(&({args[0]}))"
        if name == "str":
            return f"format!(\"{{}}\", ({args[0]}))"
        if name == "sum":
            return f"__bcg_sum(&({args[0]}))"
        if name == "max":
            return f"__bcg_max(vec![{', '.join(args)}])"
        if name == "min":
            return f"__bcg_min(vec![{', '.join(args)}])"
    if op == "method":
        receiver = render_rust_expr(expr["receiver"], variables)
        args = [render_rust_expr(arg, variables) for arg in expr["args"]]
        joined = ", ".join([f"&({receiver})"] + args)
        return f"__bcg_str_{expr['name']}({joined})"
    if op == "subscript":
        return f"__bcg_subscript(&({render_rust_expr(expr['value'], variables)}), &({render_rust_expr(expr['index'], variables)}))"
    if op == "slice":
        lower = "None" if expr["lower"] is None else f"Some({render_rust_expr(expr['lower'], variables)} as isize)"
        upper = "None" if expr["upper"] is None else f"Some({render_rust_expr(expr['upper'], variables)} as isize)"
        step = "None" if expr["step"] is None else f"Some({render_rust_expr(expr['step'], variables)} as isize)"
        return f"__bcg_slice(&({render_rust_expr(expr['value'], variables)}), {lower}, {upper}, {step})"
    raise DiscoveryError(f"unsupported Rust expression operation: {op}")


CPP_HARNESS_HELPERS = r'''
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <deque>
#include <future>
#include <iomanip>
#include <iostream>
#include <list>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace std;

template <typename T>
static decltype(auto) __bcg_complete(T&& value) {
    return std::forward<T>(value);
}

template <typename T>
static T __bcg_complete(std::future<T> value) {
    return value.get();
}

static void __bcg_complete(std::future<void> value) {
    value.get();
}

template <typename T>
static T __bcg_complete(std::shared_future<T> value) {
    return value.get();
}

static void __bcg_complete(std::shared_future<void> value) {
    value.get();
}

template <typename F>
static void __bcg_complete_statement(F&& function) {
    using Return = decltype(function());
    if constexpr (std::is_void<Return>::value) {
        function();
    } else {
        __bcg_complete(function());
    }
}

static string __bcg_json_string(const string& value) {
    ostringstream out;
    out << '"';
    for (unsigned char ch : value) {
        switch (ch) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (ch < 0x20) {
                    out << "\\u" << hex << setw(4) << setfill('0') << static_cast<int>(ch) << dec << setfill(' ');
                } else {
                    out << ch;
                }
        }
    }
    out << '"';
    return out.str();
}

static string __bcg_number(long double value) {
    if (!isfinite(static_cast<double>(value))) {
        return "null";
    }
    ostringstream out;
    out << setprecision(21) << value;
    return out.str();
}

static string __bcg_to_json(const bool& value) {
    return string("{\"type\":\"scalar\",\"value\":") + (value ? "true" : "false") + "}";
}

template <typename T, typename enable_if<is_integral<T>::value && !is_same<T, bool>::value, int>::type = 0>
static string __bcg_to_json(const T& value) {
    return string("{\"type\":\"scalar\",\"value\":") + to_string(static_cast<long long>(value)) + "}";
}

template <typename T, typename enable_if<is_floating_point<T>::value, int>::type = 0>
static string __bcg_to_json(const T& value) {
    return string("{\"type\":\"scalar\",\"value\":") + __bcg_number(static_cast<long double>(value)) + "}";
}

static string __bcg_to_json(const string& value) {
    return string("{\"type\":\"scalar\",\"value\":") + __bcg_json_string(value) + "}";
}

static string __bcg_to_json(const char* value) {
    return __bcg_to_json(string(value));
}

static string __bcg_to_json(nullopt_t) {
    return "{\"type\":\"scalar\",\"value\":null}";
}

template <typename T>
static string __bcg_to_json(const optional<T>& value) {
    if (!value.has_value()) {
        return __bcg_to_json(nullopt);
    }
    return __bcg_to_json(*value);
}

template <typename T>
static string __bcg_json_items(const T& values, const string& type_name) {
    string out = "{\"type\":\"" + type_name + "\",\"items\":[";
    bool first = true;
    for (const auto& item : values) {
        if (!first) out += ",";
        first = false;
        out += __bcg_to_json(item);
    }
    out += "]}";
    return out;
}

template <typename T>
static string __bcg_to_json(const vector<T>& values) {
    return __bcg_json_items(values, "list");
}

template <typename T>
static string __bcg_to_json(const deque<T>& values) {
    return __bcg_json_items(values, "deque");
}

template <typename T>
static string __bcg_to_json(const set<T>& values) {
    return __bcg_json_items(values, "set");
}

template <typename T>
static string __bcg_to_json(const unordered_set<T>& values) {
    return __bcg_json_items(values, "set");
}

template <typename K, typename V>
static string __bcg_json_map_entries(const K& values, const string& type_name) {
    string out = "{\"type\":\"" + type_name + "\",\"entries\":[";
    bool first = true;
    for (const auto& item : values) {
        if (!first) out += ",";
        first = false;
        out += "[" + __bcg_to_json(item.first) + "," + __bcg_to_json(item.second) + "]";
    }
    out += "]}";
    return out;
}

template <typename K, typename V>
static string __bcg_to_json(const map<K, V>& values) {
    return __bcg_json_map_entries<map<K, V>, V>(values, "dict");
}

template <typename K, typename V>
static string __bcg_to_json(const unordered_map<K, V>& values) {
    return __bcg_json_map_entries<unordered_map<K, V>, V>(values, "dict");
}

template <class Tuple, size_t... Indexes>
static string __bcg_tuple_json_impl(const Tuple& values, index_sequence<Indexes...>) {
    vector<string> items = {__bcg_to_json(get<Indexes>(values))...};
    string out = "{\"type\":\"tuple\",\"items\":[";
    for (size_t index = 0; index < items.size(); ++index) {
        if (index) out += ",";
        out += items[index];
    }
    out += "]}";
    return out;
}

template <typename... Ts>
static string __bcg_to_json(const tuple<Ts...>& values) {
    return __bcg_tuple_json_impl(values, index_sequence_for<Ts...>{});
}

template <typename L, typename R>
static bool __bcg_deep_equal(const L& left, const R& right) {
    return __bcg_to_json(left) == __bcg_to_json(right);
}

template <typename T>
static bool __bcg_truthy(const T& value) {
    return static_cast<bool>(value);
}

static bool __bcg_truthy(const string& value) { return !value.empty(); }
template <typename T> static bool __bcg_truthy(const vector<T>& value) { return !value.empty(); }
template <typename T> static bool __bcg_truthy(const deque<T>& value) { return !value.empty(); }
template <typename T> static bool __bcg_truthy(const set<T>& value) { return !value.empty(); }
template <typename K, typename V> static bool __bcg_truthy(const map<K, V>& value) { return !value.empty(); }
template <typename T> static bool __bcg_truthy(const optional<T>& value) { return value.has_value() && __bcg_truthy(*value); }

template <typename T>
static auto __bcg_len(const T& value) -> decltype(value.size()) { return value.size(); }

template <typename T>
static vector<T> __bcg_to_vector(const vector<T>& value) { return value; }
template <typename T>
static vector<T> __bcg_to_vector(const set<T>& value) { return vector<T>(value.begin(), value.end()); }
static vector<char> __bcg_to_vector(const string& value) { return vector<char>(value.begin(), value.end()); }

template <typename T>
static set<T> __bcg_to_set(const vector<T>& value) { return set<T>(value.begin(), value.end()); }
template <typename T>
static set<T> __bcg_to_set(const set<T>& value) { return value; }

template <typename T>
static vector<T> __bcg_sorted(const vector<T>& value) {
    vector<T> copy = value;
    sort(copy.begin(), copy.end());
    return copy;
}

template <typename T>
static vector<T> __bcg_sorted(const set<T>& value) {
    return vector<T>(value.begin(), value.end());
}

template <typename T>
static auto __bcg_sum(const T& value) {
    typename T::value_type total{};
    for (const auto& item : value) total += item;
    return total;
}

template <typename T>
static T __bcg_max(const vector<T>& value) { return *max_element(value.begin(), value.end()); }
template <typename T, typename... Rest>
static T __bcg_max(const T& first, const Rest&... rest) { return max(first, __bcg_max(vector<T>{rest...})); }
template <typename T>
static T __bcg_min(const vector<T>& value) { return *min_element(value.begin(), value.end()); }
template <typename T, typename... Rest>
static T __bcg_min(const T& first, const Rest&... rest) { return min(first, __bcg_min(vector<T>{rest...})); }

template <typename T, typename U>
static bool __bcg_contains(const vector<T>& values, const U& item) {
    return any_of(values.begin(), values.end(), [&](const T& value) { return __bcg_deep_equal(value, item); });
}
template <typename T, typename U>
static bool __bcg_contains(const set<T>& values, const U& item) {
    return any_of(values.begin(), values.end(), [&](const T& value) { return __bcg_deep_equal(value, item); });
}
static bool __bcg_contains(const string& value, const string& item) { return value.find(item) != string::npos; }
template <typename K, typename V, typename U>
static bool __bcg_contains(const map<K, V>& values, const U& item) {
    return any_of(values.begin(), values.end(), [&](const auto& entry) { return __bcg_deep_equal(entry.first, item); });
}

template <typename T>
static auto __bcg_subscript(const vector<T>& value, long long index) {
    long long resolved = index < 0 ? static_cast<long long>(value.size()) + index : index;
    return value.at(static_cast<size_t>(resolved));
}
static string __bcg_subscript(const string& value, long long index) {
    long long resolved = index < 0 ? static_cast<long long>(value.size()) + index : index;
    return string(1, value.at(static_cast<size_t>(resolved)));
}
template <typename K, typename V>
static V __bcg_subscript(const map<K, V>& value, const K& key) { return value.at(key); }

template <typename T>
static vector<T> __bcg_slice(const vector<T>& value, optional<long long> lower, optional<long long> upper, optional<long long> step) {
    long long actual_step = step.value_or(1);
    vector<T> result;
    if (actual_step == 0) return result;
    long long size = static_cast<long long>(value.size());
    long long start = lower.value_or(actual_step > 0 ? 0 : size - 1);
    long long stop = upper.value_or(actual_step > 0 ? size : -1);
    if (start < 0) start += size;
    if (stop < 0 && upper.has_value()) stop += size;
    if (actual_step > 0) {
        for (long long i = start; i < stop && i < size; i += actual_step) result.push_back(value.at(static_cast<size_t>(i)));
    } else {
        for (long long i = start; i > stop && i >= 0; i += actual_step) result.push_back(value.at(static_cast<size_t>(i)));
    }
    return result;
}

static string __bcg_slice(const string& value, optional<long long> lower, optional<long long> upper, optional<long long> step) {
    vector<char> chars(value.begin(), value.end());
    auto sliced = __bcg_slice(chars, lower, upper, step);
    return string(sliced.begin(), sliced.end());
}

template <typename T>
static string __bcg_stringify(const T& value) {
    ostringstream out;
    out << value;
    return out.str();
}

static string __bcg_str_upper(string value) {
    transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(toupper(c)); });
    return value;
}
static string __bcg_str_lower(string value) {
    transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(tolower(c)); });
    return value;
}
static bool __bcg_str_startswith(const string& value, const string& needle) { return value.rfind(needle, 0) == 0; }
static bool __bcg_str_endswith(const string& value, const string& needle) {
    return value.size() >= needle.size() && value.compare(value.size() - needle.size(), needle.size(), needle) == 0;
}
static long long __bcg_str_find(const string& value, const string& needle) {
    auto found = value.find(needle);
    return found == string::npos ? -1 : static_cast<long long>(found);
}
static vector<string> __bcg_str_split(const string& value, const string& sep) {
    vector<string> result;
    size_t start = 0;
    while (true) {
        size_t pos = value.find(sep, start);
        if (pos == string::npos) {
            result.push_back(value.substr(start));
            return result;
        }
        result.push_back(value.substr(start, pos - start));
        start = pos + sep.size();
    }
}
static string __bcg_str_join(const string& sep, const vector<string>& values) {
    string out;
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) out += sep;
        out += values[i];
    }
    return out;
}
static long long __bcg_str_count(const string& value, const string& needle) {
    if (needle.empty()) return static_cast<long long>(value.size()) + 1;
    long long count = 0;
    size_t start = 0;
    while ((start = value.find(needle, start)) != string::npos) {
        ++count;
        start += needle.size();
    }
    return count;
}
static string __bcg_str_replace(string value, const string& old_value, const string& new_value) {
    size_t start = 0;
    while ((start = value.find(old_value, start)) != string::npos) {
        value.replace(start, old_value.size(), new_value);
        start += new_value.size();
    }
    return value;
}
static string __bcg_trim_chars(string value, const string& chars, bool left, bool right) {
    if (left) value.erase(value.begin(), find_if(value.begin(), value.end(), [&](char c) { return chars.find(c) == string::npos; }));
    if (right) value.erase(find_if(value.rbegin(), value.rend(), [&](char c) { return chars.find(c) == string::npos; }).base(), value.end());
    return value;
}
static string __bcg_str_strip(const string& value) { return __bcg_trim_chars(value, " \t\n\r\f\v", true, true); }
static string __bcg_str_strip(const string& value, const string& chars) { return __bcg_trim_chars(value, chars, true, true); }
static string __bcg_str_lstrip(const string& value) { return __bcg_trim_chars(value, " \t\n\r\f\v", true, false); }
static string __bcg_str_lstrip(const string& value, const string& chars) { return __bcg_trim_chars(value, chars, true, false); }
static string __bcg_str_rstrip(const string& value) { return __bcg_trim_chars(value, " \t\n\r\f\v", false, true); }
static string __bcg_str_rstrip(const string& value, const string& chars) { return __bcg_trim_chars(value, chars, false, true); }
'''


RUST_HARNESS_HELPERS = r'''
#![allow(dead_code)]
#![allow(unused_imports)]
use std::any::Any;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fmt::Display;
use std::future::Future;
use std::hash::Hash;
use std::io::Write;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};
use std::thread;

fn __bcg_json_string(value: &str) -> String {
    let mut out = String::from("\"");
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if c < '\u{20}' => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

trait BcgToJson {
    fn __bcg_to_json(&self) -> String;
}

trait BcgTruthy {
    fn __bcg_truthy(&self) -> bool;
}

impl<T: BcgToJson + ?Sized> BcgToJson for &T {
    fn __bcg_to_json(&self) -> String { (*self).__bcg_to_json() }
}

impl<T: BcgTruthy + ?Sized> BcgTruthy for &T {
    fn __bcg_truthy(&self) -> bool { (*self).__bcg_truthy() }
}

impl BcgToJson for bool {
    fn __bcg_to_json(&self) -> String {
        format!("{{\"type\":\"scalar\",\"value\":{}}}", if *self { "true" } else { "false" })
    }
}
impl BcgTruthy for bool { fn __bcg_truthy(&self) -> bool { *self } }

macro_rules! impl_bcg_int {
    ($($t:ty),*) => {$(
        impl BcgToJson for $t {
            fn __bcg_to_json(&self) -> String { format!("{{\"type\":\"scalar\",\"value\":{}}}", *self) }
        }
        impl BcgTruthy for $t { fn __bcg_truthy(&self) -> bool { *self != 0 } }
    )*};
}
impl_bcg_int!(i8, i16, i32, i64, i128, isize, u8, u16, u32, u64, u128, usize);

macro_rules! impl_bcg_float {
    ($($t:ty),*) => {$(
        impl BcgToJson for $t {
            fn __bcg_to_json(&self) -> String {
                if self.is_finite() {
                    format!("{{\"type\":\"scalar\",\"value\":{}}}", *self)
                } else {
                    String::from("{\"type\":\"scalar\",\"value\":null}")
                }
            }
        }
        impl BcgTruthy for $t { fn __bcg_truthy(&self) -> bool { *self != 0.0 && !self.is_nan() } }
    )*};
}
impl_bcg_float!(f32, f64);

impl BcgToJson for String {
    fn __bcg_to_json(&self) -> String { format!("{{\"type\":\"scalar\",\"value\":{}}}", __bcg_json_string(self)) }
}
impl BcgTruthy for String { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }
impl BcgToJson for str {
    fn __bcg_to_json(&self) -> String { format!("{{\"type\":\"scalar\",\"value\":{}}}", __bcg_json_string(self)) }
}
impl BcgTruthy for str { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

impl<T: BcgToJson> BcgToJson for Option<T> {
    fn __bcg_to_json(&self) -> String {
        match self {
            Some(value) => value.__bcg_to_json(),
            None => String::from("{\"type\":\"scalar\",\"value\":null}"),
        }
    }
}
impl<T: BcgTruthy> BcgTruthy for Option<T> {
    fn __bcg_truthy(&self) -> bool { self.as_ref().map(|value| value.__bcg_truthy()).unwrap_or(false) }
}

fn __bcg_json_items<T: BcgToJson>(values: impl Iterator<Item = T>, type_name: &str) -> String {
    let mut out = format!("{{\"type\":\"{}\",\"items\":[", type_name);
    let mut first = true;
    for item in values {
        if !first { out.push(','); }
        first = false;
        out.push_str(&item.__bcg_to_json());
    }
    out.push_str("]}");
    out
}

impl<T: BcgToJson + Clone> BcgToJson for Vec<T> {
    fn __bcg_to_json(&self) -> String { __bcg_json_items(self.iter().cloned(), "list") }
}
impl<T> BcgTruthy for Vec<T> { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

impl<T: BcgToJson + Clone + Eq + Hash> BcgToJson for HashSet<T> {
    fn __bcg_to_json(&self) -> String { __bcg_json_items(self.iter().cloned(), "set") }
}
impl<T> BcgTruthy for HashSet<T> { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

impl<T: BcgToJson + Clone + Ord> BcgToJson for BTreeSet<T> {
    fn __bcg_to_json(&self) -> String { __bcg_json_items(self.iter().cloned(), "set") }
}
impl<T> BcgTruthy for BTreeSet<T> { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

impl<K: BcgToJson + Eq + Hash, V: BcgToJson> BcgToJson for HashMap<K, V> {
    fn __bcg_to_json(&self) -> String {
        let mut out = String::from("{\"type\":\"dict\",\"entries\":[");
        let mut first = true;
        for (key, value) in self.iter() {
            if !first { out.push(','); }
            first = false;
            out.push('[');
            out.push_str(&key.__bcg_to_json());
            out.push(',');
            out.push_str(&value.__bcg_to_json());
            out.push(']');
        }
        out.push_str("]}");
        out
    }
}
impl<K, V> BcgTruthy for HashMap<K, V> { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

impl<K: BcgToJson + Ord, V: BcgToJson> BcgToJson for BTreeMap<K, V> {
    fn __bcg_to_json(&self) -> String {
        let mut out = String::from("{\"type\":\"dict\",\"entries\":[");
        let mut first = true;
        for (key, value) in self.iter() {
            if !first { out.push(','); }
            first = false;
            out.push('[');
            out.push_str(&key.__bcg_to_json());
            out.push(',');
            out.push_str(&value.__bcg_to_json());
            out.push(']');
        }
        out.push_str("]}");
        out
    }
}
impl<K, V> BcgTruthy for BTreeMap<K, V> { fn __bcg_truthy(&self) -> bool { !self.is_empty() } }

macro_rules! impl_tuple_json {
    ($($name:ident),+) => {
        impl<$($name: BcgToJson),+> BcgToJson for ($($name,)+) {
            #[allow(non_snake_case)]
            fn __bcg_to_json(&self) -> String {
                let ($($name,)+) = self;
                let items = vec![$($name.__bcg_to_json()),+];
                format!("{{\"type\":\"tuple\",\"items\":[{}]}}", items.join(","))
            }
        }
        impl<$($name),+> BcgTruthy for ($($name,)+) {
            fn __bcg_truthy(&self) -> bool { true }
        }
    };
}
impl_tuple_json!(A);
impl_tuple_json!(A, B);
impl_tuple_json!(A, B, C);
impl_tuple_json!(A, B, C, D);

fn __bcg_raw_waker() -> RawWaker {
    unsafe fn clone(_: *const ()) -> RawWaker { __bcg_raw_waker() }
    unsafe fn wake(_: *const ()) {}
    unsafe fn wake_by_ref(_: *const ()) {}
    unsafe fn drop(_: *const ()) {}
    static VTABLE: RawWakerVTable = RawWakerVTable::new(clone, wake, wake_by_ref, drop);
    RawWaker::new(std::ptr::null(), &VTABLE)
}

fn __bcg_block_on<F: Future>(mut future: F) -> F::Output {
    let waker = unsafe { Waker::from_raw(__bcg_raw_waker()) };
    let mut context = Context::from_waker(&waker);
    let mut pinned = unsafe { Pin::new_unchecked(&mut future) };
    loop {
        match pinned.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => thread::yield_now(),
        }
    }
}

fn __bcg_to_json<T: BcgToJson + ?Sized>(value: &T) -> String { value.__bcg_to_json() }
fn __bcg_truthy<T: BcgTruthy + ?Sized>(value: &T) -> bool { value.__bcg_truthy() }
fn __bcg_deep_equal<L: BcgToJson + ?Sized, R: BcgToJson + ?Sized>(left: &L, right: &R) -> bool {
    left.__bcg_to_json() == right.__bcg_to_json()
}

trait BcgLen { fn __bcg_len(&self) -> usize; }
impl<T> BcgLen for Vec<T> { fn __bcg_len(&self) -> usize { self.len() } }
impl<T> BcgLen for HashSet<T> { fn __bcg_len(&self) -> usize { self.len() } }
impl<K, V> BcgLen for HashMap<K, V> { fn __bcg_len(&self) -> usize { self.len() } }
impl BcgLen for String { fn __bcg_len(&self) -> usize { self.len() } }
impl BcgLen for str { fn __bcg_len(&self) -> usize { self.len() } }
fn __bcg_len<T: BcgLen + ?Sized>(value: &T) -> usize { value.__bcg_len() }

fn __bcg_contains<C: BcgToJson + ?Sized, I: BcgToJson + ?Sized>(container: &C, item: &I) -> bool {
    container.__bcg_to_json().contains(&item.__bcg_to_json())
}
fn __bcg_to_vec<T: Clone>(value: &Vec<T>) -> Vec<T> { value.clone() }
fn __bcg_to_set<T: Clone + Eq + Hash>(value: &Vec<T>) -> HashSet<T> { value.iter().cloned().collect() }
fn __bcg_sorted<T: Clone + Ord>(value: &Vec<T>) -> Vec<T> {
    let mut copy = value.clone();
    copy.sort();
    copy
}
fn __bcg_sum<T>(value: &Vec<T>) -> T where T: Copy + Default + std::ops::Add<Output = T> {
    value.iter().copied().fold(T::default(), |total, item| total + item)
}
fn __bcg_max<T: Ord + Clone>(values: Vec<T>) -> T { values.into_iter().max().unwrap() }
fn __bcg_min<T: Ord + Clone>(values: Vec<T>) -> T { values.into_iter().min().unwrap() }
fn __bcg_subscript<T: Clone>(value: &Vec<T>, index: &isize) -> T {
    let len = value.len() as isize;
    let resolved = if *index < 0 { len + *index } else { *index };
    value[resolved as usize].clone()
}
fn __bcg_slice<T: Clone>(value: &Vec<T>, lower: Option<isize>, upper: Option<isize>, step: Option<isize>) -> Vec<T> {
    let step = step.unwrap_or(1);
    if step == 0 { return vec![]; }
    let len = value.len() as isize;
    let mut index = lower.unwrap_or(if step > 0 { 0 } else { len - 1 });
    if index < 0 { index += len; }
    let mut stop = upper.unwrap_or(if step > 0 { len } else { -1 });
    if upper.is_some() && stop < 0 { stop += len; }
    let mut result = Vec::new();
    if step > 0 {
        while index < stop && index < len {
            result.push(value[index as usize].clone());
            index += step;
        }
    } else {
        while index > stop && index >= 0 {
            result.push(value[index as usize].clone());
            index += step;
        }
    }
    result
}
fn __bcg_str_upper(value: &String) -> String { value.to_uppercase() }
fn __bcg_str_lower(value: &String) -> String { value.to_lowercase() }
fn __bcg_str_strip(value: &String) -> String { value.trim().to_string() }
fn __bcg_str_lstrip(value: &String) -> String { value.trim_start().to_string() }
fn __bcg_str_rstrip(value: &String) -> String { value.trim_end().to_string() }
fn __bcg_str_startswith(value: &String, needle: String) -> bool { value.starts_with(&needle) }
fn __bcg_str_endswith(value: &String, needle: String) -> bool { value.ends_with(&needle) }
fn __bcg_str_find(value: &String, needle: String) -> isize { value.find(&needle).map(|i| i as isize).unwrap_or(-1) }
fn __bcg_str_split(value: &String, sep: String) -> Vec<String> { value.split(&sep).map(|s| s.to_string()).collect() }
fn __bcg_str_count(value: &String, needle: String) -> usize { value.matches(&needle).count() }
fn __bcg_str_replace(value: &String, old_value: String, new_value: String) -> String { value.replace(&old_value, &new_value) }

#[cfg(unix)]
mod __bcg_capture {
    use super::*;
    type CInt = i32;
    unsafe extern "C" {
        fn pipe(fds: *mut CInt) -> CInt;
        fn dup(fd: CInt) -> CInt;
        fn dup2(fd: CInt, fd2: CInt) -> CInt;
        fn close(fd: CInt) -> CInt;
        fn read(fd: CInt, buf: *mut u8, count: usize) -> isize;
    }
    unsafe fn read_fd(fd: CInt) -> String {
        let mut bytes = Vec::new();
        let mut buf = [0u8; 4096];
        loop {
            let n = read(fd, buf.as_mut_ptr(), buf.len());
            if n <= 0 { break; }
            bytes.extend_from_slice(&buf[..n as usize]);
        }
        String::from_utf8_lossy(&bytes).into_owned()
    }
    pub fn run<F: FnOnce() -> String>(f: F) -> (Result<String, Box<dyn Any + Send>>, String, String) {
        unsafe {
            let mut out_pipe = [0 as CInt; 2];
            let mut err_pipe = [0 as CInt; 2];
            if pipe(out_pipe.as_mut_ptr()) != 0 || pipe(err_pipe.as_mut_ptr()) != 0 {
                return (catch_unwind(AssertUnwindSafe(f)), String::new(), String::new());
            }
            let old_out = dup(1);
            let old_err = dup(2);
            dup2(out_pipe[1], 1);
            dup2(err_pipe[1], 2);
            let result = catch_unwind(AssertUnwindSafe(f));
            let _ = std::io::stdout().flush();
            let _ = std::io::stderr().flush();
            dup2(old_out, 1);
            dup2(old_err, 2);
            close(old_out);
            close(old_err);
            close(out_pipe[1]);
            close(err_pipe[1]);
            let stdout = read_fd(out_pipe[0]);
            let stderr = read_fd(err_pipe[0]);
            close(out_pipe[0]);
            close(err_pipe[0]);
            (result, stdout, stderr)
        }
    }
}

#[cfg(not(unix))]
mod __bcg_capture {
    use super::*;
    pub fn run<F: FnOnce() -> String>(f: F) -> (Result<String, Box<dyn Any + Send>>, String, String) {
        (catch_unwind(AssertUnwindSafe(f)), String::new(), String::new())
    }
}

fn __bcg_panic_message(error: &(dyn Any + Send)) -> String {
    if let Some(value) = error.downcast_ref::<&str>() { return value.to_string(); }
    if let Some(value) = error.downcast_ref::<String>() { return value.clone(); }
    String::new()
}
'''


def run_python_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    payload = {
        "solution_path": str(solution_path),
        "entrypoint": entrypoint,
        "case": case_to_json(case, default_abs_tol),
    }
    harness = PYTHON_CASE_RUNNER + "\nPAYLOAD = " + repr(payload) + "\nrun(PAYLOAD)\n"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", harness],
            text=True,
            capture_output=True,
            timeout=timeout_seconds or DEFAULT_CASE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(proc)


PYTHON_CASE_RUNNER = r'''
import asyncio
import builtins
import inspect
import io
import json
import math
import re
import runpy
from collections import Counter, defaultdict, deque
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal


def _resolve_callable(namespace, entrypoint):
    direct = namespace.get(entrypoint)
    if callable(direct) and not isinstance(direct, type):
        return direct

    module_name = namespace.get("__name__")
    for value in namespace.values():
        if not isinstance(value, type):
            continue
        if module_name is not None and getattr(value, "__module__", None) != module_name:
            continue
        try:
            raw = inspect.getattr_static(value, entrypoint)
        except AttributeError:
            continue
        if isinstance(raw, (staticmethod, classmethod)):
            candidate = getattr(value, entrypoint)
            if callable(candidate):
                return candidate
        try:
            instance = value()
        except Exception:
            continue
        candidate = getattr(instance, entrypoint, None)
        if callable(candidate):
            return candidate
    raise LookupError("entrypoint not found")


def _complete_awaitable(value):
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _decode_value(tag):
    if tag is None:
        return None
    kind = tag["type"]
    if kind == "scalar":
        return tag["value"]
    if kind == "decimal":
        return Decimal(tag["value"])
    if kind == "list":
        return [_decode_value(item) for item in tag["items"]]
    if kind == "tuple":
        return tuple(_decode_value(item) for item in tag["items"])
    if kind == "dict":
        return {_decode_value(key): _decode_value(value) for key, value in tag["entries"]}
    if kind == "defaultdict":
        return defaultdict(_defaultdict_factory(tag.get("factory")), {_decode_value(key): _decode_value(value) for key, value in tag["entries"]})
    if kind == "counter":
        return Counter({_decode_value(key): _decode_value(value) for key, value in tag["entries"]})
    if kind == "deque":
        return deque(_decode_value(item) for item in tag["items"])
    if kind == "set":
        return set(_decode_value(item) for item in tag["items"])
    if kind == "frozenset":
        return frozenset(_decode_value(item) for item in tag["items"])
    raise ValueError("unsupported value tag")


def _decode_expr(expr):
    op = expr["op"]
    if op == "value":
        return {"op": "value", "value": _decode_value(expr["value"])}
    if op == "var":
        return {"op": "var", "name": expr["name"]}
    if op == "result":
        return {"op": "result"}
    if op in {"list", "tuple", "set"}:
        return {"op": op, "items": [_decode_expr(item) for item in expr["items"]]}
    if op == "dict":
        return {"op": "dict", "entries": [[_decode_expr(key), _decode_expr(value)] for key, value in expr["entries"]]}
    if op == "unary":
        return {"op": "unary", "operator": expr["operator"], "operand": _decode_expr(expr["operand"])}
    if op in {"binary", "compare"}:
        return {"op": op, "operator": expr["operator"], "left": _decode_expr(expr["left"]), "right": _decode_expr(expr["right"])}
    if op == "call":
        return {"op": "call", "name": expr["name"], "args": [_decode_expr(arg) for arg in expr["args"]]}
    if op == "method":
        return {
            "op": "method",
            "name": expr["name"],
            "receiver": _decode_expr(expr["receiver"]),
            "args": [_decode_expr(arg) for arg in expr["args"]],
        }
    if op == "subscript":
        return {"op": "subscript", "value": _decode_expr(expr["value"]), "index": _decode_expr(expr["index"])}
    if op == "slice":
        return {
            "op": "slice",
            "value": _decode_expr(expr["value"]),
            "lower": _decode_expr(expr["lower"]) if expr["lower"] is not None else None,
            "upper": _decode_expr(expr["upper"]) if expr["upper"] is not None else None,
            "step": _decode_expr(expr["step"]) if expr["step"] is not None else None,
        }
    raise ValueError("unsupported expression operation")


def _defaultdict_factory(name):
    if name is None:
        return None
    return {
        "bool": bool,
        "dict": dict,
        "float": float,
        "int": int,
        "list": list,
        "set": set,
        "str": str,
        "tuple": tuple,
    }.get(name)


def _decode_case(case):
    decoded = dict(case)
    decoded["args"] = [_decode_value(item) for item in case["args"]]
    decoded["actual_expr"] = _decode_expr(case.get("actual_expr") or {"op": "result"})
    decoded["expected"] = _decode_value(case["expected"])
    decoded["abs_tol"] = _decode_value(case["abs_tol"])
    decoded["rel_tol"] = _decode_value(case["rel_tol"])
    decoded["default_abs_tol"] = _decode_value(case["default_abs_tol"])
    decoded["mutation_arg_names"] = dict(case.get("mutation_arg_names") or {})
    return decoded


def _is_numeric(value):
    return not isinstance(value, bool) and isinstance(value, (int, float, Decimal))


def _uses_tolerance(left, right):
    return _is_numeric(left) and _is_numeric(right) and (
        isinstance(left, (float, Decimal)) or isinstance(right, (float, Decimal))
    )


def _to_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _numeric_close(left, right, abs_tol=None, rel_tol=None):
    if not _is_numeric(left) or not _is_numeric(right):
        return False
    abs_tol = 0 if abs_tol is None else abs_tol
    rel_tol = 0 if rel_tol is None else rel_tol
    if any(isinstance(value, Decimal) for value in (left, right, abs_tol, rel_tol)):
        left_d = _to_decimal(left)
        right_d = _to_decimal(right)
        abs_d = _to_decimal(abs_tol)
        rel_d = _to_decimal(rel_tol)
        diff = abs(left_d - right_d)
        limit = max(abs_d, rel_d * max(abs(left_d), abs(right_d)))
        return diff <= limit
    return math.isclose(float(left), float(right), abs_tol=float(abs_tol), rel_tol=float(rel_tol))


def _sequence_equal(left, right, abs_tol=None, rel_tol=None):
    if type(left) is not type(right) or len(left) != len(right):
        return False
    return all(_deep_equal(item, right[index], abs_tol, rel_tol) for index, item in enumerate(left))


def _unordered_equal(left_items, right_items, abs_tol=None, rel_tol=None):
    unmatched = list(right_items)
    for left_item in left_items:
        for index, right_item in enumerate(unmatched):
            if _deep_equal(left_item, right_item, abs_tol, rel_tol):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def _mapping_entries(mapping):
    return list(mapping.items())


def _mapping_equal(left, right, abs_tol=None, rel_tol=None):
    left_entries = _mapping_entries(left)
    right_entries = _mapping_entries(right)
    if len(left_entries) != len(right_entries):
        return False
    unmatched = list(right_entries)
    for left_key, left_value in left_entries:
        for index, (right_key, right_value) in enumerate(unmatched):
            if _deep_equal(left_key, right_key, abs_tol, rel_tol) and _deep_equal(left_value, right_value, abs_tol, rel_tol):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def _deep_equal(left, right, abs_tol=None, rel_tol=None):
    if _uses_tolerance(left, right) and (abs_tol is not None or rel_tol is not None):
        return _numeric_close(left, right, abs_tol, rel_tol)
    if _is_numeric(left) and _is_numeric(right):
        return left == right
    if isinstance(left, (dict, defaultdict, Counter)) or isinstance(right, (dict, defaultdict, Counter)):
        if not isinstance(left, (dict, defaultdict, Counter)) or not isinstance(right, (dict, defaultdict, Counter)):
            return False
        return _mapping_equal(left, right, abs_tol, rel_tol)
    if isinstance(left, (list, tuple, deque)) or isinstance(right, (list, tuple, deque)):
        if not isinstance(left, (list, tuple, deque)) or not isinstance(right, (list, tuple, deque)):
            return False
        return _sequence_equal(left, right, abs_tol, rel_tol)
    if isinstance(left, (set, frozenset)) or isinstance(right, (set, frozenset)):
        if not isinstance(left, (set, frozenset)) or not isinstance(right, (set, frozenset)):
            return False
        if len(left) != len(right):
            return False
        return _unordered_equal(left, right, abs_tol, rel_tol)
    return left == right


def _contains(container, item):
    try:
        return item in container
    except Exception:
        return False


def _eval_call(name, args):
    if name == "abs":
        return abs(args[0])
    if name == "bool":
        return bool(args[0])
    if name == "float":
        return float(args[0])
    if name == "frozenset":
        return frozenset(args[0])
    if name == "int":
        return int(args[0])
    if name == "len":
        return len(args[0])
    if name == "list":
        return list(args[0])
    if name == "max":
        return max(*args) if len(args) > 1 else max(args[0])
    if name == "min":
        return min(*args) if len(args) > 1 else min(args[0])
    if name == "set":
        return set(args[0])
    if name == "sorted":
        return sorted(args[0])
    if name == "str":
        return str(args[0])
    if name == "sum":
        return sum(args[0])
    if name == "tuple":
        return tuple(args[0])
    raise ValueError("unsupported primitive call")


def _eval_method(name, receiver, args):
    if not isinstance(receiver, str):
        raise ValueError("string method receiver must be a string")
    if name == "upper":
        return receiver.upper()
    if name == "lower":
        return receiver.lower()
    if name == "strip":
        return receiver.strip(*args)
    if name == "lstrip":
        return receiver.lstrip(*args)
    if name == "rstrip":
        return receiver.rstrip(*args)
    if name == "startswith":
        return receiver.startswith(args[0])
    if name == "endswith":
        return receiver.endswith(args[0])
    if name == "replace":
        return receiver.replace(args[0], args[1])
    if name == "split":
        return receiver.split(*args)
    if name == "join":
        return receiver.join(args[0])
    if name == "count":
        return receiver.count(args[0])
    if name == "find":
        return receiver.find(args[0])
    raise ValueError("unsupported string method")


def _eval_expr(expr, result, variables=None):
    op = expr["op"]
    if op == "result":
        return result
    if op == "var":
        if variables is None or expr["name"] not in variables:
            raise ValueError("unknown runtime variable")
        return variables[expr["name"]]
    if op == "value":
        return expr["value"]
    if op == "list":
        return [_eval_expr(item, result, variables) for item in expr["items"]]
    if op == "tuple":
        return tuple(_eval_expr(item, result, variables) for item in expr["items"])
    if op == "set":
        return set(_eval_expr(item, result, variables) for item in expr["items"])
    if op == "dict":
        return {
            _eval_expr(key, result, variables): _eval_expr(value, result, variables)
            for key, value in expr["entries"]
        }
    if op == "unary":
        operand = _eval_expr(expr["operand"], result, variables)
        if expr["operator"] == "uadd":
            return +operand
        if expr["operator"] == "usub":
            return -operand
        if expr["operator"] == "not":
            return not operand
    if op == "binary":
        left = _eval_expr(expr["left"], result, variables)
        right = _eval_expr(expr["right"], result, variables)
        operator = expr["operator"]
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mult":
            return left * right
        if operator == "truediv":
            return left / right
        if operator == "floordiv":
            return left // right
        if operator == "mod":
            return left % right
        if operator == "pow":
            return left ** right
    if op == "compare":
        left = _eval_expr(expr["left"], result, variables)
        right = _eval_expr(expr["right"], result, variables)
        operator = expr["operator"]
        if operator == "eq":
            return _deep_equal(left, right)
        if operator == "ne":
            return not _deep_equal(left, right)
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
        if operator == "gt":
            return left > right
        if operator == "gte":
            return left >= right
        if operator == "in":
            return _contains(right, left)
        if operator == "not_in":
            return not _contains(right, left)
    if op == "call":
        return _eval_call(expr["name"], [_eval_expr(arg, result, variables) for arg in expr["args"]])
    if op == "method":
        receiver = _eval_expr(expr["receiver"], result, variables)
        args = [_eval_expr(arg, result, variables) for arg in expr["args"]]
        return _eval_method(expr["name"], receiver, args)
    if op == "subscript":
        return _eval_expr(expr["value"], result, variables)[_eval_expr(expr["index"], result, variables)]
    if op == "slice":
        value = _eval_expr(expr["value"], result, variables)
        lower = _eval_expr(expr["lower"], result, variables) if expr["lower"] is not None else None
        upper = _eval_expr(expr["upper"], result, variables) if expr["upper"] is not None else None
        step = _eval_expr(expr["step"], result, variables) if expr["step"] is not None else None
        return value[slice(lower, upper, step)]
    raise ValueError("unsupported expression operation")


def _effective_abs_tol(case):
    return case["abs_tol"] if case["abs_tol"] is not None else case["default_abs_tol"]


def _message_matches(case, raised):
    mode = case.get("message_match")
    if mode is None:
        return True
    message = str(raised)
    pattern = case.get("message_pattern") or ""
    if mode == "contains":
        return pattern in message
    if mode == "regex":
        try:
            return re.search(pattern, message) is not None
        except re.error:
            return False
    return False


def _exception_matches(case, raised):
    if raised is None or not isinstance(raised, Exception):
        return False
    expected_type = case.get("exception_type")
    if expected_type is not None:
        exception_cls = getattr(builtins, expected_type, None)
        if not isinstance(exception_cls, type) or not isinstance(raised, exception_cls):
            return False
    return _message_matches(case, raised)


def _matches(case, value, raised, variables=None):
    kind = case["kind"]
    if kind == "raises":
        return _exception_matches(case, raised)
    if raised is not None:
        return False
    try:
        actual = _eval_expr(case["actual_expr"], value, variables)
    except Exception:
        return False
    if kind == "mutation":
        return bool(actual)
    if kind == "eq":
        return _deep_equal(actual, case["expected"], _effective_abs_tol(case), case["rel_tol"])
    if kind == "ne":
        return not _deep_equal(actual, case["expected"], _effective_abs_tol(case), case["rel_tol"])
    if kind == "isclose":
        return _numeric_close(actual, case["expected"], case["abs_tol"], case["rel_tol"])
    if kind == "absdiff":
        if not _is_numeric(actual) or not _is_numeric(case["expected"]):
            return False
        if isinstance(actual, Decimal) or isinstance(case["expected"], Decimal) or isinstance(case["abs_tol"], Decimal):
            diff = abs(_to_decimal(actual) - _to_decimal(case["expected"]))
            tolerance = _to_decimal(case["abs_tol"])
        else:
            diff = abs(actual - case["expected"])
            tolerance = case["abs_tol"]
        if case["comparison"] == "abs_lt":
            return diff < tolerance
        return diff <= tolerance
    if kind == "truthy":
        return bool(actual)
    if kind == "not":
        return not bool(actual)
    return False


def run(payload):
    case = _decode_case(payload["case"])
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            namespace = runpy.run_path(payload["solution_path"])
        function = _resolve_callable(namespace, payload["entrypoint"])
    except BaseException:
        print(json.dumps({"passed": False}, separators=(",", ":")))
        return

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    value = None
    raised = None
    variables = None
    if case["kind"] == "mutation":
        variables = {
            name: case["args"][index]
            for name, index in case.get("mutation_arg_names", {}).items()
        }
    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            value = function(*case["args"])
            value = _complete_awaitable(value)
    except BaseException as exc:
        raised = exc

    if raised is None and variables is not None and case.get("mutation_assignment") is not None:
        variables[case["mutation_assignment"]] = value

    passed = _matches(case, value, raised, variables)
    if case["expect_stdout"] is not None:
        passed = passed and stdout_capture.getvalue() == case["expect_stdout"]
    if case["expect_stderr"] is not None:
        passed = passed and stderr_capture.getvalue() == case["expect_stderr"]
    print(json.dumps({"passed": bool(passed)}, separators=(",", ":")))
'''


NODE_CASE_RUNNER = r'''
const fs = require("fs");
const vm = require("vm");

function emit(passed) {
  process.stdout.write(JSON.stringify({passed: Boolean(passed)}) + "\n");
}

function chunkToString(chunk, encoding) {
  if (Buffer.isBuffer(chunk)) {
    return chunk.toString(typeof encoding === "string" ? encoding : "utf8");
  }
  return String(chunk);
}

function installCapture() {
  let stdout = "";
  let stderr = "";
  const originalStdout = process.stdout.write;
  const originalStderr = process.stderr.write;
  process.stdout.write = function(chunk, encoding, callback) {
    stdout += chunkToString(chunk, encoding);
    if (typeof encoding === "function") {
      encoding();
    }
    if (typeof callback === "function") {
      callback();
    }
    return true;
  };
  process.stderr.write = function(chunk, encoding, callback) {
    stderr += chunkToString(chunk, encoding);
    if (typeof encoding === "function") {
      encoding();
    }
    if (typeof callback === "function") {
      callback();
    }
    return true;
  };
  return {
    restore() {
      process.stdout.write = originalStdout;
      process.stderr.write = originalStderr;
    },
    stdout() {
      return stdout;
    },
    stderr() {
      return stderr;
    },
  };
}

function withCaptureSync(fn) {
  const capture = installCapture();
  try {
    const value = fn();
    return {raised: false, value, stdout: capture.stdout(), stderr: capture.stderr()};
  } catch (error) {
    return {raised: true, error, stdout: capture.stdout(), stderr: capture.stderr()};
  } finally {
    capture.restore();
  }
}

async function withCaptureAsync(fn) {
  const capture = installCapture();
  try {
    const value = await fn();
    return {raised: false, value, stdout: capture.stdout(), stderr: capture.stderr()};
  } catch (error) {
    return {raised: true, error, stdout: capture.stdout(), stderr: capture.stderr()};
  } finally {
    capture.restore();
  }
}

function stripTypeScript(source) {
  return source
    .replace(/^\s*export\s+default\s+/gm, "")
    .replace(/^\s*export\s+(?=(function|class|const|let|var)\b)/gm, "")
    .replace(/:\s*[A-Za-z_$][A-Za-z0-9_$<>,\[\]\s|&?.]*(?=\s*[,)=;{])/g, "")
    .replace(/\s+as\s+[A-Za-z_$][A-Za-z0-9_$<>,\[\]\s|&?.]*/g, "");
}

function classNamesFrom(source) {
  const names = new Set();
  const regex = /(?:^|[^\w$])class\s+([A-Za-z_$][A-Za-z0-9_$]*)/g;
  let match;
  while ((match = regex.exec(source)) !== null) {
    names.add(match[1]);
  }
  return [...names];
}

function isIdentifier(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name);
}

function isClass(value) {
  return typeof value === "function" && /^class\s/.test(Function.prototype.toString.call(value));
}

function resolveFromClass(cls, entrypoint) {
  if (typeof cls !== "function") {
    return null;
  }
  if (typeof cls[entrypoint] === "function") {
    return cls[entrypoint].bind(cls);
  }
  try {
    const instance = new cls();
    if (typeof instance[entrypoint] === "function") {
      return instance[entrypoint].bind(instance);
    }
  } catch (_) {
  }
  return null;
}

function resolveCallable(solutionModule, context, entrypoint) {
  const exported = solutionModule.exports;
  if (exported && typeof exported === "object" && typeof exported[entrypoint] === "function") {
    return exported[entrypoint].bind(exported);
  }
  if (typeof exported === "function") {
    const fromClass = resolveFromClass(exported, entrypoint);
    if (fromClass) {
      return fromClass;
    }
    if (!isClass(exported)) {
      return exported;
    }
  }

  const exposed = context.__bcg_exports || {direct: undefined, classes: []};
  if (typeof exposed.direct === "function") {
    return exposed.direct;
  }
  for (const cls of exposed.classes || []) {
    const fromClass = resolveFromClass(cls, entrypoint);
    if (fromClass) {
      return fromClass;
    }
  }
  throw new Error("entrypoint not found");
}

function decodeValue(tag) {
  if (tag === null) {
    return null;
  }
  if (tag.type === "scalar") {
    return tag.value;
  }
  if (tag.type === "decimal") {
    return Number(tag.value);
  }
  if (tag.type === "list" || tag.type === "tuple" || tag.type === "deque") {
    return tag.items.map((item) => decodeValue(item));
  }
  if (tag.type === "set" || tag.type === "frozenset") {
    return new Set(tag.items.map((item) => decodeValue(item)));
  }
  if (tag.type === "counter") {
    return new Map(tag.entries.map(([key, value]) => [decodeValue(key), decodeValue(value)]));
  }
  if (tag.type === "dict" || tag.type === "defaultdict") {
    const entries = tag.entries.map(([key, value]) => [decodeValue(key), decodeValue(value)]);
    if (entries.every(([key]) => typeof key === "string")) {
      const object = {};
      for (const [key, value] of entries) {
        object[key] = value;
      }
      return object;
    }
    return new Map(entries);
  }
  throw new Error("unsupported value tag");
}

function decodeExpr(expr) {
  if (expr.op === "value") {
    return {...expr, value: decodeValue(expr.value)};
  }
  if (expr.op === "var") {
    return {op: "var", name: expr.name};
  }
  if (expr.op === "result") {
    return {op: "result"};
  }
  if (expr.op === "list" || expr.op === "tuple" || expr.op === "set") {
    return {...expr, items: expr.items.map((item) => decodeExpr(item))};
  }
  if (expr.op === "dict") {
    return {...expr, entries: expr.entries.map(([key, value]) => [decodeExpr(key), decodeExpr(value)])};
  }
  if (expr.op === "unary") {
    return {...expr, operand: decodeExpr(expr.operand)};
  }
  if (expr.op === "binary" || expr.op === "compare") {
    return {...expr, left: decodeExpr(expr.left), right: decodeExpr(expr.right)};
  }
  if (expr.op === "call") {
    return {...expr, args: expr.args.map((arg) => decodeExpr(arg))};
  }
  if (expr.op === "method") {
    return {...expr, receiver: decodeExpr(expr.receiver), args: expr.args.map((arg) => decodeExpr(arg))};
  }
  if (expr.op === "subscript") {
    return {...expr, value: decodeExpr(expr.value), index: decodeExpr(expr.index)};
  }
  if (expr.op === "slice") {
    return {
      ...expr,
      value: decodeExpr(expr.value),
      lower: expr.lower === null ? null : decodeExpr(expr.lower),
      upper: expr.upper === null ? null : decodeExpr(expr.upper),
      step: expr.step === null ? null : decodeExpr(expr.step),
    };
  }
  throw new Error("unsupported expression operation");
}

function decodeCase(testCase) {
  return {
    ...testCase,
    args: testCase.args.map((item) => decodeValue(item)),
    actual_expr: decodeExpr(testCase.actual_expr || {op: "result"}),
    expected: decodeValue(testCase.expected),
    abs_tol: decodeValue(testCase.abs_tol),
    rel_tol: decodeValue(testCase.rel_tol),
    default_abs_tol: decodeValue(testCase.default_abs_tol),
    mutation_arg_names: testCase.mutation_arg_names || {},
  };
}

function isMap(value) {
  return value instanceof Map || Object.prototype.toString.call(value) === "[object Map]";
}

function isSet(value) {
  return value instanceof Set || Object.prototype.toString.call(value) === "[object Set]";
}

function isPlainObject(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    !isMap(value) &&
    !isSet(value)
  );
}

function isMapping(value) {
  return isMap(value) || isPlainObject(value);
}

function mappingEntries(value) {
  if (isMap(value)) {
    return [...value.entries()];
  }
  return Object.keys(value).map((key) => [key, value[key]]);
}

function isNumeric(value) {
  return typeof value === "number" && !Number.isNaN(value);
}

function numericClose(left, right, absTol, relTol) {
  if (!isNumeric(left) || !isNumeric(right)) {
    return false;
  }
  const absolute = absTol === null ? 0 : Number(absTol);
  const relative = relTol === null ? 0 : Number(relTol);
  const diff = Math.abs(left - right);
  const limit = Math.max(absolute, relative * Math.max(Math.abs(left), Math.abs(right)));
  return diff <= limit;
}

function unorderedEqual(leftItems, rightItems, absTol, relTol) {
  const unmatched = [...rightItems];
  for (const leftItem of leftItems) {
    const index = unmatched.findIndex((rightItem) => deepEqual(leftItem, rightItem, absTol, relTol));
    if (index === -1) {
      return false;
    }
    unmatched.splice(index, 1);
  }
  return unmatched.length === 0;
}

function mappingEqual(left, right, absTol, relTol) {
  const leftEntries = mappingEntries(left);
  const rightEntries = mappingEntries(right);
  if (leftEntries.length !== rightEntries.length) {
    return false;
  }
  const unmatched = [...rightEntries];
  for (const [leftKey, leftValue] of leftEntries) {
    const index = unmatched.findIndex(([rightKey, rightValue]) => (
      deepEqual(leftKey, rightKey, absTol, relTol) &&
      deepEqual(leftValue, rightValue, absTol, relTol)
    ));
    if (index === -1) {
      return false;
    }
    unmatched.splice(index, 1);
  }
  return unmatched.length === 0;
}

function deepEqual(left, right, absTol = null, relTol = null) {
  if (isNumeric(left) && isNumeric(right) && (absTol !== null || relTol !== null)) {
    return numericClose(left, right, absTol, relTol);
  }
  if (Object.is(left, right)) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false;
    }
    return left.every((item, index) => deepEqual(item, right[index], absTol, relTol));
  }
  if (isSet(left) || isSet(right)) {
    if (!isSet(left) || !isSet(right) || left.size !== right.size) {
      return false;
    }
    return unorderedEqual(left.values(), right.values(), absTol, relTol);
  }
  if (isMapping(left) || isMapping(right)) {
    if (!isMapping(left) || !isMapping(right)) {
      return false;
    }
    return mappingEqual(left, right, absTol, relTol);
  }
  return false;
}

function effectiveAbsTol(testCase) {
  return testCase.abs_tol !== null ? testCase.abs_tol : testCase.default_abs_tol;
}

function pyTruthy(value) {
  if (value === null || value === undefined || value === false) {
    return false;
  }
  if (typeof value === "number") {
    return value !== 0 && !Number.isNaN(value);
  }
  if (typeof value === "string" || Array.isArray(value)) {
    return value.length > 0;
  }
  if (isMap(value) || isSet(value)) {
    return value.size > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

function contains(container, item) {
  if (typeof container === "string") {
    return typeof item === "string" && container.includes(item);
  }
  if (Array.isArray(container)) {
    return container.some((value) => deepEqual(value, item));
  }
  if (isSet(container)) {
    return [...container.values()].some((value) => deepEqual(value, item));
  }
  if (isMap(container)) {
    return [...container.keys()].some((key) => deepEqual(key, item));
  }
  if (isPlainObject(container)) {
    return typeof item === "string" && Object.prototype.hasOwnProperty.call(container, item);
  }
  return false;
}

function lengthOf(value) {
  if (typeof value === "string" || Array.isArray(value)) {
    return value.length;
  }
  if (isSet(value) || isMap(value)) {
    return value.size;
  }
  if (isPlainObject(value)) {
    return Object.keys(value).length;
  }
  throw new Error("unsupported len target");
}

function iterableArray(value) {
  if (typeof value === "string") {
    return [...value];
  }
  if (Array.isArray(value)) {
    return [...value];
  }
  if (isSet(value)) {
    return [...value.values()];
  }
  if (isMap(value)) {
    return [...value.keys()];
  }
  if (isPlainObject(value)) {
    return Object.keys(value);
  }
  throw new Error("unsupported iterable target");
}

function comparePrimitive(left, right) {
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return String(left).localeCompare(String(right));
}

function repeatArray(items, count) {
  const times = Math.trunc(Number(count));
  if (!Number.isFinite(times) || times < 0) {
    throw new Error("invalid repeat count");
  }
  const result = [];
  for (let index = 0; index < times; index += 1) {
    result.push(...items);
  }
  return result;
}

function binaryValue(operator, left, right) {
  if (operator === "add") {
    if (Array.isArray(left) && Array.isArray(right)) {
      return left.concat(right);
    }
    return left + right;
  }
  if (operator === "sub") {
    return left - right;
  }
  if (operator === "mult") {
    if (Array.isArray(left) && typeof right === "number") {
      return repeatArray(left, right);
    }
    if (typeof left === "number" && Array.isArray(right)) {
      return repeatArray(right, left);
    }
    if (typeof left === "string" && typeof right === "number") {
      return left.repeat(Math.trunc(right));
    }
    if (typeof left === "number" && typeof right === "string") {
      return right.repeat(Math.trunc(left));
    }
    return left * right;
  }
  if (operator === "truediv") {
    return left / right;
  }
  if (operator === "floordiv") {
    return Math.floor(left / right);
  }
  if (operator === "mod") {
    return left % right;
  }
  if (operator === "pow") {
    return left ** right;
  }
  throw new Error("unsupported binary operator");
}

function callValue(name, args) {
  if (name === "abs") {
    return Math.abs(args[0]);
  }
  if (name === "bool") {
    return pyTruthy(args[0]);
  }
  if (name === "float") {
    const value = Number(args[0]);
    if (Number.isNaN(value)) {
      throw new Error("invalid float value");
    }
    return value;
  }
  if (name === "frozenset" || name === "set") {
    return new Set(iterableArray(args[0]));
  }
  if (name === "int") {
    const value = Number(args[0]);
    if (Number.isNaN(value)) {
      throw new Error("invalid int value");
    }
    return Math.trunc(value);
  }
  if (name === "len") {
    return lengthOf(args[0]);
  }
  if (name === "list" || name === "tuple") {
    return iterableArray(args[0]);
  }
  if (name === "max" || name === "min") {
    const values = args.length === 1 ? iterableArray(args[0]) : args;
    if (values.length === 0) {
      throw new Error("empty sequence");
    }
    return values.reduce((best, item) => (
      name === "max"
        ? (comparePrimitive(item, best) > 0 ? item : best)
        : (comparePrimitive(item, best) < 0 ? item : best)
    ));
  }
  if (name === "sorted") {
    return iterableArray(args[0]).sort(comparePrimitive);
  }
  if (name === "str") {
    return String(args[0]);
  }
  if (name === "sum") {
    return iterableArray(args[0]).reduce((total, item) => total + item, 0);
  }
  throw new Error("unsupported primitive call");
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripChars(value, chars, side) {
  if (chars === undefined) {
    if (side === "left") {
      return value.replace(/^\s+/, "");
    }
    if (side === "right") {
      return value.replace(/\s+$/, "");
    }
    return value.trim();
  }
  const pattern = `[${escapeRegex(chars)}]`;
  if (side === "left") {
    return value.replace(new RegExp(`^${pattern}+`), "");
  }
  if (side === "right") {
    return value.replace(new RegExp(`${pattern}+$`), "");
  }
  return value.replace(new RegExp(`^${pattern}+|${pattern}+$`, "g"), "");
}

function splitMax(value, separator, maxSplit) {
  if (maxSplit === undefined) {
    return value.split(separator);
  }
  const limit = Math.trunc(Number(maxSplit));
  if (limit < 0) {
    return value.split(separator);
  }
  const parts = value.split(separator);
  if (parts.length <= limit + 1) {
    return parts;
  }
  return parts.slice(0, limit).concat(parts.slice(limit).join(separator));
}

function countSubstring(value, needle) {
  if (needle === "") {
    return value.length + 1;
  }
  let count = 0;
  let index = 0;
  while (true) {
    const found = value.indexOf(needle, index);
    if (found === -1) {
      return count;
    }
    count += 1;
    index = found + needle.length;
  }
}

function methodValue(name, receiver, args) {
  if (typeof receiver !== "string") {
    throw new Error("string method receiver must be a string");
  }
  if (name === "upper") {
    return receiver.toUpperCase();
  }
  if (name === "lower") {
    return receiver.toLowerCase();
  }
  if (name === "strip") {
    return stripChars(receiver, args[0], "both");
  }
  if (name === "lstrip") {
    return stripChars(receiver, args[0], "left");
  }
  if (name === "rstrip") {
    return stripChars(receiver, args[0], "right");
  }
  if (name === "startswith") {
    return receiver.startsWith(args[0]);
  }
  if (name === "endswith") {
    return receiver.endsWith(args[0]);
  }
  if (name === "replace") {
    return receiver.split(args[0]).join(args[1]);
  }
  if (name === "split") {
    if (args.length === 0) {
      const trimmed = receiver.trim();
      return trimmed === "" ? [] : trimmed.split(/\s+/);
    }
    return splitMax(receiver, args[0], args[1]);
  }
  if (name === "join") {
    return iterableArray(args[0]).join(receiver);
  }
  if (name === "count") {
    return countSubstring(receiver, args[0]);
  }
  if (name === "find") {
    return receiver.indexOf(args[0]);
  }
  throw new Error("unsupported string method");
}

function subscriptValue(value, index) {
  if (Array.isArray(value) || typeof value === "string") {
    const numeric = Math.trunc(Number(index));
    const resolved = numeric < 0 ? value.length + numeric : numeric;
    return value[resolved];
  }
  if (isMap(value)) {
    for (const [key, item] of value.entries()) {
      if (deepEqual(key, index)) {
        return item;
      }
    }
    return undefined;
  }
  if (isPlainObject(value)) {
    return value[index];
  }
  throw new Error("unsupported subscript target");
}

function sliceValue(value, lower, upper, step) {
  const sequence = typeof value === "string" ? [...value] : iterableArray(value);
  const actualStep = step === null ? 1 : Math.trunc(Number(step));
  if (actualStep === 0) {
    throw new Error("slice step cannot be zero");
  }
  if (actualStep === 1) {
    const sliced = sequence.slice(lower === null ? undefined : lower, upper === null ? undefined : upper);
    return typeof value === "string" ? sliced.join("") : sliced;
  }
  const result = [];
  const length = sequence.length;
  let start = lower === null ? (actualStep > 0 ? 0 : length - 1) : (lower < 0 ? length + lower : lower);
  const stop = upper === null ? (actualStep > 0 ? length : -1) : (upper < 0 ? length + upper : upper);
  if (actualStep > 0) {
    for (let index = start; index < stop; index += actualStep) {
      result.push(sequence[index]);
    }
  } else {
    for (let index = start; index > stop; index += actualStep) {
      result.push(sequence[index]);
    }
  }
  return typeof value === "string" ? result.join("") : result;
}

function evalExpr(expr, result, variables = null) {
  if (expr.op === "result") {
    return result;
  }
  if (expr.op === "var") {
    if (variables === null || !Object.prototype.hasOwnProperty.call(variables, expr.name)) {
      throw new Error("unknown runtime variable");
    }
    return variables[expr.name];
  }
  if (expr.op === "value") {
    return expr.value;
  }
  if (expr.op === "list" || expr.op === "tuple") {
    return expr.items.map((item) => evalExpr(item, result, variables));
  }
  if (expr.op === "set") {
    return new Set(expr.items.map((item) => evalExpr(item, result, variables)));
  }
  if (expr.op === "dict") {
    const entries = expr.entries.map(([key, value]) => [
      evalExpr(key, result, variables),
      evalExpr(value, result, variables),
    ]);
    if (entries.every(([key]) => typeof key === "string")) {
      const object = {};
      for (const [key, value] of entries) {
        object[key] = value;
      }
      return object;
    }
    return new Map(entries);
  }
  if (expr.op === "unary") {
    const operand = evalExpr(expr.operand, result, variables);
    if (expr.operator === "uadd") {
      return +operand;
    }
    if (expr.operator === "usub") {
      return -operand;
    }
    if (expr.operator === "not") {
      return !pyTruthy(operand);
    }
  }
  if (expr.op === "binary") {
    return binaryValue(
      expr.operator,
      evalExpr(expr.left, result, variables),
      evalExpr(expr.right, result, variables),
    );
  }
  if (expr.op === "compare") {
    const left = evalExpr(expr.left, result, variables);
    const right = evalExpr(expr.right, result, variables);
    if (expr.operator === "eq") {
      return deepEqual(left, right);
    }
    if (expr.operator === "ne") {
      return !deepEqual(left, right);
    }
    if (expr.operator === "lt") {
      return left < right;
    }
    if (expr.operator === "lte") {
      return left <= right;
    }
    if (expr.operator === "gt") {
      return left > right;
    }
    if (expr.operator === "gte") {
      return left >= right;
    }
    if (expr.operator === "in") {
      return contains(right, left);
    }
    if (expr.operator === "not_in") {
      return !contains(right, left);
    }
  }
  if (expr.op === "call") {
    return callValue(expr.name, expr.args.map((arg) => evalExpr(arg, result, variables)));
  }
  if (expr.op === "method") {
    return methodValue(
      expr.name,
      evalExpr(expr.receiver, result, variables),
      expr.args.map((arg) => evalExpr(arg, result, variables)),
    );
  }
  if (expr.op === "subscript") {
    return subscriptValue(
      evalExpr(expr.value, result, variables),
      evalExpr(expr.index, result, variables),
    );
  }
  if (expr.op === "slice") {
    return sliceValue(
      evalExpr(expr.value, result, variables),
      expr.lower === null ? null : evalExpr(expr.lower, result, variables),
      expr.upper === null ? null : evalExpr(expr.upper, result, variables),
      expr.step === null ? null : evalExpr(expr.step, result, variables),
    );
  }
  throw new Error("unsupported expression operation");
}

function exceptionName(error) {
  if (error && typeof error === "object") {
    return error.name || (error.constructor && error.constructor.name) || "";
  }
  return "";
}

function exceptionMessage(error) {
  if (error && typeof error === "object" && "message" in error) {
    return String(error.message);
  }
  return String(error);
}

function exceptionMatches(testCase, error) {
  if (!error) {
    return false;
  }
  if (testCase.exception_type !== null) {
    const names = new Set([exceptionName(error), error && error.constructor ? error.constructor.name : ""]);
    if (!names.has(testCase.exception_type)) {
      return false;
    }
  }
  if (testCase.message_match === null) {
    return true;
  }
  const message = exceptionMessage(error);
  if (testCase.message_match === "contains") {
    return message.includes(testCase.message_pattern || "");
  }
  if (testCase.message_match === "regex") {
    try {
      return new RegExp(testCase.message_pattern || "").test(message);
    } catch (_) {
      return false;
    }
  }
  return false;
}

function assertionMatches(testCase, callResult) {
  if (testCase.kind === "raises") {
    return callResult.raised && exceptionMatches(testCase, callResult.error);
  }
  if (callResult.raised) {
    return false;
  }
  let actual;
  try {
    actual = evalExpr(testCase.actual_expr, callResult.value, callResult.variables || null);
  } catch (_) {
    return false;
  }
  if (testCase.kind === "mutation") {
    return pyTruthy(actual);
  }
  if (testCase.kind === "eq") {
    return deepEqual(actual, testCase.expected, effectiveAbsTol(testCase), testCase.rel_tol);
  }
  if (testCase.kind === "ne") {
    return !deepEqual(actual, testCase.expected, effectiveAbsTol(testCase), testCase.rel_tol);
  }
  if (testCase.kind === "isclose") {
    return numericClose(actual, testCase.expected, testCase.abs_tol, testCase.rel_tol);
  }
  if (testCase.kind === "absdiff") {
    if (!isNumeric(actual) || !isNumeric(testCase.expected)) {
      return false;
    }
    const diff = Math.abs(actual - testCase.expected);
    if (testCase.comparison === "abs_lt") {
      return diff < testCase.abs_tol;
    }
    return diff <= testCase.abs_tol;
  }
  if (testCase.kind === "truthy") {
    return pyTruthy(actual);
  }
  if (testCase.kind === "not") {
    return !pyTruthy(actual);
  }
  return false;
}

(async function main() {
  try {
    const solutionPath = process.env.BCG_SOLUTION_PATH;
    const entrypoint = process.env.BCG_ENTRYPOINT;
    const language = process.env.BCG_LANG;
    const testCase = decodeCase(JSON.parse(process.env.BCG_CASE));
    let source = fs.readFileSync(solutionPath, "utf8");
    if (language === "typescript") {
      source = stripTypeScript(source);
    }

    const solutionModule = {exports: {}};
    const context = {
      console,
      require,
      process,
      Buffer,
      setTimeout,
      clearTimeout,
      module: solutionModule,
      exports: solutionModule.exports,
    };
    context.globalThis = context;
    const classNames = classNamesFrom(source);
    const directExpr = isIdentifier(entrypoint)
      ? `(typeof ${entrypoint} !== "undefined" ? ${entrypoint} : undefined)`
      : "undefined";
    const classExprs = classNames
      .filter(isIdentifier)
      .map((name) => `(typeof ${name} !== "undefined" ? ${name} : undefined)`);
    const expose = `\n;globalThis.__bcg_exports = {direct: ${directExpr}, classes: [${classExprs.join(",")}]};`;

    vm.createContext(context);
    const loadResult = withCaptureSync(() => vm.runInContext(source + expose, context, {filename: solutionPath}));
    if (loadResult.raised) {
      emit(false);
      return;
    }

    const callable = resolveCallable(solutionModule, context, entrypoint);
    let variables = null;
    if (testCase.kind === "mutation") {
      variables = {};
      for (const [name, index] of Object.entries(testCase.mutation_arg_names || {})) {
        variables[name] = testCase.args[index];
      }
    }
    const callResult = await withCaptureAsync(() => callable(...testCase.args));
    if (!callResult.raised && variables !== null && testCase.mutation_assignment !== null) {
      variables[testCase.mutation_assignment] = callResult.value;
    }
    callResult.variables = variables;
    let passed = assertionMatches(testCase, callResult);
    if (testCase.expect_stdout !== null) {
      passed = passed && callResult.stdout === testCase.expect_stdout;
    }
    if (testCase.expect_stderr !== null) {
      passed = passed && callResult.stderr === testCase.expect_stderr;
    }
    emit(passed);
  } catch (_) {
    emit(false);
  }
})();
'''


def run_node_case(
    solution_path: Path,
    entrypoint: str,
    lang: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    node_path = shutil.which("node")
    if node_path is None:
        return False
    env = os.environ.copy()
    env.update(
        {
            "BCG_SOLUTION_PATH": str(solution_path),
            "BCG_ENTRYPOINT": entrypoint,
            "BCG_LANG": lang,
            "BCG_CASE": json_line(case_to_json(case, default_abs_tol)),
        }
    )
    try:
        proc = subprocess.run(
            [node_path, "-"],
            input=NODE_CASE_RUNNER,
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout_seconds or DEFAULT_CASE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(proc)


def render_cpp_case_source(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    param_types: list[str],
) -> str:
    include_path = str(solution_path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    arg_lines: list[str] = []
    call_args: list[str] = []
    for index, arg in enumerate(case.args):
        context = param_types[index] if index < len(param_types) else None
        value_type = normalize_cpp_type(context)
        rendered = render_cpp_value(arg, value_type)
        if value_type is not None:
            arg_lines.append(f"        {value_type} __bcg_arg{index} = {rendered};")
        else:
            arg_lines.append(f"        auto __bcg_arg{index} = {rendered};")
        call_args.append(f"__bcg_arg{index}")

    variables = {
        name: f"__bcg_arg{index}"
        for name, index in case.mutation_arg_names.items()
    }
    if case.mutation_assignment is not None:
        variables[case.mutation_assignment] = "__bcg_result"
    actual_expr = render_cpp_expr(case.actual_expr, variables)
    call = f"{entrypoint}({', '.join(call_args)})"
    completed_call = f"__bcg_complete({call})"
    body = list(arg_lines)
    if case.kind == "raises":
        body.append(f"        __bcg_complete_statement([&]() {{ return {call}; }});")
    elif case.kind == "mutation" and case.mutation_assignment is None:
        body.append(f"        __bcg_complete_statement([&]() {{ return {call}; }});")
        body.append(f"        auto __bcg_actual = {actual_expr};")
        body.append("        __bcg_actual_json = __bcg_to_json(__bcg_actual);")
    else:
        body.append(f"        auto __bcg_result = {completed_call};")
        body.append(f"        auto __bcg_actual = {actual_expr};")
        body.append("        __bcg_actual_json = __bcg_to_json(__bcg_actual);")

    body_source = "\n".join(body)
    return f'''{CPP_HARNESS_HELPERS}
#include "{include_path}"

int main() {{
    std::ostringstream __bcg_stdout_capture;
    std::ostringstream __bcg_stderr_capture;
    auto* __bcg_old_stdout = std::cout.rdbuf(__bcg_stdout_capture.rdbuf());
    auto* __bcg_old_stderr = std::cerr.rdbuf(__bcg_stderr_capture.rdbuf());
    bool __bcg_raised = false;
    std::string __bcg_exception_type;
    std::string __bcg_message;
    std::string __bcg_actual_json = "null";
    try {{
{body_source}
    }} catch (const std::invalid_argument& e) {{
        __bcg_raised = true;
        __bcg_exception_type = "ValueError";
        __bcg_message = e.what();
    }} catch (const std::out_of_range& e) {{
        __bcg_raised = true;
        __bcg_exception_type = "IndexError";
        __bcg_message = e.what();
    }} catch (const std::runtime_error& e) {{
        __bcg_raised = true;
        __bcg_exception_type = "RuntimeError";
        __bcg_message = e.what();
    }} catch (const std::exception& e) {{
        __bcg_raised = true;
        __bcg_exception_type = "Exception";
        __bcg_message = e.what();
    }} catch (...) {{
        __bcg_raised = true;
        __bcg_exception_type = "Exception";
        __bcg_message = "";
    }}
    std::cout.rdbuf(__bcg_old_stdout);
    std::cerr.rdbuf(__bcg_old_stderr);
    std::cout
        << "{{\\"raised\\":" << (__bcg_raised ? "true" : "false")
        << ",\\"exception_type\\":" << __bcg_json_string(__bcg_exception_type)
        << ",\\"message\\":" << __bcg_json_string(__bcg_message)
        << ",\\"stdout\\":" << __bcg_json_string(__bcg_stdout_capture.str())
        << ",\\"stderr\\":" << __bcg_json_string(__bcg_stderr_capture.str())
        << ",\\"actual\\":" << __bcg_actual_json
        << "}}" << std::endl;
    return 0;
}}
'''


def render_rust_case_source(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    param_types: list[str],
    entrypoint_returns_future: bool = False,
) -> str:
    include_path = str(solution_path.resolve())
    arg_lines: list[str] = []
    call_args: list[str] = []
    for index, arg in enumerate(case.args):
        raw_context = param_types[index] if index < len(param_types) else None
        variable_type = normalize_rust_type(raw_context)
        rendered = render_rust_value(arg, raw_context)
        if variable_type is not None and variable_type != "str":
            arg_lines.append(f"        let mut __bcg_arg{index}: {variable_type} = {rendered};")
        else:
            arg_lines.append(f"        let mut __bcg_arg{index} = {rendered};")
        call_args.append(rust_call_arg(f"__bcg_arg{index}", raw_context))

    variables = {
        name: f"__bcg_arg{index}"
        for name, index in case.mutation_arg_names.items()
    }
    if case.mutation_assignment is not None:
        variables[case.mutation_assignment] = "__bcg_result"
    actual_expr = render_rust_expr(case.actual_expr, variables)
    call = f"{entrypoint}({', '.join(call_args)})"
    completed_call = f"__bcg_block_on({call})" if entrypoint_returns_future else call
    body = list(arg_lines)
    if case.kind == "raises":
        body.append(f"        let _ = {completed_call};")
        body.append("        String::from(\"{\\\"type\\\":\\\"scalar\\\",\\\"value\\\":null}\")")
    elif case.kind == "mutation" and case.mutation_assignment is None:
        body.append(f"        {completed_call};")
        body.append(f"        let __bcg_actual = {actual_expr};")
        body.append("        __bcg_to_json(&__bcg_actual)")
    else:
        body.append(f"        let __bcg_result = {completed_call};")
        body.append(f"        let __bcg_actual = {actual_expr};")
        body.append("        __bcg_to_json(&__bcg_actual)")
    body_source = "\n".join(body)
    return f'''{RUST_HARNESS_HELPERS}
include!(r#"{include_path}"#);

fn main() {{
    let (__bcg_run, __bcg_stdout, __bcg_stderr) = __bcg_capture::run(|| {{
{body_source}
    }});
    let mut __bcg_raised = false;
    let mut __bcg_exception_type = String::new();
    let mut __bcg_message = String::new();
    let __bcg_actual_json = match __bcg_run {{
        Ok(value) => value,
        Err(error) => {{
            __bcg_raised = true;
            __bcg_exception_type = String::from("Exception");
            __bcg_message = __bcg_panic_message(error.as_ref());
            String::from("null")
        }}
    }};
    println!(
        "{{\\"raised\\":{{}},\\"exception_type\\":{{}},\\"message\\":{{}},\\"stdout\\":{{}},\\"stderr\\":{{}},\\"actual\\":{{}}}}",
        if __bcg_raised {{ "true" }} else {{ "false" }},
        __bcg_json_string(&__bcg_exception_type),
        __bcg_json_string(&__bcg_message),
        __bcg_json_string(&__bcg_stdout),
        __bcg_json_string(&__bcg_stderr),
        __bcg_actual_json
    );
}}
'''


def parse_target_result(proc: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if proc.returncode != 0:
        return None
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def run_cpp_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        return False
    try:
        solution_source = solution_path.read_text(encoding="utf-8")
        param_types = parse_cpp_param_types(solution_source, entrypoint)
        harness_source = render_cpp_case_source(solution_path, entrypoint, case, param_types)
    except (OSError, DiscoveryError):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        harness_path = tmp_path / "bcg_case.cpp"
        binary_path = tmp_path / "bcg_case"
        harness_path.write_text(harness_source, encoding="utf-8")
        started = time.monotonic()
        try:
            compile_timeout = timeout_seconds or DEFAULT_COMPILE_TIMEOUT_SECONDS
            compile_proc = subprocess.run(
                [compiler, "-std=c++17", str(harness_path), "-o", str(binary_path)],
                text=True,
                capture_output=True,
                timeout=compile_timeout,
            )
            if compile_proc.returncode != 0:
                return False
            if timeout_seconds is None:
                run_timeout = DEFAULT_CASE_TIMEOUT_SECONDS
            else:
                run_timeout = timeout_seconds - (time.monotonic() - started)
                if run_timeout <= 0:
                    return False
                run_timeout = max(run_timeout, MIN_TIMEOUT_SECONDS)
            proc = subprocess.run(
                [str(binary_path)],
                text=True,
                capture_output=True,
                timeout=run_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    result = parse_target_result(proc)
    return False if result is None else target_case_matches(case, result, default_abs_tol)


def run_rust_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    if case_requires_deque(case):
        return True
    compiler = shutil.which("rustc")
    if compiler is None:
        return False
    try:
        solution_source = solution_path.read_text(encoding="utf-8")
        param_types = parse_rust_param_types(solution_source, entrypoint)
        harness_source = render_rust_case_source(
            solution_path,
            entrypoint,
            case,
            param_types,
            rust_entrypoint_returns_future(solution_source, entrypoint),
        )
    except (OSError, DiscoveryError):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        harness_path = tmp_path / "bcg_case.rs"
        binary_path = tmp_path / "bcg_case"
        harness_path.write_text(harness_source, encoding="utf-8")
        started = time.monotonic()
        try:
            compile_timeout = timeout_seconds or DEFAULT_COMPILE_TIMEOUT_SECONDS
            compile_proc = subprocess.run(
                [compiler, "--edition=2021", str(harness_path), "-o", str(binary_path)],
                text=True,
                capture_output=True,
                timeout=compile_timeout,
            )
            if compile_proc.returncode != 0:
                return False
            if timeout_seconds is None:
                run_timeout = DEFAULT_CASE_TIMEOUT_SECONDS
            else:
                run_timeout = timeout_seconds - (time.monotonic() - started)
                if run_timeout <= 0:
                    return False
                run_timeout = max(run_timeout, MIN_TIMEOUT_SECONDS)
            proc = subprocess.run(
                [str(binary_path)],
                text=True,
                capture_output=True,
                timeout=run_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    result = parse_target_result(proc)
    return False if result is None else target_case_matches(case, result, default_abs_tol)


def parse_subprocess_result(proc: subprocess.CompletedProcess[str]) -> bool:
    if proc.returncode != 0:
        return False
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return False
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError:
        return False
    return data.get("passed") is True


def execute_case(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    if case.kind == "loop":
        return case.loop_pass is True
    if lang == "python":
        return run_python_case(solution_path, entrypoint, case, default_abs_tol, timeout_seconds)
    if lang in {"javascript", "typescript"}:
        return run_node_case(solution_path, entrypoint, lang, case, default_abs_tol, timeout_seconds)
    if lang == "cpp":
        return run_cpp_case(solution_path, entrypoint, case, default_abs_tol, timeout_seconds)
    if lang == "rust":
        return run_rust_case(solution_path, entrypoint, case, default_abs_tol, timeout_seconds)
    return False


def aggregate_results(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None = None,
    timeout_seconds: float | None = None,
    total_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    passed: list[str] = []
    failed: list[str] = []
    deadline = None if total_timeout_seconds is None else time.monotonic() + total_timeout_seconds
    for index, case in enumerate(cases):
        effective_timeout = timeout_seconds
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failed.extend(item.id for item in cases[index:])
                break
            effective_timeout = remaining if effective_timeout is None else min(effective_timeout, remaining)
            effective_timeout = max(effective_timeout, MIN_TIMEOUT_SECONDS)
        if execute_case(solution_path, lang, entrypoint, case, default_abs_tol, effective_timeout):
            passed.append(case.id)
        else:
            failed.append(case.id)
    status = "pass" if not failed else "fail"
    return {"status": status, "passed": passed, "failed": failed}


def prepare_run_context(args: argparse.Namespace) -> RunContext:
    lang = args.lang
    if not is_supported_lang(lang):
        raise CommandError("unsupported language")
    if args.list_tests and args.run is not None:
        raise CommandError("conflicting selection flags")
    try:
        default_abs_tol = parse_default_tolerance(args.tol)
        timeout_seconds = parse_positive_timeout_seconds(args.timeout_ms)
        total_timeout_seconds = parse_positive_timeout_seconds(args.total_timeout_ms)
    except DiscoveryError as exc:
        raise CommandError("invalid common options") from exc

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / tester_filename(lang)
    if not tester_path.is_file():
        raise CommandError("missing tester")

    try:
        metadata = read_tester_metadata(tester_path)
    except MetadataError as exc:
        raise CommandError("invalid tester metadata") from exc
    if metadata["lang"] != lang:
        raise CommandError("tester language mismatch")

    try:
        cases = discover_tests(tests_dir, metadata["entrypoint"])
    except DiscoveryError as exc:
        raise CommandError("discovery failed") from exc

    if args.run is not None:
        selected = [case for case in cases if case.id == args.run]
        if not selected:
            raise CommandError("unknown selected test")
        cases = selected

    return RunContext(
        solution_path=Path(args.solution_path),
        tests_dir=tests_dir,
        lang=lang,
        entrypoint=metadata["entrypoint"],
        cases=cases,
        default_abs_tol=default_abs_tol,
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
    )


def list_tests_result(cases: list[TestCase]) -> dict[str, Any]:
    return {"status": "pass", "passed": [case.id for case in cases], "failed": []}


def sample_stats(samples: list[float]) -> dict[str, float]:
    mean = sum(samples) / len(samples)
    variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
    return {"mean": mean, "std": math.sqrt(variance)}


def rusage_memory_kb(who: int) -> float:
    if resource is None:
        return 0.0
    try:
        value = float(resource.getrusage(who).ru_maxrss)
    except (OSError, ValueError):
        return 0.0
    if sys.platform == "darwin":
        value /= 1024.0
    return value


def current_memory_kb() -> float:
    if resource is None:
        return 0.0
    return rusage_memory_kb(resource.RUSAGE_SELF) + rusage_memory_kb(resource.RUSAGE_CHILDREN)


def aggregate_profile_results(
    context: RunContext,
    trials: int,
    warmup: int,
    include_memory: bool,
) -> dict[str, Any]:
    measured_results: list[dict[str, Any]] = []
    runtime_samples: list[float] = []
    memory_samples: list[float] = []

    for trial_index in range(trials):
        started_ns = time.perf_counter_ns()
        result = aggregate_results(
            context.solution_path,
            context.lang,
            context.entrypoint,
            context.cases,
            context.default_abs_tol,
            context.timeout_seconds,
            context.total_timeout_seconds,
        )
        elapsed_ns = time.perf_counter_ns() - started_ns
        memory_kb = current_memory_kb() if include_memory else None

        if trial_index >= warmup:
            measured_results.append(result)
            runtime_samples.append(float(elapsed_ns))
            if include_memory:
                memory_samples.append(float(memory_kb))

    failed_ids: list[str] = []
    failed_set: set[str] = set()
    for result in measured_results:
        for test_id in result["failed"]:
            if test_id not in failed_set:
                failed_set.add(test_id)
                failed_ids.append(test_id)

    passed_ids = [case.id for case in context.cases if case.id not in failed_set]
    profile_result: dict[str, Any] = {
        "status": "pass" if not failed_ids else "fail",
        "passed": passed_ids,
        "failed": failed_ids,
        "runtime_ns": sample_stats(runtime_samples),
    }
    if include_memory:
        profile_result["memory_kb"] = sample_stats(memory_samples)
    return profile_result


def command_generate(args: argparse.Namespace) -> int:
    lang = args.lang
    tests_dir = Path(args.tests_dir)

    if not is_supported_lang(lang):
        print(f"unsupported language: {lang}", file=sys.stderr)
        return 2
    if not is_valid_entrypoint(args.entrypoint):
        print("invalid entrypoint", file=sys.stderr)
        return 2
    if not tests_dir.is_dir():
        print("tests_dir must be an existing directory", file=sys.stderr)
        return 2

    try:
        discover_tests(tests_dir, args.entrypoint)
        content = render_tester(lang, args.entrypoint)
    except DiscoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        write_atomic(tests_dir / tester_filename(lang), content)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def command_test(args: argparse.Namespace) -> int:
    try:
        context = prepare_run_context(args)
    except CommandError:
        print_json_result(error_result())
        return 2

    if args.list_tests:
        print_json_result(list_tests_result(context.cases))
        return 0

    result = aggregate_results(
        context.solution_path,
        context.lang,
        context.entrypoint,
        context.cases,
        context.default_abs_tol,
        context.timeout_seconds,
        context.total_timeout_seconds,
    )
    print_json_result(result)
    return status_exit_code(result["status"])


def command_profile(args: argparse.Namespace) -> int:
    try:
        context = prepare_run_context(args)
        trials, warmup = parse_profile_trials(args.trials, args.warmup)
    except (CommandError, DiscoveryError):
        print_json_result(error_result())
        return 2

    if args.list_tests:
        print_json_result(list_tests_result(context.cases))
        return 0

    result = aggregate_profile_results(context, trials, warmup, args.memory)
    print_json_result(result)
    return status_exit_code(result["status"])


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
    test.add_argument("--tol")
    test.add_argument("--list-tests", action="store_true")
    test.add_argument("--run")
    test.add_argument("--timeout-ms")
    test.add_argument("--total-timeout-ms")
    test.set_defaults(func=command_test)

    profile = subparsers.add_parser("profile")
    profile.add_argument("tests_dir")
    profile.add_argument("solution_path")
    profile.add_argument("--lang", required=True)
    profile.add_argument("-n", dest="trials", default="1")
    profile.add_argument("--warmup", default="0")
    profile.add_argument("--memory", action="store_true")
    profile.add_argument("--tol")
    profile.add_argument("--list-tests", action="store_true")
    profile.add_argument("--run")
    profile.add_argument("--timeout-ms")
    profile.add_argument("--total-timeout-ms")
    profile.set_defaults(func=command_profile)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
