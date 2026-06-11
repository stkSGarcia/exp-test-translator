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
MATH_ISCLOSE_REL_TOL = 1e-09
MATH_ISCLOSE_ABS_TOL = 0.0
DEFAULT_CASE_TIMEOUT_SECONDS = 10.0
DEFAULT_COMPILE_TIMEOUT_SECONDS = 20.0
LOOP_ITERATION_LIMIT = 10000
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
    """Raised when test sources cannot be interpreted as the supported subset."""


class MetadataError(Exception):
    """Raised when generated tester metadata is absent or invalid."""


class LoopEvaluationError(Exception):
    """Raised when a loop cannot be evaluated as a supported parameterization."""


def result_expr() -> dict[str, Any]:
    return {"op": "result"}


@dataclass(frozen=True)
class PendingTest:
    line: int
    source_path: str
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


@dataclass(frozen=True)
class TestCase:
    id: str
    line: int
    source_path: str
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


@dataclass(frozen=True)
class TestExecutionOptions:
    list_tests: bool = False
    run_id: str | None = None
    timeout_seconds: float | None = None
    total_timeout_seconds: float | None = None


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


def parse_timeout_ms(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise DiscoveryError("invalid timeout") from exc
    if value < 1:
        raise DiscoveryError("invalid timeout")
    return value / 1000.0


def render_tester(lang: str, entrypoint: str) -> str:
    metadata = {
        "version": METADATA_VERSION,
        "entrypoint": entrypoint,
        "lang": lang,
    }
    prefix = "#" if lang == "python" else "//"
    scaffold = {
        "cpp": "// C++ target harness is compiled per test case by babel_code_goat.py.\n",
        "rust": "// Rust target harness is compiled per test case by babel_code_goat.py.\n",
    }.get(lang, "")
    return (
        f"{prefix} Generated by babel_code_goat.py.\n"
        f"{prefix} {METADATA_MARKER} {json_line(metadata)}\n"
        f"{scaffold}"
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
    def __init__(
        self,
        entrypoint: str,
        source_lines: list[str],
        source_path: str = "tests.py",
    ) -> None:
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
            mutation = self.mutation_call_from_stmt(stmt)
            if mutation is not None:
                args, mutation_refs = mutation
                assert_index = index + 1
                mutation_asserts: list[ast.Assert] = []
                while assert_index < len(body) and isinstance(body[assert_index], ast.Assert):
                    mutation_asserts.append(body[assert_index])
                    assert_index += 1
                if not mutation_asserts:
                    raise DiscoveryError(
                        f"mutation call requires immediate assert at line {stmt.lineno}"
                    )
                for assertion in mutation_asserts:
                    self.visit_mutation_assert(assertion, args, mutation_refs)
                index = assert_index
                continue

            if isinstance(stmt, ast.FunctionDef):
                self.visit_function(stmt)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                pass
            elif isinstance(stmt, ast.Assert):
                self.visit_assert(stmt)
            elif isinstance(stmt, ast.Try):
                self.visit_raise_expectation(stmt)
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

    def entrypoint_call_node(self, node: ast.AST) -> ast.Call | None:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == self.entrypoint
        ):
            return node
        return None

    def mutation_call_from_stmt(
        self,
        stmt: ast.stmt,
    ) -> tuple[list[Any], dict[str, dict[str, Any]]] | None:
        call: ast.Call | None = None
        assigned_name: str | None = None
        if isinstance(stmt, ast.Expr):
            call = self.entrypoint_call_node(stmt.value)
        elif isinstance(stmt, ast.Assign):
            call = self.entrypoint_call_node(stmt.value)
            if call is None:
                return None
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                raise DiscoveryError(f"mutation assignment target is unsupported at line {stmt.lineno}")
            assigned_name = stmt.targets[0].id
            if assigned_name == self.entrypoint:
                raise DiscoveryError(f"assignment to entrypoint is unsupported at line {stmt.lineno}")
        if call is None:
            return None

        args = self.parse_entrypoint_call(call, stmt.lineno)
        mutation_refs = self.direct_mutation_refs_for_call(call, stmt.lineno)
        if assigned_name is not None:
            mutation_refs[assigned_name] = result_expr()
        return args, mutation_refs

    def direct_mutation_refs_for_call(
        self,
        call: ast.Call,
        line_no: int,
    ) -> dict[str, dict[str, Any]]:
        refs: dict[str, dict[str, Any]] = {}
        arg_index = 0
        for arg in call.args:
            if isinstance(arg, ast.Starred):
                values = as_iterable_items(
                    self.parse_value(arg.value),
                    line_no,
                    "starred argument",
                )
                arg_index += len(values)
                continue
            if isinstance(arg, ast.Name) and arg.id in self.env and arg.id not in refs:
                refs[arg.id] = {"op": "arg", "index": arg_index}
            arg_index += 1
        return refs

    def parse_mutation_expression(
        self,
        node: ast.AST,
        mutation_refs: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], set[str]]:
        used_refs: set[str] = set()
        expr = self.parse_expression(
            node,
            [],
            mutation_refs=mutation_refs,
            mutation_refs_used=used_refs,
        )
        return expr, used_refs

    def require_mutation_ref(
        self,
        used_refs: set[str],
        line_no: int,
    ) -> None:
        if not used_refs:
            raise DiscoveryError(f"mutation assert must reference mutated value at line {line_no}")

    def visit_mutation_assert(
        self,
        stmt: ast.Assert,
        args: list[Any],
        mutation_refs: dict[str, dict[str, Any]],
    ) -> None:
        if stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {stmt.lineno}")
        if self.count_entrypoint_calls(stmt.test):
            raise DiscoveryError(
                f"mutation assert must not call {self.entrypoint} at line {stmt.lineno}"
            )

        test = stmt.test
        if isinstance(test, ast.Compare):
            self.visit_mutation_comparison_assert(stmt, args, mutation_refs, test)
            return

        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            actual_expr, used_refs = self.parse_mutation_expression(
                test.operand,
                mutation_refs,
            )
            self.require_mutation_ref(used_refs, stmt.lineno)
            self.add_test(stmt.lineno, "not", args, actual_expr=actual_expr)
            return

        actual_expr, used_refs = self.parse_mutation_expression(test, mutation_refs)
        self.require_mutation_ref(used_refs, stmt.lineno)
        self.add_test(stmt.lineno, "truthy", args, actual_expr=actual_expr)

    def visit_mutation_comparison_assert(
        self,
        stmt: ast.Assert,
        args: list[Any],
        mutation_refs: dict[str, dict[str, Any]],
        test: ast.Compare,
    ) -> None:
        if len(test.ops) != 1 or len(test.comparators) != 1:
            raise DiscoveryError(f"unsupported comparison at line {stmt.lineno}")
        operator = test.ops[0]
        if type(operator) not in COMPARE_OPERATORS:
            raise DiscoveryError(f"unsupported comparison operator at line {stmt.lineno}")

        left_expr, left_refs = self.parse_mutation_expression(test.left, mutation_refs)
        right = test.comparators[0]
        right_expr, right_refs = self.parse_mutation_expression(right, mutation_refs)
        self.require_mutation_ref(left_refs | right_refs, stmt.lineno)

        if isinstance(operator, (ast.Eq, ast.NotEq)) and bool(left_refs) != bool(right_refs):
            if left_refs:
                actual_expr = left_expr
                expected = self.parse_value(right)
            else:
                actual_expr = right_expr
                expected = self.parse_value(test.left)
            self.add_test(
                stmt.lineno,
                "eq" if isinstance(operator, ast.Eq) else "ne",
                args,
                expected,
                actual_expr=actual_expr,
            )
            return

        self.add_test(
            stmt.lineno,
            "truthy",
            args,
            actual_expr={
                "op": "compare",
                "operator": COMPARE_OPERATORS[type(operator)],
                "left": left_expr,
                "right": right_expr,
            },
        )

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
        mutation_refs: dict[str, dict[str, Any]] | None = None,
        mutation_refs_used: set[str] | None = None,
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return {"op": "value", "value": node.value}
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            if mutation_refs is not None and node.id in mutation_refs:
                if mutation_refs_used is not None:
                    mutation_refs_used.add(node.id)
                return dict(mutation_refs[node.id])
            return {"op": "value", "value": self.resolve_name(node.id, line_no)}
        if isinstance(node, ast.List):
            return {
                "op": "list",
                "items": [
                    self.parse_expression(
                        item,
                        entrypoint_args,
                        mutation_refs,
                        mutation_refs_used,
                    )
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Tuple):
            return {
                "op": "tuple",
                "items": [
                    self.parse_expression(
                        item,
                        entrypoint_args,
                        mutation_refs,
                        mutation_refs_used,
                    )
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Set):
            return {
                "op": "set",
                "items": [
                    self.parse_expression(
                        item,
                        entrypoint_args,
                        mutation_refs,
                        mutation_refs_used,
                    )
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
                        self.parse_expression(
                            key_node,
                            entrypoint_args,
                            mutation_refs,
                            mutation_refs_used,
                        ),
                        self.parse_expression(
                            value_node,
                            entrypoint_args,
                            mutation_refs,
                            mutation_refs_used,
                        ),
                    ]
                )
            return {"op": "dict", "entries": entries}
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return {
                "op": "unary",
                "operator": UNARY_OPERATORS[type(node.op)],
                "operand": self.parse_expression(
                    node.operand,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
            }
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return {
                "op": "binary",
                "operator": BINARY_OPERATORS[type(node.op)],
                "left": self.parse_expression(
                    node.left,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
                "right": self.parse_expression(
                    node.right,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
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
                "left": self.parse_expression(
                    node.left,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
                "right": self.parse_expression(
                    node.comparators[0],
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
            }
        if isinstance(node, ast.Subscript):
            return self.parse_subscript_expression(
                node,
                entrypoint_args,
                mutation_refs,
                mutation_refs_used,
            )
        if isinstance(node, ast.Call):
            return self.parse_call_expression(
                node,
                entrypoint_args,
                mutation_refs,
                mutation_refs_used,
            )
        raise DiscoveryError(f"unsupported expression at line {line_no}")

    def parse_call_expression(
        self,
        node: ast.Call,
        entrypoint_args: list[list[Any]],
        mutation_refs: dict[str, dict[str, Any]] | None = None,
        mutation_refs_used: set[str] | None = None,
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
                    self.parse_expression(
                        arg,
                        entrypoint_args,
                        mutation_refs,
                        mutation_refs_used,
                    )
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
                "receiver": self.parse_expression(
                    node.func.value,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                ),
                "args": [
                    self.parse_expression(
                        arg,
                        entrypoint_args,
                        mutation_refs,
                        mutation_refs_used,
                    )
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
        mutation_refs: dict[str, dict[str, Any]] | None = None,
        mutation_refs_used: set[str] | None = None,
    ) -> dict[str, Any]:
        value = self.parse_expression(
            node.value,
            entrypoint_args,
            mutation_refs,
            mutation_refs_used,
        )
        if isinstance(node.slice, ast.Slice):
            return {
                "op": "slice",
                "value": value,
                "lower": self.parse_expression(
                    node.slice.lower,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                )
                if node.slice.lower is not None
                else None,
                "upper": self.parse_expression(
                    node.slice.upper,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                )
                if node.slice.upper is not None
                else None,
                "step": self.parse_expression(
                    node.slice.step,
                    entrypoint_args,
                    mutation_refs,
                    mutation_refs_used,
                )
                if node.slice.step is not None
                else None,
            }
        return {
            "op": "subscript",
            "value": value,
            "index": self.parse_expression(
                node.slice,
                entrypoint_args,
                mutation_refs,
                mutation_refs_used,
            ),
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
    ) -> None:
        expectations = self.expectations_for(line_no)
        self.pending.append(
            PendingTest(
                line=line_no,
                source_path=self.source_path,
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
            )
        )

    def add_loop_test(self, line_no: int, passed: bool) -> None:
        self.pending.append(
            PendingTest(
                line=line_no,
                source_path=self.source_path,
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
    bases = [
        test_id_base(test.source_path, test.line, test.iteration_path)
        for test in pending
    ]
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
                line=test.line,
                source_path=test.source_path,
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
            )
        )
    return cases


def test_id_base(source_path: str, line_no: int, iteration_path: tuple[int, ...]) -> str:
    suffix = "".join(f":{index}" for index in iteration_path)
    return f"{source_path}:{line_no}{suffix}"


def relative_source_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_generated_tester_file(path: Path) -> bool:
    return path.name in set(SUPPORTED_LANGS.values())


def is_test_like_non_python(path: Path) -> bool:
    if path.suffix == ".py" or is_generated_tester_file(path):
        return False
    stem = path.stem
    return (
        stem.startswith("test")
        or stem.endswith("_test")
        or stem == "tests"
        or stem.endswith("_tests")
    )


def discover_source_files(tests_dir: Path | str) -> list[tuple[str, Path]]:
    root = Path(tests_dir)
    if not root.is_dir():
        raise DiscoveryError("tests_dir is required")

    sources: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_test_like_non_python(path):
            raise DiscoveryError(f"non-Python test-like file is unsupported: {relative_source_path(root, path)}")
        if path.suffix == ".py":
            sources.append((relative_source_path(root, path), path))
    return sorted(sources, key=lambda item: item[0])


def discover_tests(tests_dir: Path | str, entrypoint: str) -> list[TestCase]:
    cases: list[TestCase] = []
    for source_path, path in discover_source_files(tests_dir):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=source_path)
        except (OSError, SyntaxError) as exc:
            raise DiscoveryError(f"cannot read or parse {source_path}") from exc
        cases.extend(
            TestDiscoverer(entrypoint, source.splitlines(), source_path).discover(tree)
        )
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
    if op == "result":
        return {"op": "result"}
    if op == "arg":
        return {"op": "arg", "index": expr["index"]}
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
    }


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
    if op == "result":
        return {"op": "result"}
    if op == "arg":
        return {"op": "arg", "index": expr["index"]}
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


def _eval_expr(expr, result, args):
    op = expr["op"]
    if op == "result":
        return result
    if op == "arg":
        return args[expr["index"]]
    if op == "value":
        return expr["value"]
    if op == "list":
        return [_eval_expr(item, result, args) for item in expr["items"]]
    if op == "tuple":
        return tuple(_eval_expr(item, result, args) for item in expr["items"])
    if op == "set":
        return set(_eval_expr(item, result, args) for item in expr["items"])
    if op == "dict":
        return {_eval_expr(key, result, args): _eval_expr(value, result, args) for key, value in expr["entries"]}
    if op == "unary":
        operand = _eval_expr(expr["operand"], result, args)
        if expr["operator"] == "uadd":
            return +operand
        if expr["operator"] == "usub":
            return -operand
        if expr["operator"] == "not":
            return not operand
    if op == "binary":
        left = _eval_expr(expr["left"], result, args)
        right = _eval_expr(expr["right"], result, args)
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
        left = _eval_expr(expr["left"], result, args)
        right = _eval_expr(expr["right"], result, args)
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
        return _eval_call(expr["name"], [_eval_expr(arg, result, args) for arg in expr["args"]])
    if op == "method":
        receiver = _eval_expr(expr["receiver"], result, args)
        method_args = [_eval_expr(arg, result, args) for arg in expr["args"]]
        return _eval_method(expr["name"], receiver, method_args)
    if op == "subscript":
        return _eval_expr(expr["value"], result, args)[_eval_expr(expr["index"], result, args)]
    if op == "slice":
        value = _eval_expr(expr["value"], result, args)
        lower = _eval_expr(expr["lower"], result, args) if expr["lower"] is not None else None
        upper = _eval_expr(expr["upper"], result, args) if expr["upper"] is not None else None
        step = _eval_expr(expr["step"], result, args) if expr["step"] is not None else None
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


def _matches(case, value, raised):
    kind = case["kind"]
    if kind == "raises":
        return _exception_matches(case, raised)
    if raised is not None:
        return False
    try:
        actual = _eval_expr(case["actual_expr"], value, case["args"])
    except Exception:
        return False
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
    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            value = function(*case["args"])
            if inspect.isawaitable(value):
                value = asyncio.run(value)
    except BaseException as exc:
        raised = exc

    passed = _matches(case, value, raised)
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
  if (expr.op === "result") {
    return {op: "result"};
  }
  if (expr.op === "arg") {
    return {op: "arg", index: expr.index};
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

function evalExpr(expr, result, args) {
  if (expr.op === "result") {
    return result;
  }
  if (expr.op === "arg") {
    return args[expr.index];
  }
  if (expr.op === "value") {
    return expr.value;
  }
  if (expr.op === "list" || expr.op === "tuple") {
    return expr.items.map((item) => evalExpr(item, result, args));
  }
  if (expr.op === "set") {
    return new Set(expr.items.map((item) => evalExpr(item, result, args)));
  }
  if (expr.op === "dict") {
    const entries = expr.entries.map(([key, value]) => [
      evalExpr(key, result, args),
      evalExpr(value, result, args),
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
    const operand = evalExpr(expr.operand, result, args);
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
      evalExpr(expr.left, result, args),
      evalExpr(expr.right, result, args),
    );
  }
  if (expr.op === "compare") {
    const left = evalExpr(expr.left, result, args);
    const right = evalExpr(expr.right, result, args);
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
    return callValue(expr.name, expr.args.map((arg) => evalExpr(arg, result, args)));
  }
  if (expr.op === "method") {
    return methodValue(
      expr.name,
      evalExpr(expr.receiver, result, args),
      expr.args.map((arg) => evalExpr(arg, result, args)),
    );
  }
  if (expr.op === "subscript") {
    return subscriptValue(evalExpr(expr.value, result, args), evalExpr(expr.index, result, args));
  }
  if (expr.op === "slice") {
    return sliceValue(
      evalExpr(expr.value, result, args),
      expr.lower === null ? null : evalExpr(expr.lower, result, args),
      expr.upper === null ? null : evalExpr(expr.upper, result, args),
      expr.step === null ? null : evalExpr(expr.step, result, args),
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
    actual = evalExpr(testCase.actual_expr, callResult.value, testCase.args);
  } catch (_) {
    return false;
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
    const callResult = await withCaptureAsync(() => callable(...testCase.args));
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


@dataclass(frozen=True)
class TargetType:
    kind: str
    args: tuple["TargetType", ...] = ()


NULL_TYPE = TargetType("null")
BOOL_TYPE = TargetType("bool")
INT_TYPE = TargetType("int")
FLOAT_TYPE = TargetType("float")
STRING_TYPE = TargetType("string")


def vector_type(item_type: TargetType) -> TargetType:
    return TargetType("vector", (item_type,))


def set_type(item_type: TargetType) -> TargetType:
    return TargetType("set", (item_type,))


def map_type(key_type: TargetType, value_type: TargetType) -> TargetType:
    return TargetType("map", (key_type, value_type))


def optional_type(item_type: TargetType) -> TargetType:
    return TargetType("optional", (item_type,))


def is_numeric_target_type(type_: TargetType) -> bool:
    return type_.kind in {"int", "float", "bool"}


def unified_target_type(types: list[TargetType]) -> TargetType:
    if not types:
        return INT_TYPE
    non_null = [type_ for type_ in types if type_.kind != "null"]
    if len(non_null) != len(types):
        inner = unified_target_type(non_null) if non_null else INT_TYPE
        return optional_type(inner)
    kinds = {type_.kind for type_ in types}
    if kinds <= {"bool"}:
        return BOOL_TYPE
    if kinds <= {"int", "bool"}:
        return INT_TYPE
    if kinds <= {"int", "float", "bool"}:
        return FLOAT_TYPE
    if len(kinds) == 1:
        kind = types[0].kind
        if kind in {"string", "int", "float", "bool"}:
            return types[0]
        if kind == "vector":
            return vector_type(unified_target_type([type_.args[0] for type_ in types]))
        if kind == "set":
            return set_type(unified_target_type([type_.args[0] for type_ in types]))
        if kind == "map":
            return map_type(
                unified_target_type([type_.args[0] for type_ in types]),
                unified_target_type([type_.args[1] for type_ in types]),
            )
        if kind == "optional":
            return optional_type(unified_target_type([type_.args[0] for type_ in types]))
    return types[0]


def target_type_for_value(value: Any) -> TargetType:
    if value is None:
        return NULL_TYPE
    if isinstance(value, bool):
        return BOOL_TYPE
    if isinstance(value, int) and not isinstance(value, bool):
        return INT_TYPE
    if isinstance(value, (float, Decimal)) and not isinstance(value, bool):
        return FLOAT_TYPE
    if isinstance(value, str):
        return STRING_TYPE
    if isinstance(value, (list, tuple, deque)):
        return vector_type(unified_target_type([target_type_for_value(item) for item in value]))
    if isinstance(value, (set, frozenset)):
        return set_type(unified_target_type([target_type_for_value(item) for item in value]))
    if isinstance(value, (dict, defaultdict)):
        return map_type(
            unified_target_type([target_type_for_value(key) for key in value.keys()]),
            unified_target_type([target_type_for_value(item) for item in value.values()]),
        )
    if isinstance(value, Counter):
        return map_type(
            unified_target_type([target_type_for_value(key) for key in value.keys()]),
            INT_TYPE,
        )
    return STRING_TYPE


def target_type_contains_deque(value: Any) -> bool:
    if isinstance(value, deque):
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(target_type_contains_deque(item) for item in value)
    if isinstance(value, (dict, defaultdict, Counter)):
        return any(
            target_type_contains_deque(key) or target_type_contains_deque(item)
            for key, item in value.items()
        )
    return False


def expr_contains_deque(expr: dict[str, Any]) -> bool:
    op = expr["op"]
    if op == "value":
        return target_type_contains_deque(expr["value"])
    if op in {"result", "arg"}:
        return False
    if op in {"list", "tuple", "set"}:
        return any(expr_contains_deque(item) for item in expr["items"])
    if op == "dict":
        return any(
            expr_contains_deque(key) or expr_contains_deque(value)
            for key, value in expr["entries"]
        )
    if op == "unary":
        return expr_contains_deque(expr["operand"])
    if op in {"binary", "compare"}:
        return expr_contains_deque(expr["left"]) or expr_contains_deque(expr["right"])
    if op == "call":
        return any(expr_contains_deque(arg) for arg in expr["args"])
    if op == "method":
        return expr_contains_deque(expr["receiver"]) or any(
            expr_contains_deque(arg) for arg in expr["args"]
        )
    if op == "subscript":
        return expr_contains_deque(expr["value"]) or expr_contains_deque(expr["index"])
    if op == "slice":
        return (
            expr_contains_deque(expr["value"])
            or (expr["lower"] is not None and expr_contains_deque(expr["lower"]))
            or (expr["upper"] is not None and expr_contains_deque(expr["upper"]))
            or (expr["step"] is not None and expr_contains_deque(expr["step"]))
        )
    return False


def case_contains_deque(case: TestCase) -> bool:
    return (
        any(target_type_contains_deque(arg) for arg in case.args)
        or target_type_contains_deque(case.expected)
        or target_type_contains_deque(case.abs_tol)
        or target_type_contains_deque(case.rel_tol)
        or expr_contains_deque(case.actual_expr)
    )


def expr_uses_result(expr: dict[str, Any]) -> bool:
    op = expr["op"]
    if op == "result":
        return True
    if op in {"value", "arg"}:
        return False
    if op in {"list", "tuple", "set"}:
        return any(expr_uses_result(item) for item in expr["items"])
    if op == "dict":
        return any(
            expr_uses_result(key) or expr_uses_result(value)
            for key, value in expr["entries"]
        )
    if op == "unary":
        return expr_uses_result(expr["operand"])
    if op in {"binary", "compare"}:
        return expr_uses_result(expr["left"]) or expr_uses_result(expr["right"])
    if op == "call":
        return any(expr_uses_result(arg) for arg in expr["args"])
    if op == "method":
        return expr_uses_result(expr["receiver"]) or any(
            expr_uses_result(arg) for arg in expr["args"]
        )
    if op == "subscript":
        return expr_uses_result(expr["value"]) or expr_uses_result(expr["index"])
    if op == "slice":
        return (
            expr_uses_result(expr["value"])
            or (expr["lower"] is not None and expr_uses_result(expr["lower"]))
            or (expr["upper"] is not None and expr_uses_result(expr["upper"]))
            or (expr["step"] is not None and expr_uses_result(expr["step"]))
        )
    return False


def expr_arg_indices(expr: dict[str, Any]) -> set[int]:
    op = expr["op"]
    if op == "arg":
        return {int(expr["index"])}
    if op in {"value", "result"}:
        return set()
    if op in {"list", "tuple", "set"}:
        return set().union(*(expr_arg_indices(item) for item in expr["items"]))
    if op == "dict":
        indexes: set[int] = set()
        for key, value in expr["entries"]:
            indexes.update(expr_arg_indices(key))
            indexes.update(expr_arg_indices(value))
        return indexes
    if op == "unary":
        return expr_arg_indices(expr["operand"])
    if op in {"binary", "compare"}:
        return expr_arg_indices(expr["left"]) | expr_arg_indices(expr["right"])
    if op == "call":
        return set().union(*(expr_arg_indices(arg) for arg in expr["args"]))
    if op == "method":
        indexes = expr_arg_indices(expr["receiver"])
        for arg in expr["args"]:
            indexes.update(expr_arg_indices(arg))
        return indexes
    if op == "subscript":
        return expr_arg_indices(expr["value"]) | expr_arg_indices(expr["index"])
    if op == "slice":
        indexes = expr_arg_indices(expr["value"])
        for key in ("lower", "upper", "step"):
            if expr[key] is not None:
                indexes.update(expr_arg_indices(expr[key]))
        return indexes
    return set()


def first_available_tool(names: list[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path is not None:
            return path
    return None


def run_compiled_source(
    source: str,
    suffix: str,
    compiler_names: list[str],
    command_builder: Any,
    timeout_seconds: float | None = None,
) -> bool:
    compiler = first_available_tool(compiler_names)
    if compiler is None:
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / f"case{suffix}"
            binary_path = root / "case"
            source_path.write_text(source, encoding="utf-8")
            compile_proc = subprocess.run(
                command_builder(compiler, source_path, binary_path),
                text=True,
                capture_output=True,
                timeout=timeout_seconds or DEFAULT_COMPILE_TIMEOUT_SECONDS,
            )
            if compile_proc.returncode != 0:
                return False
            run_proc = subprocess.run(
                [str(binary_path)],
                text=True,
                capture_output=True,
                timeout=timeout_seconds or DEFAULT_CASE_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(run_proc)


CPP_CASE_HELPERS = r'''
#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <future>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace bcg {

template <typename T> struct is_optional : std::false_type {};
template <typename T> struct is_optional<std::optional<T>> : std::true_type {};
template <typename T> constexpr bool is_optional_v = is_optional<std::decay_t<T>>::value;

template <typename T> struct is_nullopt : std::false_type {};
template <> struct is_nullopt<std::nullopt_t> : std::true_type {};
template <typename T> constexpr bool is_nullopt_v = is_nullopt<std::decay_t<T>>::value;

template <typename T> struct is_future : std::false_type {};
template <typename T> struct is_future<std::future<T>> : std::true_type {};
template <typename T> struct is_future<std::shared_future<T>> : std::true_type {};
template <typename T> constexpr bool is_future_v = is_future<std::decay_t<T>>::value;

template <typename T> struct future_result {};
template <typename T> struct future_result<std::future<T>> { using type = T; };
template <typename T> struct future_result<std::shared_future<T>> { using type = T; };
template <typename T> using future_result_t = typename future_result<std::decay_t<T>>::type;

template <typename T> struct is_vector : std::false_type {};
template <typename T, typename Alloc> struct is_vector<std::vector<T, Alloc>> : std::true_type {};
template <typename T> constexpr bool is_vector_v = is_vector<std::decay_t<T>>::value;

template <typename T> struct is_set : std::false_type {};
template <typename T, typename C, typename A> struct is_set<std::set<T, C, A>> : std::true_type {};
template <typename T, typename H, typename E, typename A> struct is_set<std::unordered_set<T, H, E, A>> : std::true_type {};
template <typename T> constexpr bool is_set_v = is_set<std::decay_t<T>>::value;

template <typename T> struct is_map : std::false_type {};
template <typename K, typename V, typename C, typename A> struct is_map<std::map<K, V, C, A>> : std::true_type {};
template <typename K, typename V, typename H, typename E, typename A> struct is_map<std::unordered_map<K, V, H, E, A>> : std::true_type {};
template <typename T> constexpr bool is_map_v = is_map<std::decay_t<T>>::value;

template <typename T>
constexpr bool is_numeric_v = std::is_arithmetic_v<std::decay_t<T>> && !std::is_same_v<std::decay_t<T>, bool>;

template <typename F>
decltype(auto) invoke_to_completion(F&& func) {
    using Result = decltype(func());
    if constexpr (std::is_void_v<Result>) {
        func();
    } else if constexpr (is_future_v<Result>) {
        auto future = func();
        if constexpr (std::is_void_v<future_result_t<Result>>) {
            future.get();
        } else {
            return future.get();
        }
    } else {
        return func();
    }
}

inline bool numeric_close(long double left, long double right, std::optional<long double> abs_tol, std::optional<long double> rel_tol) {
    long double absolute = abs_tol.value_or(0.0L);
    long double relative = rel_tol.value_or(0.0L);
    long double diff = std::fabs(left - right);
    long double limit = std::max(absolute, relative * std::max(std::fabs(left), std::fabs(right)));
    return diff <= limit;
}

template <typename L, typename R>
bool deep_equal(const L& left, const R& right, std::optional<long double> abs_tol = std::nullopt, std::optional<long double> rel_tol = std::nullopt) {
    if constexpr (is_nullopt_v<L> || is_nullopt_v<R>) {
        if constexpr (is_optional_v<L> && is_nullopt_v<R>) {
            return !left.has_value();
        } else if constexpr (is_nullopt_v<L> && is_optional_v<R>) {
            return !right.has_value();
        } else if constexpr (is_nullopt_v<L> && is_nullopt_v<R>) {
            return true;
        } else {
            return false;
        }
    } else if constexpr (is_optional_v<L> || is_optional_v<R>) {
        if constexpr (is_optional_v<L> && is_optional_v<R>) {
            if (left.has_value() != right.has_value()) {
                return false;
            }
            return !left.has_value() || deep_equal(*left, *right, abs_tol, rel_tol);
        } else if constexpr (is_optional_v<L>) {
            return left.has_value() && deep_equal(*left, right, abs_tol, rel_tol);
        } else {
            return right.has_value() && deep_equal(left, *right, abs_tol, rel_tol);
        }
    } else if constexpr (is_vector_v<L> || is_vector_v<R>) {
        if constexpr (!(is_vector_v<L> && is_vector_v<R>)) {
            return false;
        } else {
            if (left.size() != right.size()) {
                return false;
            }
            for (std::size_t index = 0; index < left.size(); ++index) {
                if (!deep_equal(left[index], right[index], abs_tol, rel_tol)) {
                    return false;
                }
            }
            return true;
        }
    } else if constexpr (is_set_v<L> || is_set_v<R>) {
        if constexpr (!(is_set_v<L> && is_set_v<R>)) {
            return false;
        } else {
            if (left.size() != right.size()) {
                return false;
            }
            std::vector<bool> matched(right.size(), false);
            for (const auto& left_item : left) {
                std::size_t index = 0;
                bool found = false;
                for (const auto& right_item : right) {
                    if (!matched[index] && deep_equal(left_item, right_item, abs_tol, rel_tol)) {
                        matched[index] = true;
                        found = true;
                        break;
                    }
                    ++index;
                }
                if (!found) {
                    return false;
                }
            }
            return true;
        }
    } else if constexpr (is_map_v<L> || is_map_v<R>) {
        if constexpr (!(is_map_v<L> && is_map_v<R>)) {
            return false;
        } else {
            if (left.size() != right.size()) {
                return false;
            }
            std::vector<bool> matched(right.size(), false);
            for (const auto& left_entry : left) {
                std::size_t index = 0;
                bool found = false;
                for (const auto& right_entry : right) {
                    if (!matched[index] &&
                        deep_equal(left_entry.first, right_entry.first, abs_tol, rel_tol) &&
                        deep_equal(left_entry.second, right_entry.second, abs_tol, rel_tol)) {
                        matched[index] = true;
                        found = true;
                        break;
                    }
                    ++index;
                }
                if (!found) {
                    return false;
                }
            }
            return true;
        }
    } else if constexpr (is_numeric_v<L> && is_numeric_v<R>) {
        if (abs_tol.has_value() || rel_tol.has_value() || std::is_floating_point_v<std::decay_t<L>> || std::is_floating_point_v<std::decay_t<R>>) {
            return numeric_close(static_cast<long double>(left), static_cast<long double>(right), abs_tol, rel_tol);
        }
        return left == right;
    } else {
        return left == right;
    }
}

template <typename T>
bool truthy(const T& value) {
    if constexpr (is_nullopt_v<T>) {
        return false;
    } else if constexpr (is_optional_v<T>) {
        return value.has_value() && truthy(*value);
    } else if constexpr (std::is_same_v<std::decay_t<T>, bool>) {
        return value;
    } else if constexpr (is_numeric_v<T>) {
        return value != 0;
    } else if constexpr (std::is_same_v<std::decay_t<T>, std::string> || is_vector_v<T> || is_set_v<T> || is_map_v<T>) {
        return !value.empty();
    } else {
        return true;
    }
}

template <typename Container, typename Item>
bool contains(const Container& container, const Item& item) {
    if constexpr (std::is_same_v<std::decay_t<Container>, std::string>) {
        if constexpr (std::is_same_v<std::decay_t<Item>, std::string>) {
            return container.find(item) != std::string::npos;
        } else {
            return false;
        }
    } else if constexpr (is_vector_v<Container> || is_set_v<Container>) {
        for (const auto& value : container) {
            if (deep_equal(value, item)) {
                return true;
            }
        }
        return false;
    } else if constexpr (is_map_v<Container>) {
        for (const auto& entry : container) {
            if (deep_equal(entry.first, item)) {
                return true;
            }
        }
        return false;
    } else {
        return false;
    }
}

template <typename T>
auto sorted_copy(const T& value) {
    if constexpr (is_vector_v<T>) {
        auto result = value;
        std::sort(result.begin(), result.end());
        return result;
    } else if constexpr (is_set_v<T>) {
        return std::vector<typename std::decay_t<T>::value_type>(value.begin(), value.end());
    } else {
        auto result = value;
        std::sort(result.begin(), result.end());
        return result;
    }
}

template <typename T>
auto len(const T& value) {
    return static_cast<int>(value.size());
}

template <typename T>
auto abs_value(const T& value) {
    using std::abs;
    return abs(value);
}

inline std::string upper(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::toupper(ch)); });
    return value;
}

inline std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return value;
}

inline int find(std::string value, std::string needle) {
    auto pos = value.find(needle);
    return pos == std::string::npos ? -1 : static_cast<int>(pos);
}

template <typename T>
auto subscript(const T& value, int index) {
    int resolved = index < 0 ? static_cast<int>(value.size()) + index : index;
    return value.at(static_cast<std::size_t>(resolved));
}

template <typename K, typename V, typename C, typename A, typename I>
auto subscript(const std::map<K, V, C, A>& value, const I& index) {
    for (const auto& entry : value) {
        if (deep_equal(entry.first, index)) {
            return entry.second;
        }
    }
    throw std::out_of_range("missing map key");
}

inline bool message_matches(const std::string& mode, const std::string& pattern, const std::string& message) {
    if (mode.empty()) {
        return true;
    }
    if (mode == "contains") {
        return message.find(pattern) != std::string::npos;
    }
    if (mode == "regex") {
        try {
            return std::regex_search(message, std::regex(pattern));
        } catch (...) {
            return false;
        }
    }
    return false;
}

} // namespace bcg
'''


def cpp_string_literal(value: str) -> str:
    return json.dumps(value)


def cpp_include_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def cpp_type_name(type_: TargetType) -> str:
    if type_.kind == "null":
        return "std::nullopt_t"
    if type_.kind == "bool":
        return "bool"
    if type_.kind == "int":
        return "int"
    if type_.kind == "float":
        return "long double"
    if type_.kind == "string":
        return "std::string"
    if type_.kind == "vector":
        return f"std::vector<{cpp_type_name(type_.args[0])}>"
    if type_.kind == "set":
        return f"std::set<{cpp_type_name(type_.args[0])}>"
    if type_.kind == "map":
        return f"std::map<{cpp_type_name(type_.args[0])}, {cpp_type_name(type_.args[1])}>"
    if type_.kind == "optional":
        return f"std::optional<{cpp_type_name(type_.args[0])}>"
    return "int"


def cpp_numeric_literal(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"{str(value)}L"
    if isinstance(value, float):
        if math.isnan(value):
            return "std::numeric_limits<long double>::quiet_NaN()"
        if math.isinf(value):
            return "std::numeric_limits<long double>::infinity()" if value > 0 else "-std::numeric_limits<long double>::infinity()"
        return f"{repr(value)}L"
    return str(value)


def cpp_literal(value: Any, type_: TargetType | None = None) -> str:
    if type_ is None:
        type_ = target_type_for_value(value)
    if type_.kind == "optional":
        inner = type_.args[0]
        if value is None:
            return f"{cpp_type_name(type_)}{{}}"
        return f"{cpp_type_name(type_)}{{{cpp_literal(value, inner)}}}"
    if value is None:
        return "std::nullopt"
    if type_.kind == "bool" or isinstance(value, bool):
        return "true" if bool(value) else "false"
    if type_.kind == "int" and isinstance(value, int):
        return str(value)
    if type_.kind == "float" or isinstance(value, (float, Decimal)):
        return cpp_numeric_literal(value)
    if type_.kind == "string" or isinstance(value, str):
        return f"std::string({cpp_string_literal(str(value))})"
    if type_.kind == "vector" and isinstance(value, (list, tuple, deque)):
        item_type = type_.args[0]
        items = ", ".join(cpp_literal(item, item_type) for item in value)
        return f"{cpp_type_name(type_)}{{{items}}}"
    if type_.kind == "set" and isinstance(value, (set, frozenset)):
        item_type = type_.args[0]
        items = ", ".join(cpp_literal(item, item_type) for item in sorted(value, key=repr))
        return f"{cpp_type_name(type_)}{{{items}}}"
    if type_.kind == "map" and isinstance(value, (dict, defaultdict, Counter)):
        key_type, value_type = type_.args
        entries = []
        for key, item in sorted(value.items(), key=lambda entry: repr(entry[0])):
            entries.append(
                f"{{{cpp_literal(key, key_type)}, {cpp_literal(item, value_type)}}}"
            )
        return f"{cpp_type_name(type_)}{{{', '.join(entries)}}}"
    return cpp_literal(value, target_type_for_value(value))


def cpp_optional_tolerance(value: Any) -> str:
    if value is None:
        return "std::optional<long double>{}"
    return f"std::optional<long double>{{{cpp_numeric_literal(value)}}}"


def cpp_expr(expr: dict[str, Any]) -> str:
    op = expr["op"]
    if op == "value":
        return cpp_literal(expr["value"])
    if op == "result":
        return "__result"
    if op == "arg":
        return f"__arg{expr['index']}"
    if op in {"list", "tuple"}:
        if not expr["items"]:
            return "std::vector<int>{}"
        return f"std::vector{{{', '.join(cpp_expr(item) for item in expr['items'])}}}"
    if op == "set":
        if not expr["items"]:
            return "std::set<int>{}"
        return f"std::set{{{', '.join(cpp_expr(item) for item in expr['items'])}}}"
    if op == "dict":
        if not expr["entries"]:
            return "std::map<int, int>{}"
        pairs = ", ".join(
            f"std::pair{{{cpp_expr(key)}, {cpp_expr(value)}}}"
            for key, value in expr["entries"]
        )
        return f"std::map{{{pairs}}}"
    if op == "unary":
        operand = cpp_expr(expr["operand"])
        if expr["operator"] == "not":
            return f"(!bcg::truthy({operand}))"
        if expr["operator"] == "usub":
            return f"(-({operand}))"
        return f"(+({operand}))"
    if op == "binary":
        operators = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }
        if expr["operator"] == "pow":
            return f"std::pow({cpp_expr(expr['left'])}, {cpp_expr(expr['right'])})"
        operator = operators[expr["operator"]]
        return f"(({cpp_expr(expr['left'])}) {operator} ({cpp_expr(expr['right'])}))"
    if op == "compare":
        left = cpp_expr(expr["left"])
        right = cpp_expr(expr["right"])
        operator = expr["operator"]
        if operator == "eq":
            return f"bcg::deep_equal({left}, {right})"
        if operator == "ne":
            return f"(!bcg::deep_equal({left}, {right}))"
        if operator == "in":
            return f"bcg::contains({right}, {left})"
        if operator == "not_in":
            return f"(!bcg::contains({right}, {left}))"
        operators = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        return f"(({left}) {operators[operator]} ({right}))"
    if op == "call":
        args = [cpp_expr(arg) for arg in expr["args"]]
        name = expr["name"]
        if name == "abs":
            return f"bcg::abs_value({args[0]})"
        if name == "bool":
            return f"bcg::truthy({args[0]})"
        if name == "float":
            return f"static_cast<long double>({args[0]})"
        if name == "int":
            return f"static_cast<int>({args[0]})"
        if name == "len":
            return f"bcg::len({args[0]})"
        if name == "sorted":
            return f"bcg::sorted_copy({args[0]})"
        if name == "str":
            return f"std::to_string({args[0]})"
        if name in {"list", "tuple"}:
            return f"std::vector({args[0]}.begin(), {args[0]}.end())"
        if name in {"set", "frozenset"}:
            return f"std::set({args[0]}.begin(), {args[0]}.end())"
        if name == "sum":
            return f"std::accumulate({args[0]}.begin(), {args[0]}.end(), 0)"
        if name == "min":
            return f"(*std::min_element({args[0]}.begin(), {args[0]}.end()))"
        if name == "max":
            return f"(*std::max_element({args[0]}.begin(), {args[0]}.end()))"
    if op == "method":
        receiver = cpp_expr(expr["receiver"])
        args = [cpp_expr(arg) for arg in expr["args"]]
        name = expr["name"]
        if name == "upper":
            return f"bcg::upper({receiver})"
        if name == "lower":
            return f"bcg::lower({receiver})"
        if name == "find":
            return f"bcg::find({receiver}, {args[0]})"
        if name == "empty":
            return f"({receiver}).empty()"
        if name == "split":
            return f"std::vector<std::string>{{{receiver}}}"
        if name in {"strip", "lstrip", "rstrip"}:
            return receiver
        if name == "count":
            return f"0"
        if name == "startswith":
            return f"(({receiver}).rfind({args[0]}, 0) == 0)"
        if name == "endswith":
            return f"(({receiver}).size() >= ({args[0]}).size() && ({receiver}).compare(({receiver}).size() - ({args[0]}).size(), ({args[0]}).size(), {args[0]}) == 0)"
        if name == "replace":
            return receiver
        if name == "join":
            return receiver
    if op == "subscript":
        return f"bcg::subscript({cpp_expr(expr['value'])}, {cpp_expr(expr['index'])})"
    if op == "slice":
        return cpp_expr(expr["value"])
    return "false"


def cpp_case_assertion_code(case: TestCase, default_abs_tol: float | None) -> str:
    actual = cpp_expr(case.actual_expr)
    abs_tol = cpp_optional_tolerance(case.abs_tol if case.abs_tol is not None else default_abs_tol)
    rel_tol = cpp_optional_tolerance(case.rel_tol)
    if case.kind == "eq":
        expected = cpp_literal(case.expected)
        return f"__passed = bcg::deep_equal(({actual}), ({expected}), {abs_tol}, {rel_tol});"
    if case.kind == "ne":
        expected = cpp_literal(case.expected)
        return f"__passed = !bcg::deep_equal(({actual}), ({expected}), {abs_tol}, {rel_tol});"
    if case.kind == "isclose":
        expected = cpp_literal(case.expected)
        return f"__passed = bcg::numeric_close(static_cast<long double>({actual}), static_cast<long double>({expected}), {cpp_optional_tolerance(case.abs_tol)}, {cpp_optional_tolerance(case.rel_tol)});"
    if case.kind == "absdiff":
        expected = cpp_literal(case.expected)
        comparator = "<" if case.comparison == "abs_lt" else "<="
        return f"__passed = (std::fabs(static_cast<long double>({actual}) - static_cast<long double>({expected})) {comparator} {cpp_numeric_literal(case.abs_tol)});"
    if case.kind == "truthy":
        return f"__passed = bcg::truthy({actual});"
    if case.kind == "not":
        return f"__passed = !bcg::truthy({actual});"
    return "__passed = false;"


def build_cpp_case_source(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
) -> str:
    args = [
        f"auto __arg{index} = {cpp_literal(arg)};"
        for index, arg in enumerate(case.args)
    ]
    call_args = ", ".join(f"__arg{index}" for index in range(len(case.args)))
    exception_type = case.exception_type or ""
    message_match = case.message_match or ""
    message_pattern = case.message_pattern or ""
    expect_stdout = case.expect_stdout
    expect_stderr = case.expect_stderr
    checks = cpp_case_assertion_code(case, default_abs_tol)
    uses_result = expr_uses_result(case.actual_expr)
    invocation = f"bcg::invoke_to_completion([&]() -> decltype(auto) {{ return {entrypoint}({call_args}); }})"
    if case.kind == "raises":
        call_code = f"{invocation};"
        assertion = f'''
    if (__raised) {{
        bool __type_ok = {str(exception_type == "").lower()} || __exception_type == {cpp_string_literal(exception_type)} || {cpp_string_literal(exception_type)} == "Exception";
        __passed = __type_ok && bcg::message_matches({cpp_string_literal(message_match)}, {cpp_string_literal(message_pattern)}, __exception_message);
    }}
'''
    elif uses_result:
        call_code = f"auto __result = {invocation};\n        {checks}"
        assertion = ""
    else:
        call_code = f"{invocation};\n        {checks}"
        assertion = ""
    stdout_check = ""
    if expect_stdout is not None:
        stdout_check = f"\n    __passed = __passed && (__stdout_capture.str() == {cpp_string_literal(expect_stdout)});"
    stderr_check = ""
    if expect_stderr is not None:
        stderr_check = f"\n    __passed = __passed && (__stderr_capture.str() == {cpp_string_literal(expect_stderr)});"
    return f'''{CPP_CASE_HELPERS}
#include "{cpp_include_path(solution_path)}"

int main() {{
    {chr(10).join(args)}
    bool __passed = false;
    bool __raised = false;
    std::string __exception_type;
    std::string __exception_message;
    std::ostringstream __stdout_capture;
    std::ostringstream __stderr_capture;
    auto* __old_cout = std::cout.rdbuf(__stdout_capture.rdbuf());
    auto* __old_cerr = std::cerr.rdbuf(__stderr_capture.rdbuf());
    try {{
        {call_code}
    }} catch (const std::invalid_argument& __exc) {{
        __raised = true;
        __exception_type = "ValueError";
        __exception_message = __exc.what();
    }} catch (const std::runtime_error& __exc) {{
        __raised = true;
        __exception_type = "RuntimeError";
        __exception_message = __exc.what();
    }} catch (const std::exception& __exc) {{
        __raised = true;
        __exception_type = "Exception";
        __exception_message = __exc.what();
    }} catch (...) {{
        __raised = true;
        __exception_type = "Exception";
        __exception_message = "";
    }}
    std::cout.rdbuf(__old_cout);
    std::cerr.rdbuf(__old_cerr);
    {assertion}
    {stdout_check}{stderr_check}
    std::cout << "{{\\"passed\\":" << (__passed ? "true" : "false") << "}}\\n";
    return 0;
}}
'''


def run_cpp_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    source = build_cpp_case_source(solution_path, entrypoint, case, default_abs_tol)
    return run_compiled_source(
        source,
        ".cpp",
        ["g++", "clang++"],
        lambda compiler, source_path, binary_path: [
            compiler,
            "-std=c++17",
            "-O0",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        timeout_seconds,
    )


RUST_CASE_HELPERS = r'''
mod __bcg {
use std::any::Any;
use std::collections::{BTreeMap as StdBTreeMap, HashMap as StdHashMap, HashSet as StdHashSet};
use std::future::Future;
use std::hash::Hash;
use std::io::{Read, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::ptr;
use std::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};

#[cfg(unix)]
use std::os::unix::io::FromRawFd;

pub fn bcg_hash_map<K: Eq + Hash, V>(items: Vec<(K, V)>) -> StdHashMap<K, V> {
    items.into_iter().collect()
}

pub fn bcg_btree_map<K: Ord, V>(items: Vec<(K, V)>) -> StdBTreeMap<K, V> {
    items.into_iter().collect()
}

pub fn bcg_hash_set<T: Eq + Hash>(items: Vec<T>) -> StdHashSet<T> {
    items.into_iter().collect()
}

fn bcg_raw_waker_clone(_: *const ()) -> RawWaker {
    bcg_noop_raw_waker()
}

fn bcg_raw_waker_noop(_: *const ()) {}

static BCG_RAW_WAKER_VTABLE: RawWakerVTable = RawWakerVTable::new(
    bcg_raw_waker_clone,
    bcg_raw_waker_noop,
    bcg_raw_waker_noop,
    bcg_raw_waker_noop,
);

fn bcg_noop_raw_waker() -> RawWaker {
    RawWaker::new(ptr::null(), &BCG_RAW_WAKER_VTABLE)
}

pub fn bcg_block_on<F: Future>(future: F) -> F::Output {
    let waker = unsafe { Waker::from_raw(bcg_noop_raw_waker()) };
    let mut context = Context::from_waker(&waker);
    let mut future = Box::pin(future);
    loop {
        match Future::poll(Pin::as_mut(&mut future), &mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}

pub fn bcg_numeric_close(left: f64, right: f64, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
    let absolute = abs_tol.unwrap_or(0.0);
    let relative = rel_tol.unwrap_or(0.0);
    let diff = (left - right).abs();
    let limit = absolute.max(relative * left.abs().max(right.abs()));
    diff <= limit
}

pub trait BcgDeepEqual<Rhs = Self> {
    fn bcg_deep_equal(&self, rhs: &Rhs, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool;
}

macro_rules! impl_exact_deep_equal {
    ($($t:ty),* $(,)?) => {
        $(
            impl BcgDeepEqual<$t> for $t {
                fn bcg_deep_equal(&self, rhs: &$t, _abs_tol: Option<f64>, _rel_tol: Option<f64>) -> bool {
                    self == rhs
                }
            }
        )*
    };
}

impl_exact_deep_equal!(bool, i8, i16, i32, i64, isize, u8, u16, u32, u64, usize, String);

impl BcgDeepEqual<f64> for f64 {
    fn bcg_deep_equal(&self, rhs: &f64, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        if abs_tol.is_some() || rel_tol.is_some() {
            bcg_numeric_close(*self, *rhs, abs_tol, rel_tol)
        } else {
            self == rhs
        }
    }
}

impl BcgDeepEqual<String> for &str {
    fn bcg_deep_equal(&self, rhs: &String, _abs_tol: Option<f64>, _rel_tol: Option<f64>) -> bool {
        *self == rhs.as_str()
    }
}

impl BcgDeepEqual<&str> for String {
    fn bcg_deep_equal(&self, rhs: &&str, _abs_tol: Option<f64>, _rel_tol: Option<f64>) -> bool {
        self.as_str() == *rhs
    }
}

impl<T, U> BcgDeepEqual<Option<U>> for Option<T>
where
    T: BcgDeepEqual<U>,
{
    fn bcg_deep_equal(&self, rhs: &Option<U>, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        match (self, rhs) {
            (None, None) => true,
            (Some(left), Some(right)) => left.bcg_deep_equal(right, abs_tol, rel_tol),
            _ => false,
        }
    }
}

impl<T, U> BcgDeepEqual<Vec<U>> for Vec<T>
where
    T: BcgDeepEqual<U>,
{
    fn bcg_deep_equal(&self, rhs: &Vec<U>, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        self.len() == rhs.len()
            && self.iter().zip(rhs.iter()).all(|(left, right)| left.bcg_deep_equal(right, abs_tol, rel_tol))
    }
}

impl<T, U> BcgDeepEqual<StdHashSet<U>> for StdHashSet<T>
where
    T: BcgDeepEqual<U> + Eq + Hash,
    U: Eq + Hash,
{
    fn bcg_deep_equal(&self, rhs: &StdHashSet<U>, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        if self.len() != rhs.len() {
            return false;
        }
        let mut matched = vec![false; rhs.len()];
        for left in self.iter() {
            let mut found = false;
            for (index, right) in rhs.iter().enumerate() {
                if !matched[index] && left.bcg_deep_equal(right, abs_tol, rel_tol) {
                    matched[index] = true;
                    found = true;
                    break;
                }
            }
            if !found {
                return false;
            }
        }
        true
    }
}

impl<K, V, K2, V2> BcgDeepEqual<StdHashMap<K2, V2>> for StdHashMap<K, V>
where
    K: BcgDeepEqual<K2> + Eq + Hash,
    K2: Eq + Hash,
    V: BcgDeepEqual<V2>,
{
    fn bcg_deep_equal(&self, rhs: &StdHashMap<K2, V2>, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        if self.len() != rhs.len() {
            return false;
        }
        let mut matched = vec![false; rhs.len()];
        for (left_key, left_value) in self.iter() {
            let mut found = false;
            for (index, (right_key, right_value)) in rhs.iter().enumerate() {
                if !matched[index]
                    && left_key.bcg_deep_equal(right_key, abs_tol, rel_tol)
                    && left_value.bcg_deep_equal(right_value, abs_tol, rel_tol)
                {
                    matched[index] = true;
                    found = true;
                    break;
                }
            }
            if !found {
                return false;
            }
        }
        true
    }
}

impl<K, V, K2, V2> BcgDeepEqual<StdBTreeMap<K2, V2>> for StdBTreeMap<K, V>
where
    K: BcgDeepEqual<K2> + Ord,
    K2: Ord,
    V: BcgDeepEqual<V2>,
{
    fn bcg_deep_equal(&self, rhs: &StdBTreeMap<K2, V2>, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        if self.len() != rhs.len() {
            return false;
        }
        let mut matched = vec![false; rhs.len()];
        for (left_key, left_value) in self.iter() {
            let mut found = false;
            for (index, (right_key, right_value)) in rhs.iter().enumerate() {
                if !matched[index]
                    && left_key.bcg_deep_equal(right_key, abs_tol, rel_tol)
                    && left_value.bcg_deep_equal(right_value, abs_tol, rel_tol)
                {
                    matched[index] = true;
                    found = true;
                    break;
                }
            }
            if !found {
                return false;
            }
        }
        true
    }
}

pub fn bcg_deep_equal<L, R>(left: &L, right: &R, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool
where
    L: BcgDeepEqual<R>,
{
    left.bcg_deep_equal(right, abs_tol, rel_tol)
}

pub trait BcgTruthy {
    fn bcg_truthy(&self) -> bool;
}

macro_rules! impl_numeric_truthy {
    ($($t:ty),* $(,)?) => {
        $(impl BcgTruthy for $t {
            fn bcg_truthy(&self) -> bool { *self != 0 as $t }
        })*
    };
}

impl_numeric_truthy!(i8, i16, i32, i64, isize, u8, u16, u32, u64, usize);

impl BcgTruthy for bool {
    fn bcg_truthy(&self) -> bool { *self }
}

impl BcgTruthy for f64 {
    fn bcg_truthy(&self) -> bool { *self != 0.0 && !self.is_nan() }
}

impl BcgTruthy for String {
    fn bcg_truthy(&self) -> bool { !self.is_empty() }
}

impl<T> BcgTruthy for Vec<T> {
    fn bcg_truthy(&self) -> bool { !self.is_empty() }
}

impl<T> BcgTruthy for Option<T>
where
    T: BcgTruthy,
{
    fn bcg_truthy(&self) -> bool {
        self.as_ref().map(|value| value.bcg_truthy()).unwrap_or(false)
    }
}

impl<T: Eq + Hash> BcgTruthy for StdHashSet<T> {
    fn bcg_truthy(&self) -> bool { !self.is_empty() }
}

impl<K: Eq + Hash, V> BcgTruthy for StdHashMap<K, V> {
    fn bcg_truthy(&self) -> bool { !self.is_empty() }
}

impl<K: Ord, V> BcgTruthy for StdBTreeMap<K, V> {
    fn bcg_truthy(&self) -> bool { !self.is_empty() }
}

pub fn bcg_truthy<T: BcgTruthy>(value: &T) -> bool {
    value.bcg_truthy()
}

pub trait BcgContains<Item> {
    fn bcg_contains(&self, item: &Item) -> bool;
}

impl<T, U> BcgContains<U> for Vec<T>
where
    T: BcgDeepEqual<U>,
{
    fn bcg_contains(&self, item: &U) -> bool {
        self.iter().any(|value| value.bcg_deep_equal(item, None, None))
    }
}

impl<T, U> BcgContains<U> for StdHashSet<T>
where
    T: BcgDeepEqual<U> + Eq + Hash,
{
    fn bcg_contains(&self, item: &U) -> bool {
        self.iter().any(|value| value.bcg_deep_equal(item, None, None))
    }
}

impl<K, V, U> BcgContains<U> for StdHashMap<K, V>
where
    K: BcgDeepEqual<U> + Eq + Hash,
{
    fn bcg_contains(&self, item: &U) -> bool {
        self.keys().any(|value| value.bcg_deep_equal(item, None, None))
    }
}

impl BcgContains<String> for String {
    fn bcg_contains(&self, item: &String) -> bool {
        self.contains(item)
    }
}

pub fn bcg_contains<C, I>(container: &C, item: &I) -> bool
where
    C: BcgContains<I>,
{
    container.bcg_contains(item)
}

pub trait BcgLen {
    fn bcg_len(&self) -> i32;
}

impl<T> BcgLen for Vec<T> {
    fn bcg_len(&self) -> i32 { self.len() as i32 }
}

impl BcgLen for String {
    fn bcg_len(&self) -> i32 { self.len() as i32 }
}

impl<T: Eq + Hash> BcgLen for StdHashSet<T> {
    fn bcg_len(&self) -> i32 { self.len() as i32 }
}

impl<K: Eq + Hash, V> BcgLen for StdHashMap<K, V> {
    fn bcg_len(&self) -> i32 { self.len() as i32 }
}

pub fn bcg_len<T: BcgLen>(value: &T) -> i32 {
    value.bcg_len()
}

pub trait BcgOwnedStringHashMapLookup<V> {
    fn get(&self, key: String) -> Option<&V>;
    fn get_mut(&mut self, key: String) -> Option<&mut V>;
}

impl<V> BcgOwnedStringHashMapLookup<V> for StdHashMap<String, V> {
    fn get(&self, key: String) -> Option<&V> {
        StdHashMap::get(self, &key)
    }

    fn get_mut(&mut self, key: String) -> Option<&mut V> {
        StdHashMap::get_mut(self, &key)
    }
}

pub trait BcgSorted {
    type Output;
    fn bcg_sorted(&self) -> Self::Output;
}

impl<T: Ord + Clone> BcgSorted for Vec<T> {
    type Output = Vec<T>;
    fn bcg_sorted(&self) -> Vec<T> {
        let mut result = self.clone();
        result.sort();
        result
    }
}

impl BcgSorted for String {
    type Output = String;
    fn bcg_sorted(&self) -> String {
        let mut chars: Vec<char> = self.chars().collect();
        chars.sort();
        chars.into_iter().collect()
    }
}

pub fn bcg_sorted<T: BcgSorted>(value: &T) -> T::Output {
    value.bcg_sorted()
}

pub fn bcg_upper(value: String) -> String { value.to_uppercase() }
pub fn bcg_lower(value: String) -> String { value.to_lowercase() }
pub fn bcg_find(value: String, needle: String) -> i32 {
    value.find(&needle).map(|index| index as i32).unwrap_or(-1)
}

pub fn bcg_message_matches(mode: &str, pattern: &str, message: &str) -> bool {
    if mode.is_empty() {
        true
    } else if mode == "contains" {
        message.contains(pattern)
    } else if mode == "regex" {
        message.contains(pattern)
    } else {
        false
    }
}

pub struct BcgCall<T> {
    pub raised: bool,
    pub value: Option<T>,
    pub message: String,
    pub stdout: String,
    pub stderr: String,
}

fn bcg_panic_message(payload: Box<dyn Any + Send>) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_string()
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else {
        String::new()
    }
}

#[cfg(unix)]
extern "C" {
    fn pipe(fds: *mut i32) -> i32;
    fn dup(fd: i32) -> i32;
    fn dup2(oldfd: i32, newfd: i32) -> i32;
    fn close(fd: i32) -> i32;
}

#[cfg(unix)]
pub fn bcg_capture<F, T>(f: F) -> BcgCall<T>
where
    F: FnOnce() -> T,
{
    unsafe {
        let mut out_pipe = [0_i32; 2];
        let mut err_pipe = [0_i32; 2];
        if pipe(out_pipe.as_mut_ptr()) != 0 || pipe(err_pipe.as_mut_ptr()) != 0 {
            let result = catch_unwind(AssertUnwindSafe(f));
            return match result {
                Ok(value) => BcgCall { raised: false, value: Some(value), message: String::new(), stdout: String::new(), stderr: String::new() },
                Err(payload) => BcgCall { raised: true, value: None, message: bcg_panic_message(payload), stdout: String::new(), stderr: String::new() },
            };
        }
        let saved_out = dup(1);
        let saved_err = dup(2);
        dup2(out_pipe[1], 1);
        dup2(err_pipe[1], 2);
        close(out_pipe[1]);
        close(err_pipe[1]);

        let old_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let result = catch_unwind(AssertUnwindSafe(f));
        std::panic::set_hook(old_hook);

        let _ = std::io::stdout().flush();
        let _ = std::io::stderr().flush();
        dup2(saved_out, 1);
        dup2(saved_err, 2);
        close(saved_out);
        close(saved_err);

        let mut stdout = String::new();
        let mut stderr = String::new();
        let mut out_file = std::fs::File::from_raw_fd(out_pipe[0]);
        let mut err_file = std::fs::File::from_raw_fd(err_pipe[0]);
        let _ = out_file.read_to_string(&mut stdout);
        let _ = err_file.read_to_string(&mut stderr);

        match result {
            Ok(value) => BcgCall { raised: false, value: Some(value), message: String::new(), stdout, stderr },
            Err(payload) => BcgCall { raised: true, value: None, message: bcg_panic_message(payload), stdout, stderr },
        }
    }
}

#[cfg(not(unix))]
pub fn bcg_capture<F, T>(f: F) -> BcgCall<T>
where
    F: FnOnce() -> T,
{
    let result = catch_unwind(AssertUnwindSafe(f));
    match result {
        Ok(value) => BcgCall { raised: false, value: Some(value), message: String::new(), stdout: String::new(), stderr: String::new() },
        Err(payload) => BcgCall { raised: true, value: None, message: bcg_panic_message(payload), stdout: String::new(), stderr: String::new() },
    }
}
}
'''


def rust_string_literal(value: str) -> str:
    return json.dumps(value)


def rust_include_literal(path: Path) -> str:
    text = str(path)
    hashes = "#"
    while f'"{hashes}' in text:
        hashes += "#"
    return f"r{hashes}\"{text}\"{hashes}"


def rust_literal(value: Any, type_: TargetType | None = None) -> str:
    if type_ is None:
        type_ = target_type_for_value(value)
    if type_.kind == "optional":
        inner = type_.args[0]
        if value is None:
            return "None"
        return f"Some({rust_literal(value, inner)})"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (float, Decimal)) and not isinstance(value, bool):
        return f"{str(value)}_f64"
    if isinstance(value, str):
        return f"String::from({rust_string_literal(value)})"
    if type_.kind == "vector" and isinstance(value, (list, tuple, deque)):
        item_type = type_.args[0]
        return f"vec![{', '.join(rust_literal(item, item_type) for item in value)}]"
    if type_.kind == "set" and isinstance(value, (set, frozenset)):
        item_type = type_.args[0]
        items = ", ".join(rust_literal(item, item_type) for item in sorted(value, key=repr))
        return f"__bcg::bcg_hash_set(vec![{items}])"
    if type_.kind == "map" and isinstance(value, (dict, defaultdict, Counter)):
        key_type, value_type = type_.args
        entries = []
        for key, item in sorted(value.items(), key=lambda entry: repr(entry[0])):
            entries.append(
                f"({rust_literal(key, key_type)}, {rust_literal(item, value_type)})"
            )
        return f"__bcg::bcg_hash_map(vec![{', '.join(entries)}])"
    return rust_literal(value, target_type_for_value(value))


def rust_optional_tolerance(value: Any) -> str:
    if value is None:
        return "None"
    return f"Some({str(value)}_f64)"


def rust_expr(expr: dict[str, Any]) -> str:
    op = expr["op"]
    if op == "value":
        return rust_literal(expr["value"])
    if op == "result":
        return "__result.clone()"
    if op == "arg":
        return f"__arg{expr['index']}.clone()"
    if op in {"list", "tuple"}:
        return f"vec![{', '.join(rust_expr(item) for item in expr['items'])}]"
    if op == "set":
        return f"__bcg::bcg_hash_set(vec![{', '.join(rust_expr(item) for item in expr['items'])}])"
    if op == "dict":
        entries = ", ".join(
            f"({rust_expr(key)}, {rust_expr(value)})"
            for key, value in expr["entries"]
        )
        return f"__bcg::bcg_hash_map(vec![{entries}])"
    if op == "unary":
        operand = rust_expr(expr["operand"])
        if expr["operator"] == "not":
            return f"(!__bcg::bcg_truthy(&({operand})))"
        if expr["operator"] == "usub":
            return f"(-({operand}))"
        return f"(+({operand}))"
    if op == "binary":
        operators = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }
        if expr["operator"] == "pow":
            return f"({rust_expr(expr['left'])}).powf({rust_expr(expr['right'])} as f64)"
        return f"(({rust_expr(expr['left'])}) {operators[expr['operator']]} ({rust_expr(expr['right'])}))"
    if op == "compare":
        left = rust_expr(expr["left"])
        right = rust_expr(expr["right"])
        operator = expr["operator"]
        if operator == "eq":
            return f"__bcg::bcg_deep_equal(&({left}), &({right}), None, None)"
        if operator == "ne":
            return f"(!__bcg::bcg_deep_equal(&({left}), &({right}), None, None))"
        if operator == "in":
            return f"__bcg::bcg_contains(&({right}), &({left}))"
        if operator == "not_in":
            return f"(!__bcg::bcg_contains(&({right}), &({left})))"
        operators = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        return f"(({left}) {operators[operator]} ({right}))"
    if op == "call":
        args = [rust_expr(arg) for arg in expr["args"]]
        name = expr["name"]
        if name == "abs":
            return f"({args[0]}).abs()"
        if name == "bool":
            return f"__bcg::bcg_truthy(&({args[0]}))"
        if name == "float":
            return f"(({args[0]}) as f64)"
        if name == "int":
            return f"(({args[0]}) as i32)"
        if name == "len":
            return f"__bcg::bcg_len(&({args[0]}))"
        if name == "sorted":
            return f"__bcg::bcg_sorted(&({args[0]}))"
        if name == "str":
            return f"format!(\"{{}}\", {args[0]})"
        if name in {"list", "tuple"}:
            return args[0]
        if name in {"set", "frozenset"}:
            return f"__bcg::bcg_hash_set({args[0]})"
        if name == "sum":
            return f"({args[0]}).iter().sum::<i32>()"
        if name == "min":
            return f"*({args[0]}).iter().min().unwrap()"
        if name == "max":
            return f"*({args[0]}).iter().max().unwrap()"
    if op == "method":
        receiver = rust_expr(expr["receiver"])
        args = [rust_expr(arg) for arg in expr["args"]]
        name = expr["name"]
        if name == "upper":
            return f"__bcg::bcg_upper({receiver})"
        if name == "lower":
            return f"__bcg::bcg_lower({receiver})"
        if name == "find":
            return f"__bcg::bcg_find({receiver}, {args[0]})"
        if name in {"strip", "lstrip", "rstrip"}:
            return f"({receiver}).trim().to_string()"
        if name == "split":
            return f"({receiver}).split_whitespace().map(String::from).collect::<Vec<String>>()"
        if name == "startswith":
            return f"({receiver}).starts_with(&{args[0]})"
        if name == "endswith":
            return f"({receiver}).ends_with(&{args[0]})"
        if name == "count":
            return f"({receiver}).matches(&{args[0]}).count() as i32"
        if name == "replace":
            return f"({receiver}).replace(&{args[0]}, &{args[1]})"
        if name == "join":
            return receiver
    if op == "subscript":
        return f"({rust_expr(expr['value'])})[{rust_expr(expr['index'])} as usize].clone()"
    if op == "slice":
        return rust_expr(expr["value"])
    return "false"


def rust_case_assertion_code(case: TestCase, default_abs_tol: float | None) -> str:
    actual = rust_expr(case.actual_expr)
    abs_tol = rust_optional_tolerance(case.abs_tol if case.abs_tol is not None else default_abs_tol)
    rel_tol = rust_optional_tolerance(case.rel_tol)
    if case.kind == "eq":
        expected = rust_literal(case.expected)
        return f"__passed = __bcg::bcg_deep_equal(&({actual}), &({expected}), {abs_tol}, {rel_tol});"
    if case.kind == "ne":
        expected = rust_literal(case.expected)
        return f"__passed = !__bcg::bcg_deep_equal(&({actual}), &({expected}), {abs_tol}, {rel_tol});"
    if case.kind == "isclose":
        expected = rust_literal(case.expected)
        return f"__passed = __bcg::bcg_numeric_close(({actual}) as f64, ({expected}) as f64, {rust_optional_tolerance(case.abs_tol)}, {rust_optional_tolerance(case.rel_tol)});"
    if case.kind == "absdiff":
        expected = rust_literal(case.expected)
        comparator = "<" if case.comparison == "abs_lt" else "<="
        return f"__passed = ((({actual}) as f64 - ({expected}) as f64).abs() {comparator} {str(case.abs_tol)}_f64);"
    if case.kind == "truthy":
        return f"__passed = __bcg::bcg_truthy(&({actual}));"
    if case.kind == "not":
        return f"__passed = !__bcg::bcg_truthy(&({actual}));"
    return "__passed = false;"


def rust_entrypoint_is_async(solution_path: Path, entrypoint: str) -> bool:
    try:
        source = solution_path.read_text(encoding="utf-8")
    except OSError:
        return False
    escaped = re.escape(entrypoint)
    if re.search(rf"\basync\s+fn\s+{escaped}\b", source):
        return True
    return re.search(rf"\bfn\s+{escaped}\b[^\{{;]*\bFuture\b", source, flags=re.DOTALL) is not None


def build_rust_case_source(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    await_entrypoint: bool = False,
) -> str:
    args = [
        f"let mut __arg{index} = {rust_literal(arg)};"
        for index, arg in enumerate(case.args)
    ]
    mutation_indexes = expr_arg_indices(case.actual_expr)
    call_args = ", ".join(
        f"&mut __arg{index}" if index in mutation_indexes else f"__arg{index}.clone()"
        for index in range(len(case.args))
    )
    call_expr = f"{entrypoint}({call_args})"
    if await_entrypoint:
        call_expr = f"__bcg::bcg_block_on({call_expr})"
    exception_type = case.exception_type or ""
    message_match = case.message_match or ""
    message_pattern = case.message_pattern or ""
    if case.kind == "raises":
        assertion = f'''
    let __type_ok = {str(exception_type == "").lower()} || {rust_string_literal(exception_type)} == "Exception" || {rust_string_literal(exception_type)} == "RuntimeError" || {rust_string_literal(exception_type)} == "ValueError";
    let mut __passed = __call.raised && __type_ok && __bcg::bcg_message_matches({rust_string_literal(message_match)}.as_str(), {rust_string_literal(message_pattern)}.as_str(), __call.message.as_str());
'''
    else:
        checks = rust_case_assertion_code(case, default_abs_tol)
        assertion = f'''
    let mut __passed = false;
    if !__call.raised {{
        if let Some(__result) = __call.value {{
            {checks}
        }}
    }}
'''
    stdout_check = ""
    if case.expect_stdout is not None:
        stdout_check = f"\n    __passed = __passed && __call.stdout == {rust_string_literal(case.expect_stdout)};"
    stderr_check = ""
    if case.expect_stderr is not None:
        stderr_check = f"\n    __passed = __passed && __call.stderr == {rust_string_literal(case.expect_stderr)};"
    return f'''{RUST_CASE_HELPERS}
use __bcg::BcgOwnedStringHashMapLookup;
include!({rust_include_literal(solution_path)});

fn main() {{
    {chr(10).join(args)}
    let __call = __bcg::bcg_capture(|| {{
        {call_expr}
    }});
    {assertion}
    {stdout_check}{stderr_check}
    println!("{{\\"passed\\":{{}}}}", if __passed {{ "true" }} else {{ "false" }});
}}
'''


def run_rust_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout_seconds: float | None = None,
) -> bool:
    if case_contains_deque(case):
        return False
    source = build_rust_case_source(
        solution_path,
        entrypoint,
        case,
        default_abs_tol,
        rust_entrypoint_is_async(solution_path, entrypoint),
    )
    return run_compiled_source(
        source,
        ".rs",
        ["rustc"],
        lambda compiler, source_path, binary_path: [
            compiler,
            "--edition=2021",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        timeout_seconds,
    )


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


def case_timeout_for_options(
    options: TestExecutionOptions,
    deadline: float | None,
) -> float | None:
    timeout_seconds = options.timeout_seconds
    if deadline is None:
        return timeout_seconds
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 0
    if timeout_seconds is None:
        return remaining
    return min(timeout_seconds, remaining)


def aggregate_results(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None = None,
    options: TestExecutionOptions | None = None,
) -> dict[str, Any]:
    options = options or TestExecutionOptions()
    deadline = None
    if options.total_timeout_seconds is not None:
        deadline = time.monotonic() + options.total_timeout_seconds
    passed: list[str] = []
    failed: list[str] = []
    for index, case in enumerate(cases):
        timeout_seconds = case_timeout_for_options(options, deadline)
        if timeout_seconds == 0:
            failed.extend(remaining.id for remaining in cases[index:])
            break
        if execute_case(solution_path, lang, entrypoint, case, default_abs_tol, timeout_seconds):
            passed.append(case.id)
        else:
            failed.append(case.id)
    status = "pass" if not failed else "fail"
    return {"status": status, "passed": passed, "failed": failed}


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
    lang = args.lang
    if not is_supported_lang(lang):
        print_json_result(error_result())
        return 2
    try:
        default_abs_tol = parse_default_tolerance(args.tol)
        options = TestExecutionOptions(
            list_tests=args.list_tests,
            run_id=args.run,
            timeout_seconds=parse_timeout_ms(args.timeout_ms),
            total_timeout_seconds=parse_timeout_ms(args.total_timeout_ms),
        )
    except DiscoveryError:
        print_json_result(error_result())
        return 2

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / tester_filename(lang)
    if not tester_path.is_file():
        print_json_result(error_result())
        return 2

    try:
        metadata = read_tester_metadata(tester_path)
    except MetadataError:
        print_json_result(error_result())
        return 2
    if metadata["lang"] != lang:
        print_json_result(error_result())
        return 2

    entrypoint = metadata["entrypoint"]
    try:
        cases = discover_tests(tests_dir, entrypoint)
    except DiscoveryError:
        print_json_result(error_result())
        return 2

    if options.list_tests:
        print_json_result({"status": "pass", "passed": [case.id for case in cases], "failed": []})
        return 0

    if options.run_id is not None:
        selected = [case for case in cases if case.id == options.run_id]
        if not selected:
            print_json_result(error_result())
            return 2
        cases = selected

    result = aggregate_results(Path(args.solution_path), lang, entrypoint, cases, default_abs_tol, options)
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
