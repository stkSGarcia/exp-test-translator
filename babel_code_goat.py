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
    """Raised when tests.py cannot be interpreted as the supported subset."""


class MetadataError(Exception):
    """Raised when generated tester metadata is absent or invalid."""


class ExecutionSetupError(Exception):
    """Raised when a target cannot be prepared before tests execute."""


class LoopEvaluationError(Exception):
    """Raised when a loop cannot be evaluated as a supported parameterization."""


def result_expr() -> dict[str, Any]:
    return {"op": "result"}


@dataclass(frozen=True)
class PendingTest:
    line: int
    kind: str
    source_path: str = "tests.py"
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
    mutation_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    id: str
    line: int
    kind: str
    source_path: str = "tests.py"
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
    mutation_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)


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


def render_tester(lang: str, entrypoint: str) -> str:
    metadata = {
        "version": METADATA_VERSION,
        "entrypoint": entrypoint,
        "lang": lang,
    }
    if lang == "cpp":
        return render_cpp_tester_metadata(metadata)
    if lang == "rust":
        return render_rust_tester_metadata(metadata)
    return render_comment_metadata(metadata, "#" if lang == "python" else "//")


def render_comment_metadata(metadata: dict[str, Any], prefix: str) -> str:
    return (
        f"{prefix} Generated by babel_code_goat.py.\n"
        f"{prefix} {METADATA_MARKER} {json_line(metadata)}\n"
    )


def render_cpp_tester_metadata(metadata: dict[str, Any]) -> str:
    return (
        render_comment_metadata(metadata, "//")
        + textwrap.dedent(
            """
            // C++17 target support is generated at test time so the harness can
            // include the selected solution path and discovered test cases.
            #include <algorithm>
            #include <deque>
            #include <map>
            #include <optional>
            #include <set>
            #include <stdexcept>
            #include <string>
            #include <vector>

            namespace babel_code_goat_generated {
            struct tester_anchor {};
            }
            """
        ).lstrip("\n")
    )


def render_rust_tester_metadata(metadata: dict[str, Any]) -> str:
    return (
        render_comment_metadata(metadata, "//")
        + textwrap.dedent(
            """
            // Rust target support is generated at test time so the harness can
            // include the selected solution path and discovered test cases.
            use std::collections::{BTreeMap, HashMap, HashSet};
            use std::panic;

            mod babel_code_goat_generated {
                pub struct TesterAnchor;
            }
            """
        ).lstrip("\n")
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
            mutation = self.parse_mutation_start(stmt)
            if mutation is not None:
                args, bindings = mutation
                next_index = index + 1
                if next_index >= len(body) or not isinstance(body[next_index], ast.Assert):
                    raise DiscoveryError(
                        f"mutation call must be immediately followed by assertions at line {stmt.lineno}"
                    )
                while next_index < len(body) and isinstance(body[next_index], ast.Assert):
                    self.visit_mutation_assert(body[next_index], args, bindings)
                    next_index += 1
                index = next_index
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

    def parse_mutation_start(
        self,
        stmt: ast.stmt,
    ) -> tuple[list[Any], dict[str, dict[str, Any]]] | None:
        if isinstance(stmt, ast.Expr) and self.is_entrypoint_call(stmt.value):
            call = stmt.value
            assert isinstance(call, ast.Call)
            args = self.parse_entrypoint_call(call, stmt.lineno)
            return args, self.mutation_arg_bindings(call)

        if isinstance(stmt, ast.Assign) and self.is_entrypoint_call(stmt.value):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                raise DiscoveryError(
                    f"mutation assignment requires one name target at line {stmt.lineno}"
                )
            call = stmt.value
            assert isinstance(call, ast.Call)
            args = self.parse_entrypoint_call(call, stmt.lineno)
            bindings = self.mutation_arg_bindings(call)
            target_name = stmt.targets[0].id
            if target_name == self.entrypoint:
                raise DiscoveryError(f"assignment to entrypoint is unsupported at line {stmt.lineno}")
            bindings[target_name] = {"source": "result"}
            return args, bindings

        return None

    def is_entrypoint_call(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == self.entrypoint
        )

    def mutation_arg_bindings(self, call: ast.Call) -> dict[str, dict[str, Any]]:
        bindings: dict[str, dict[str, Any]] = {}
        arg_index = 0
        for arg in call.args:
            if isinstance(arg, ast.Starred):
                items = as_iterable_items(
                    self.parse_value(arg.value),
                    getattr(arg, "lineno", getattr(call, "lineno", 0)),
                    "starred argument",
                )
                arg_index += len(items)
                continue
            if isinstance(arg, ast.Name):
                bindings.setdefault(arg.id, {"source": "arg", "index": arg_index})
            arg_index += 1
        return bindings

    def referenced_mutation_names(self, node: ast.AST, names: set[str]) -> set[str]:
        return {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in names
        }

    def parse_mutation_expression(
        self,
        node: ast.AST,
        line_no: int,
        variable_names: set[str],
    ) -> dict[str, Any]:
        if self.count_entrypoint_calls(node) != 0:
            raise DiscoveryError(
                f"mutation assertion must not call {self.entrypoint} at line {line_no}"
            )
        entrypoint_args: list[list[Any]] = []
        return self.parse_expression(node, entrypoint_args, variable_names)

    def visit_mutation_assert(
        self,
        stmt: ast.Assert,
        args: list[Any],
        bindings: dict[str, dict[str, Any]],
    ) -> None:
        if stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {stmt.lineno}")
        if self.count_entrypoint_calls(stmt.test) != 0:
            raise DiscoveryError(
                f"mutation assertion must not call {self.entrypoint} at line {stmt.lineno}"
            )

        variable_names = set(bindings)
        if not self.referenced_mutation_names(stmt.test, variable_names):
            raise DiscoveryError(
                f"mutation assertion must reference a mutated variable at line {stmt.lineno}"
            )

        if isinstance(stmt.test, ast.Compare):
            self.visit_mutation_comparison_assert(stmt, stmt.test, args, bindings)
            return

        if isinstance(stmt.test, ast.UnaryOp) and isinstance(stmt.test.op, ast.Not):
            actual_expr = self.parse_mutation_expression(
                stmt.test.operand,
                stmt.lineno,
                variable_names,
            )
            self.add_test(
                stmt.lineno,
                "not",
                args,
                actual_expr=actual_expr,
                mutation_bindings=bindings,
            )
            return

        actual_expr = self.parse_mutation_expression(stmt.test, stmt.lineno, variable_names)
        self.add_test(
            stmt.lineno,
            "truthy",
            args,
            actual_expr=actual_expr,
            mutation_bindings=bindings,
        )

    def visit_mutation_comparison_assert(
        self,
        stmt: ast.Assert,
        test: ast.Compare,
        args: list[Any],
        bindings: dict[str, dict[str, Any]],
    ) -> None:
        if len(test.ops) != 1 or len(test.comparators) != 1:
            raise DiscoveryError(f"unsupported comparison at line {stmt.lineno}")
        operator = test.ops[0]
        if type(operator) not in COMPARE_OPERATORS:
            raise DiscoveryError(f"unsupported comparison operator at line {stmt.lineno}")

        variable_names = set(bindings)
        right = test.comparators[0]
        left_refs = self.referenced_mutation_names(test.left, variable_names)
        right_refs = self.referenced_mutation_names(right, variable_names)

        if isinstance(operator, (ast.Eq, ast.NotEq)) and left_refs and not right_refs:
            actual_expr = self.parse_mutation_expression(test.left, stmt.lineno, variable_names)
            expected = self.parse_value(right)
            self.add_test(
                stmt.lineno,
                "eq" if isinstance(operator, ast.Eq) else "ne",
                args,
                expected,
                actual_expr=actual_expr,
                mutation_bindings=bindings,
            )
            return

        if isinstance(operator, (ast.Eq, ast.NotEq)) and right_refs and not left_refs:
            actual_expr = self.parse_mutation_expression(right, stmt.lineno, variable_names)
            expected = self.parse_value(test.left)
            self.add_test(
                stmt.lineno,
                "eq" if isinstance(operator, ast.Eq) else "ne",
                args,
                expected,
                actual_expr=actual_expr,
                mutation_bindings=bindings,
            )
            return

        actual_expr = self.parse_mutation_expression(test, stmt.lineno, variable_names)
        self.add_test(
            stmt.lineno,
            "truthy",
            args,
            actual_expr=actual_expr,
            mutation_bindings=bindings,
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
        variable_names: set[str] | None = None,
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return {"op": "value", "value": node.value}
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            if variable_names is not None and node.id in variable_names:
                return {"op": "var", "name": node.id}
            return {"op": "value", "value": self.resolve_name(node.id, line_no)}
        if isinstance(node, ast.List):
            return {
                "op": "list",
                "items": [
                    self.parse_expression(item, entrypoint_args, variable_names)
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Tuple):
            return {
                "op": "tuple",
                "items": [
                    self.parse_expression(item, entrypoint_args, variable_names)
                    for item in node.elts
                ],
            }
        if isinstance(node, ast.Set):
            return {
                "op": "set",
                "items": [
                    self.parse_expression(item, entrypoint_args, variable_names)
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
                        self.parse_expression(key_node, entrypoint_args, variable_names),
                        self.parse_expression(value_node, entrypoint_args, variable_names),
                    ]
                )
            return {"op": "dict", "entries": entries}
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return {
                "op": "unary",
                "operator": UNARY_OPERATORS[type(node.op)],
                "operand": self.parse_expression(node.operand, entrypoint_args, variable_names),
            }
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return {
                "op": "binary",
                "operator": BINARY_OPERATORS[type(node.op)],
                "left": self.parse_expression(node.left, entrypoint_args, variable_names),
                "right": self.parse_expression(node.right, entrypoint_args, variable_names),
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
                "left": self.parse_expression(node.left, entrypoint_args, variable_names),
                "right": self.parse_expression(
                    node.comparators[0],
                    entrypoint_args,
                    variable_names,
                ),
            }
        if isinstance(node, ast.Subscript):
            return self.parse_subscript_expression(node, entrypoint_args, variable_names)
        if isinstance(node, ast.Call):
            return self.parse_call_expression(node, entrypoint_args, variable_names)
        raise DiscoveryError(f"unsupported expression at line {line_no}")

    def parse_call_expression(
        self,
        node: ast.Call,
        entrypoint_args: list[list[Any]],
        variable_names: set[str] | None = None,
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
                    self.parse_expression(arg, entrypoint_args, variable_names)
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
                    variable_names,
                ),
                "args": [
                    self.parse_expression(arg, entrypoint_args, variable_names)
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
        variable_names: set[str] | None = None,
    ) -> dict[str, Any]:
        value = self.parse_expression(node.value, entrypoint_args, variable_names)
        if isinstance(node.slice, ast.Slice):
            return {
                "op": "slice",
                "value": value,
                "lower": self.parse_expression(node.slice.lower, entrypoint_args, variable_names)
                if node.slice.lower is not None
                else None,
                "upper": self.parse_expression(node.slice.upper, entrypoint_args, variable_names)
                if node.slice.upper is not None
                else None,
                "step": self.parse_expression(node.slice.step, entrypoint_args, variable_names)
                if node.slice.step is not None
                else None,
            }
        return {
            "op": "subscript",
            "value": value,
            "index": self.parse_expression(node.slice, entrypoint_args, variable_names),
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
        mutation_bindings: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        expectations = self.expectations_for(line_no)
        self.pending.append(
            PendingTest(
                line=line_no,
                kind=kind,
                source_path=self.source_path,
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
                mutation_bindings=dict(mutation_bindings or {}),
            )
        )

    def add_loop_test(self, line_no: int, passed: bool) -> None:
        self.pending.append(
            PendingTest(
                line=line_no,
                kind="loop",
                source_path=self.source_path,
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
                kind=test.kind,
                source_path=test.source_path,
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
                mutation_bindings=test.mutation_bindings,
            )
        )
    return cases


def test_id_base(source_path: str, line_no: int, iteration_path: tuple[int, ...]) -> str:
    suffix = "".join(f":{index}" for index in iteration_path)
    return f"{source_path}:{line_no}{suffix}"


def relative_source_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_test_like_path(path: Path) -> bool:
    stem = path.stem
    return (
        stem.startswith("test")
        or stem.endswith("_test")
        or stem == "tests"
        or stem.endswith("_tests")
    )


def is_ignored_python_source(path: Path) -> bool:
    return path.name in {tester_filename("python"), "solution.py"}


def discoverable_python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise DiscoveryError("tests_dir must be an existing directory")

    generated_tester_names = set(SUPPORTED_LANGS.values())
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".py":
            if not is_ignored_python_source(path):
                candidates.append(path)
            continue
        if path.name in generated_tester_names:
            continue
        if is_test_like_path(path):
            rel_path = relative_source_path(root, path)
            raise DiscoveryError(f"test-like file must be Python: {rel_path}")

    return sorted(candidates, key=lambda item: relative_source_path(root, item))


def discover_tests(tests_dir: Path | str, entrypoint: str) -> list[TestCase]:
    root = Path(tests_dir)
    test_files = discoverable_python_files(root)
    cases: list[TestCase] = []
    for tests_path in test_files:
        source_path = relative_source_path(root, tests_path)
        try:
            source = tests_path.read_text(encoding="utf-8")
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
        "mutation_bindings": case.mutation_bindings,
    }


Shape = tuple[Any, ...]


def int_shape(value: int) -> Shape:
    return ("int",) if -(2**31) <= value <= 2**31 - 1 else ("long",)


def optional_shape(shape: Shape) -> Shape:
    return shape if shape[0] == "optional" else ("optional", shape)


def merge_shapes(shapes: list[Shape]) -> Shape:
    if not shapes:
        return ("int",)
    non_none = [shape for shape in shapes if shape[0] != "none"]
    if len(non_none) != len(shapes):
        if not non_none:
            return optional_shape(("int",))
        return optional_shape(merge_shapes(non_none))
    if len(shapes) == 1:
        return shapes[0]
    if all(shape == shapes[0] for shape in shapes):
        return shapes[0]

    numeric = {"int", "long", "float"}
    if all(shape[0] in numeric for shape in shapes):
        if any(shape[0] == "float" for shape in shapes):
            return ("float",)
        if any(shape[0] == "long" for shape in shapes):
            return ("long",)
        return ("int",)

    first_kind = shapes[0][0]
    if all(shape[0] == first_kind for shape in shapes):
        if first_kind in {"vector", "deque", "set"}:
            return (first_kind, merge_shapes([shape[1] for shape in shapes]))
        if first_kind == "map":
            return (
                "map",
                merge_shapes([shape[1] for shape in shapes]),
                merge_shapes([shape[2] for shape in shapes]),
            )
        if first_kind == "tuple":
            arity = len(shapes[0][1])
            if all(len(shape[1]) == arity for shape in shapes):
                return (
                    "tuple",
                    tuple(
                        merge_shapes([shape[1][index] for shape in shapes])
                        for index in range(arity)
                    ),
                )
        if first_kind == "optional":
            return optional_shape(merge_shapes([shape[1] for shape in shapes]))

    set_kinds = {shape[0] for shape in shapes}
    if set_kinds <= {"set", "frozenset"}:
        return ("set", merge_shapes([shape[1] for shape in shapes]))

    raise ExecutionSetupError("compiled target cannot infer a homogeneous value shape")


def value_shape(value: Any) -> Shape:
    if value is None:
        return ("none",)
    if isinstance(value, bool):
        return ("bool",)
    if isinstance(value, int) and not isinstance(value, bool):
        return int_shape(value)
    if isinstance(value, (float, Decimal)) and not isinstance(value, bool):
        return ("float",)
    if isinstance(value, str):
        return ("string",)
    if isinstance(value, list):
        return ("vector", merge_shapes([value_shape(item) for item in value]))
    if isinstance(value, tuple):
        return ("tuple", tuple(value_shape(item) for item in value))
    if isinstance(value, deque):
        return ("deque", merge_shapes([value_shape(item) for item in value]))
    if isinstance(value, (set, frozenset)):
        return ("set", merge_shapes([value_shape(item) for item in value]))
    if isinstance(value, Counter):
        key_shape = merge_shapes([value_shape(key) for key in value.keys()])
        return ("map", key_shape, ("int",))
    if isinstance(value, (dict, defaultdict)):
        return (
            "map",
            merge_shapes([value_shape(key) for key in value.keys()]),
            merge_shapes([value_shape(item) for item in value.values()]),
        )
    raise ExecutionSetupError(f"compiled target cannot render value: {value!r}")


def cxx_string_literal(value: str) -> str:
    return json.dumps(value)


def rust_string_literal(value: str) -> str:
    return json.dumps(value)


def numeric_literal(value: Any, suffix: str = "") -> str:
    if isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, float):
        text = repr(value)
    else:
        text = str(value)
    if text in {"inf", "Infinity"}:
        raise ExecutionSetupError("compiled target cannot render infinity")
    if text in {"nan", "NaN"}:
        raise ExecutionSetupError("compiled target cannot render NaN")
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return f"{text}{suffix}"


def cpp_type(shape: Shape) -> str:
    kind = shape[0]
    if kind == "bool":
        return "bool"
    if kind == "int":
        return "int"
    if kind == "long":
        return "long long"
    if kind == "float":
        return "long double"
    if kind == "string":
        return "std::string"
    if kind == "optional":
        return f"std::optional<{cpp_type(shape[1])}>"
    if kind == "vector":
        return f"std::vector<{cpp_type(shape[1])}>"
    if kind == "deque":
        return f"std::deque<{cpp_type(shape[1])}>"
    if kind == "set":
        return f"std::set<{cpp_type(shape[1])}>"
    if kind == "map":
        return f"std::map<{cpp_type(shape[1])}, {cpp_type(shape[2])}>"
    if kind == "tuple":
        return "std::tuple<" + ", ".join(cpp_type(item) for item in shape[1]) + ">"
    if kind == "none":
        return cpp_type(optional_shape(("int",)))
    raise ExecutionSetupError(f"unsupported C++ shape: {shape!r}")


def cpp_literal(value: Any, shape: Shape | None = None) -> str:
    shape = value_shape(value) if shape is None else shape
    kind = shape[0]
    if kind == "none":
        return f"{cpp_type(shape)}{{}}"
    if kind == "optional":
        if value is None:
            return f"{cpp_type(shape)}{{}}"
        return f"{cpp_type(shape)}{{{cpp_literal(value, shape[1])}}}"
    if kind == "bool":
        return "true" if value else "false"
    if kind in {"int", "long"}:
        return str(value)
    if kind == "float":
        return numeric_literal(value, "L")
    if kind == "string":
        return f"std::string({cxx_string_literal(value)})"
    if kind in {"vector", "deque", "set"}:
        items = ", ".join(cpp_literal(item, shape[1]) for item in value)
        return f"{cpp_type(shape)}{{{items}}}"
    if kind == "tuple":
        items = ", ".join(
            cpp_literal(item, item_shape)
            for item, item_shape in zip(value, shape[1])
        )
        return f"{cpp_type(shape)}{{{items}}}"
    if kind == "map":
        entries = value.items()
        pairs = ", ".join(
            f"std::pair<{cpp_type(shape[1])}, {cpp_type(shape[2])}>"
            f"{{{cpp_literal(key, shape[1])}, {cpp_literal(item, shape[2])}}}"
            for key, item in entries
        )
        return f"{cpp_type(shape)}{{{pairs}}}"
    raise ExecutionSetupError(f"unsupported C++ literal shape: {shape!r}")


def rust_type(shape: Shape) -> str:
    kind = shape[0]
    if kind == "bool":
        return "bool"
    if kind == "int":
        return "i32"
    if kind == "long":
        return "i64"
    if kind == "float":
        return "f64"
    if kind == "string":
        return "String"
    if kind == "optional":
        return f"Option<{rust_type(shape[1])}>"
    if kind in {"vector", "deque"}:
        return f"Vec<{rust_type(shape[1])}>"
    if kind == "set":
        return f"std::collections::HashSet<{rust_type(shape[1])}>"
    if kind == "map":
        return f"std::collections::HashMap<{rust_type(shape[1])}, {rust_type(shape[2])}>"
    if kind == "tuple":
        if len(shape[1]) == 1:
            return f"({rust_type(shape[1][0])},)"
        return "(" + ", ".join(rust_type(item) for item in shape[1]) + ")"
    if kind == "none":
        return rust_type(optional_shape(("int",)))
    raise ExecutionSetupError(f"unsupported Rust shape: {shape!r}")


def rust_literal(value: Any, shape: Shape | None = None) -> str:
    shape = value_shape(value) if shape is None else shape
    kind = shape[0]
    if kind == "none":
        return "None::<i32>"
    if kind == "optional":
        if value is None:
            return f"None::<{rust_type(shape[1])}>"
        return f"Some({rust_literal(value, shape[1])})"
    if kind == "bool":
        return "true" if value else "false"
    if kind in {"int", "long"}:
        return str(value)
    if kind == "float":
        return numeric_literal(value)
    if kind == "string":
        return f"String::from({rust_string_literal(value)})"
    if kind in {"vector", "deque"}:
        items = ", ".join(rust_literal(item, shape[1]) for item in value)
        return f"vec![{items}]"
    if kind == "set":
        items = ", ".join(rust_literal(item, shape[1]) for item in value)
        return f"bcg::set_from::<{rust_type(shape[1])}>(vec![{items}])"
    if kind == "tuple":
        items = [rust_literal(item, item_shape) for item, item_shape in zip(value, shape[1])]
        if len(items) == 1:
            return f"({items[0]},)"
        return "(" + ", ".join(items) + ")"
    if kind == "map":
        entries = value.items()
        pairs = ", ".join(
            f"({rust_literal(key, shape[1])}, {rust_literal(item, shape[2])})"
            for key, item in entries
        )
        return f"bcg::map_from::<{rust_type(shape[1])}, {rust_type(shape[2])}>(vec![{pairs}])"
    raise ExecutionSetupError(f"unsupported Rust literal shape: {shape!r}")


def numeric_cpp_value(value: Any | None, default: str = "0.0L") -> tuple[bool, str]:
    if value is None:
        return False, default
    return True, numeric_literal(value, "L")


def cpp_tolerance(case: TestCase, default_abs_tol: float | None) -> str:
    has_abs, abs_value = numeric_cpp_value(case.abs_tol, "0.0L")
    if not has_abs and default_abs_tol is not None:
        has_abs, abs_value = True, numeric_literal(default_abs_tol, "L")
    has_rel, rel_value = numeric_cpp_value(case.rel_tol, "0.0L")
    return (
        "bcg::Tolerance{"
        f"{str(has_abs).lower()}, {abs_value}, "
        f"{str(has_rel).lower()}, {rel_value}"
        "}"
    )


def cpp_specific_tolerance(abs_tol: Any | None, rel_tol: Any | None = None) -> str:
    has_abs, abs_value = numeric_cpp_value(abs_tol, "0.0L")
    has_rel, rel_value = numeric_cpp_value(rel_tol, "0.0L")
    return (
        "bcg::Tolerance{"
        f"{str(has_abs).lower()}, {abs_value}, "
        f"{str(has_rel).lower()}, {rel_value}"
        "}"
    )


def cpp_expr(expr: dict[str, Any], variables: dict[str, str]) -> str:
    op = expr["op"]
    if op == "result":
        return "result"
    if op == "var":
        return variables[expr["name"]]
    if op == "value":
        return cpp_literal(expr["value"])
    if op == "list":
        items = ", ".join(cpp_expr(item, variables) for item in expr["items"])
        return f"std::vector{{{items}}}" if items else "std::vector<int>{}"
    if op == "tuple":
        items = ", ".join(cpp_expr(item, variables) for item in expr["items"])
        return f"std::make_tuple({items})"
    if op == "set":
        items = ", ".join(cpp_expr(item, variables) for item in expr["items"])
        return f"bcg::set_from(std::vector{{{items}}})" if items else "std::set<int>{}"
    if op == "dict":
        entries = ", ".join(
            f"std::make_pair({cpp_expr(key, variables)}, {cpp_expr(value, variables)})"
            for key, value in expr["entries"]
        )
        return f"bcg::map_from(std::vector{{{entries}}})" if entries else "std::map<int, int>{}"
    if op == "unary":
        operand = cpp_expr(expr["operand"], variables)
        if expr["operator"] == "not":
            return f"(!bcg::truthy({operand}))"
        if expr["operator"] == "uadd":
            return f"(+{operand})"
        if expr["operator"] == "usub":
            return f"(-{operand})"
        raise ExecutionSetupError(f"unsupported C++ unary operator: {expr['operator']}")
    if op == "binary":
        left = cpp_expr(expr["left"], variables)
        right = cpp_expr(expr["right"], variables)
        return f"bcg::binary_{expr['operator']}({left}, {right})"
    if op == "compare":
        left = cpp_expr(expr["left"], variables)
        right = cpp_expr(expr["right"], variables)
        return f"bcg::compare_{expr['operator']}({left}, {right})"
    if op == "call":
        args = [cpp_expr(arg, variables) for arg in expr["args"]]
        name = expr["name"]
        if name in {"list", "tuple"}:
            return args[0]
        if name == "frozenset":
            name = "set"
        return f"bcg::{name}_value({', '.join(args)})"
    if op == "method":
        receiver = cpp_expr(expr["receiver"], variables)
        args = [cpp_expr(arg, variables) for arg in expr["args"]]
        return f"bcg::{expr['name']}_method({receiver}{', ' if args else ''}{', '.join(args)})"
    if op == "subscript":
        return f"bcg::subscript_value({cpp_expr(expr['value'], variables)}, {cpp_expr(expr['index'], variables)})"
    if op == "slice":
        lower = "std::nullopt" if expr["lower"] is None else f"std::optional<int>{{{cpp_expr(expr['lower'], variables)}}}"
        upper = "std::nullopt" if expr["upper"] is None else f"std::optional<int>{{{cpp_expr(expr['upper'], variables)}}}"
        step = "std::nullopt" if expr["step"] is None else f"std::optional<int>{{{cpp_expr(expr['step'], variables)}}}"
        return f"bcg::slice_value({cpp_expr(expr['value'], variables)}, {lower}, {upper}, {step})"
    raise ExecutionSetupError(f"unsupported C++ expression operation: {op}")


def cpp_variables(case: TestCase) -> dict[str, str]:
    variables: dict[str, str] = {}
    for name, binding in case.mutation_bindings.items():
        if binding.get("source") == "arg":
            variables[name] = f"arg{binding['index']}"
        elif binding.get("source") == "result":
            variables[name] = "result"
    return variables


def cpp_match_code(case: TestCase, default_abs_tol: float | None) -> str:
    if case.kind == "raises":
        expected_type = "" if case.exception_type is None else case.exception_type
        message_match = "" if case.message_match is None else case.message_match
        message_pattern = "" if case.message_pattern is None else case.message_pattern
        return (
            "passed = bcg::exception_matches(call_result, "
            f"{cxx_string_literal(expected_type)}, "
            f"{cxx_string_literal(message_match)}, "
            f"{cxx_string_literal(message_pattern)});"
        )

    variables = cpp_variables(case)
    actual = cpp_expr(case.actual_expr, variables)
    if case.kind == "eq":
        expected = cpp_literal(case.expected)
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            f"        auto expected = {expected};\n"
            f"        passed = bcg::deep_equal(actual, expected, {cpp_tolerance(case, default_abs_tol)});\n"
            "    }"
        )
    if case.kind == "ne":
        expected = cpp_literal(case.expected)
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            f"        auto expected = {expected};\n"
            f"        passed = !bcg::deep_equal(actual, expected, {cpp_tolerance(case, default_abs_tol)});\n"
            "    }"
        )
    if case.kind == "isclose":
        expected = cpp_literal(case.expected)
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            f"        auto expected = {expected};\n"
            f"        passed = bcg::numeric_close(actual, expected, {cpp_specific_tolerance(case.abs_tol, case.rel_tol)});\n"
            "    }"
        )
    if case.kind == "absdiff":
        expected = cpp_literal(case.expected)
        comparator = "<" if case.comparison == "abs_lt" else "<="
        abs_tol = numeric_literal(case.abs_tol, "L")
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            f"        auto expected = {expected};\n"
            "        auto diff = bcg::abs_value(actual - expected);\n"
            f"        passed = diff {comparator} {abs_tol};\n"
            "    }"
        )
    if case.kind == "truthy":
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            "        passed = bcg::truthy(actual);\n"
            "    }"
        )
    if case.kind == "not":
        return (
            "if (!call_result.raised) {\n"
            "        auto& result = *call_result.value;\n"
            f"        auto actual = {actual};\n"
            "        passed = !bcg::truthy(actual);\n"
            "    }"
        )
    raise ExecutionSetupError(f"unsupported compiled test kind: {case.kind}")


CPP_HARNESS_SUPPORT = r'''
#include <algorithm>
#include <cmath>
#include <cctype>
#include <deque>
#include <exception>
#include <fstream>
#include <functional>
#include <iterator>
#include <map>
#include <memory>
#include <numeric>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>
#include <cxxabi.h>

namespace bcg {
struct Void {};

inline bool operator==(const Void&, const Void&) {
    return true;
}

struct Tolerance {
    bool has_abs;
    long double abs_tol;
    bool has_rel;
    long double rel_tol;
};

template <typename T>
struct is_optional : std::false_type {};
template <typename T>
struct is_optional<std::optional<T>> : std::true_type {};

template <typename T>
struct is_vector : std::false_type {};
template <typename T, typename A>
struct is_vector<std::vector<T, A>> : std::true_type {};

template <typename T>
struct is_deque : std::false_type {};
template <typename T, typename A>
struct is_deque<std::deque<T, A>> : std::true_type {};

template <typename T>
struct is_set : std::false_type {};
template <typename K, typename C, typename A>
struct is_set<std::set<K, C, A>> : std::true_type {};

template <typename T>
struct is_map : std::false_type {};
template <typename K, typename V, typename C, typename A>
struct is_map<std::map<K, V, C, A>> : std::true_type {};

template <typename T>
struct is_tuple : std::false_type {};
template <typename... T>
struct is_tuple<std::tuple<T...>> : std::true_type {};

template <typename T>
constexpr bool is_numeric_v = std::is_arithmetic_v<std::decay_t<T>> && !std::is_same_v<std::decay_t<T>, bool>;

template <typename A, typename B, typename = void>
struct is_equality_comparable : std::false_type {};
template <typename A, typename B>
struct is_equality_comparable<A, B, std::void_t<decltype(std::declval<A>() == std::declval<B>())>> : std::true_type {};

template <typename A, typename B>
bool deep_equal(const A& left, const B& right, Tolerance tolerance);

template <std::size_t Index, typename A, typename B>
bool tuple_equal(const A& left, const B& right, Tolerance tolerance) {
    if constexpr (Index == std::tuple_size_v<std::decay_t<A>>) {
        return true;
    } else {
        return deep_equal(std::get<Index>(left), std::get<Index>(right), tolerance)
            && tuple_equal<Index + 1>(left, right, tolerance);
    }
}

template <typename A, typename B>
bool numeric_close(const A& left, const B& right, Tolerance tolerance) {
    long double l = static_cast<long double>(left);
    long double r = static_cast<long double>(right);
    long double absolute = tolerance.has_abs ? tolerance.abs_tol : 0.0L;
    long double relative = tolerance.has_rel ? tolerance.rel_tol : 0.0L;
    long double diff = std::fabs(l - r);
    long double limit = std::max(absolute, relative * std::max(std::fabs(l), std::fabs(r)));
    return diff <= limit;
}

template <typename A, typename B>
bool deep_equal(const A& left, const B& right, Tolerance tolerance) {
    using Left = std::decay_t<A>;
    using Right = std::decay_t<B>;
    if constexpr (is_numeric_v<Left> && is_numeric_v<Right>) {
        if (tolerance.has_abs || tolerance.has_rel) {
            return numeric_close(left, right, tolerance);
        }
        return left == right;
    } else if constexpr (is_optional<Left>::value && is_optional<Right>::value) {
        if (left.has_value() != right.has_value()) {
            return false;
        }
        return !left.has_value() || deep_equal(*left, *right, tolerance);
    } else if constexpr ((is_vector<Left>::value || is_deque<Left>::value) && (is_vector<Right>::value || is_deque<Right>::value)) {
        if (left.size() != right.size()) {
            return false;
        }
        auto left_it = left.begin();
        auto right_it = right.begin();
        for (; left_it != left.end(); ++left_it, ++right_it) {
            if (!deep_equal(*left_it, *right_it, tolerance)) {
                return false;
            }
        }
        return true;
    } else if constexpr (is_set<Left>::value && is_set<Right>::value) {
        if (left.size() != right.size()) {
            return false;
        }
        std::vector<bool> matched(right.size(), false);
        for (const auto& left_item : left) {
            std::size_t index = 0;
            bool found = false;
            for (const auto& right_item : right) {
                if (!matched[index] && deep_equal(left_item, right_item, tolerance)) {
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
    } else if constexpr (is_map<Left>::value && is_map<Right>::value) {
        if (left.size() != right.size()) {
            return false;
        }
        std::vector<bool> matched(right.size(), false);
        for (const auto& left_entry : left) {
            std::size_t index = 0;
            bool found = false;
            for (const auto& right_entry : right) {
                if (!matched[index]
                    && deep_equal(left_entry.first, right_entry.first, tolerance)
                    && deep_equal(left_entry.second, right_entry.second, tolerance)) {
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
    } else if constexpr (is_tuple<Left>::value && is_tuple<Right>::value) {
        if constexpr (std::tuple_size_v<Left> != std::tuple_size_v<Right>) {
            return false;
        } else {
            return tuple_equal<0>(left, right, tolerance);
        }
    } else if constexpr (is_equality_comparable<Left, Right>::value) {
        return left == right;
    } else {
        return false;
    }
}

template <typename T>
bool truthy(const T& value) {
    using Value = std::decay_t<T>;
    if constexpr (std::is_same_v<Value, bool>) {
        return value;
    } else if constexpr (is_numeric_v<Value>) {
        return value != 0;
    } else if constexpr (is_optional<Value>::value) {
        return value.has_value() && truthy(*value);
    } else if constexpr (is_vector<Value>::value || is_deque<Value>::value || is_set<Value>::value || is_map<Value>::value || std::is_same_v<Value, std::string>) {
        return !value.empty();
    } else if constexpr (std::is_same_v<Value, Void>) {
        return false;
    } else {
        return true;
    }
}

template <typename C>
int len_value(const C& value) {
    return static_cast<int>(value.size());
}

template <typename T>
auto abs_value(const T& value) {
    using std::abs;
    return abs(value);
}

template <typename T>
auto sorted_value(T value) {
    std::sort(value.begin(), value.end());
    return value;
}

template <typename T>
auto set_value(const T& value) {
    using Item = typename T::value_type;
    return std::set<Item>(value.begin(), value.end());
}

template <typename T>
auto sum_value(const T& value) {
    using Item = typename T::value_type;
    Item total{};
    for (const auto& item : value) {
        total += item;
    }
    return total;
}

template <typename T>
auto max_value(const T& value) {
    return *std::max_element(value.begin(), value.end());
}

template <typename T>
auto min_value(const T& value) {
    return *std::min_element(value.begin(), value.end());
}

template <typename T>
std::string str_value(const T& value) {
    if constexpr (std::is_same_v<std::decay_t<T>, std::string>) {
        return value;
    } else if constexpr (std::is_same_v<std::decay_t<T>, const char*>) {
        return std::string(value);
    } else if constexpr (std::is_same_v<std::decay_t<T>, bool>) {
        return value ? "True" : "False";
    } else if constexpr (is_numeric_v<T>) {
        return std::to_string(value);
    } else {
        return "<value>";
    }
}

template <typename T>
auto float_value(const T& value) {
    return static_cast<long double>(value);
}

template <typename T>
auto int_value(const T& value) {
    return static_cast<int>(value);
}

template <typename T>
auto bool_value(const T& value) {
    return truthy(value);
}

template <typename T>
auto frozenset_value(const T& value) {
    return set_value(value);
}

template <typename T>
auto tuple_value(const T& value) {
    return value;
}

template <typename T>
auto list_value(const T& value) {
    return value;
}

template <typename T>
std::set<typename T::value_type> set_from(const T& value) {
    return std::set<typename T::value_type>(value.begin(), value.end());
}

template <typename T>
auto map_from(const T& pairs) {
    using Pair = typename T::value_type;
    using Key = typename Pair::first_type;
    using Value = typename Pair::second_type;
    std::map<Key, Value> result;
    for (const auto& pair : pairs) {
        result.insert(pair);
    }
    return result;
}

template <typename A, typename B>
auto binary_add(A left, B right) {
    if constexpr ((is_vector<std::decay_t<A>>::value || is_deque<std::decay_t<A>>::value) && std::is_same_v<std::decay_t<A>, std::decay_t<B>>) {
        left.insert(left.end(), right.begin(), right.end());
        return left;
    } else {
        return left + right;
    }
}

template <typename A, typename B> auto binary_sub(A left, B right) { return left - right; }
template <typename A, typename B> auto binary_mult(A left, B right) { return left * right; }
template <typename A, typename B> auto binary_truediv(A left, B right) { return left / right; }
template <typename A, typename B> auto binary_floordiv(A left, B right) { return std::floor(left / right); }
template <typename A, typename B> auto binary_mod(A left, B right) { return left % right; }
template <typename A, typename B> auto binary_pow(A left, B right) { return std::pow(left, right); }

template <typename A, typename B> bool compare_eq(const A& left, const B& right) { return deep_equal(left, right, Tolerance{false, 0.0L, false, 0.0L}); }
template <typename A, typename B> bool compare_ne(const A& left, const B& right) { return !compare_eq(left, right); }
template <typename A, typename B> bool compare_lt(const A& left, const B& right) { return left < right; }
template <typename A, typename B> bool compare_lte(const A& left, const B& right) { return left <= right; }
template <typename A, typename B> bool compare_gt(const A& left, const B& right) { return left > right; }
template <typename A, typename B> bool compare_gte(const A& left, const B& right) { return left >= right; }

template <typename Container, typename Item>
bool contains_value(const Container& container, const Item& item) {
    using C = std::decay_t<Container>;
    if constexpr (std::is_same_v<C, std::string>) {
        if constexpr (std::is_same_v<std::decay_t<Item>, std::string>) {
            return container.find(item) != std::string::npos;
        } else {
            return false;
        }
    } else if constexpr (is_map<C>::value) {
        for (const auto& entry : container) {
            if (deep_equal(entry.first, item, Tolerance{false, 0.0L, false, 0.0L})) {
                return true;
            }
        }
        return false;
    } else {
        for (const auto& value : container) {
            if (deep_equal(value, item, Tolerance{false, 0.0L, false, 0.0L})) {
                return true;
            }
        }
        return false;
    }
}

template <typename A, typename B> bool compare_in(const A& left, const B& right) { return contains_value(right, left); }
template <typename A, typename B> bool compare_not_in(const A& left, const B& right) { return !contains_value(right, left); }

inline std::string upper_method(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return value;
}

inline std::string lower_method(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

inline std::string strip_chars(std::string value, const std::string& chars, bool left, bool right) {
    auto should_strip = [&](char ch) {
        return chars.empty() ? std::isspace(static_cast<unsigned char>(ch)) != 0 : chars.find(ch) != std::string::npos;
    };
    if (left) {
        value.erase(value.begin(), std::find_if(value.begin(), value.end(), [&](char ch) { return !should_strip(ch); }));
    }
    if (right) {
        value.erase(std::find_if(value.rbegin(), value.rend(), [&](char ch) { return !should_strip(ch); }).base(), value.end());
    }
    return value;
}

inline std::string strip_method(std::string value) { return strip_chars(value, "", true, true); }
inline std::string strip_method(std::string value, std::string chars) { return strip_chars(value, chars, true, true); }
inline std::string lstrip_method(std::string value) { return strip_chars(value, "", true, false); }
inline std::string lstrip_method(std::string value, std::string chars) { return strip_chars(value, chars, true, false); }
inline std::string rstrip_method(std::string value) { return strip_chars(value, "", false, true); }
inline std::string rstrip_method(std::string value, std::string chars) { return strip_chars(value, chars, false, true); }
inline bool startswith_method(const std::string& value, const std::string& prefix) { return value.rfind(prefix, 0) == 0; }
inline bool endswith_method(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}
inline int find_method(const std::string& value, const std::string& needle) {
    auto pos = value.find(needle);
    return pos == std::string::npos ? -1 : static_cast<int>(pos);
}
inline int count_method(const std::string& value, const std::string& needle) {
    if (needle.empty()) {
        return static_cast<int>(value.size()) + 1;
    }
    int count = 0;
    std::size_t pos = 0;
    while ((pos = value.find(needle, pos)) != std::string::npos) {
        ++count;
        pos += needle.size();
    }
    return count;
}
inline std::string replace_method(std::string value, const std::string& needle, const std::string& replacement) {
    std::size_t pos = 0;
    while ((pos = value.find(needle, pos)) != std::string::npos) {
        value.replace(pos, needle.size(), replacement);
        pos += replacement.size();
    }
    return value;
}
inline std::vector<std::string> split_method(const std::string& value) {
    std::istringstream stream(value);
    std::vector<std::string> result;
    std::string item;
    while (stream >> item) {
        result.push_back(item);
    }
    return result;
}
inline std::vector<std::string> split_method(const std::string& value, const std::string& sep) {
    std::vector<std::string> result;
    std::size_t pos = 0;
    while (true) {
        auto found = value.find(sep, pos);
        if (found == std::string::npos) {
            result.push_back(value.substr(pos));
            return result;
        }
        result.push_back(value.substr(pos, found - pos));
        pos = found + sep.size();
    }
}
inline std::vector<std::string> split_method(const std::string& value, const std::string& sep, int max_split) {
    if (max_split < 0) {
        return split_method(value, sep);
    }
    std::vector<std::string> result;
    std::size_t pos = 0;
    for (int index = 0; index < max_split; ++index) {
        auto found = value.find(sep, pos);
        if (found == std::string::npos) {
            result.push_back(value.substr(pos));
            return result;
        }
        result.push_back(value.substr(pos, found - pos));
        pos = found + sep.size();
    }
    result.push_back(value.substr(pos));
    return result;
}
inline std::string join_method(const std::string& sep, const std::vector<std::string>& values) {
    std::string result;
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index) {
            result += sep;
        }
        result += values[index];
    }
    return result;
}

template <typename Container, typename Index>
auto subscript_value(const Container& value, Index index) {
    using C = std::decay_t<Container>;
    if constexpr (is_map<C>::value) {
        for (const auto& entry : value) {
            if (deep_equal(entry.first, index, Tolerance{false, 0.0L, false, 0.0L})) {
                return entry.second;
            }
        }
        throw std::out_of_range("key not found");
    } else {
        int numeric = static_cast<int>(index);
        int resolved = numeric < 0 ? static_cast<int>(value.size()) + numeric : numeric;
        return value.at(static_cast<std::size_t>(resolved));
    }
}

inline std::string subscript_value(const std::string& value, int index) {
    int resolved = index < 0 ? static_cast<int>(value.size()) + index : index;
    return std::string(1, value.at(static_cast<std::size_t>(resolved)));
}

template <typename Container>
auto slice_value(const Container& value, std::optional<int> lower, std::optional<int> upper, std::optional<int> step) {
    using Item = typename Container::value_type;
    std::vector<Item> result;
    int actual_step = step.value_or(1);
    if (actual_step == 0) {
        throw std::invalid_argument("slice step cannot be zero");
    }
    int size = static_cast<int>(value.size());
    int start = lower.value_or(actual_step > 0 ? 0 : size - 1);
    int stop = upper.value_or(actual_step > 0 ? size : -1);
    if (start < 0) start += size;
    if (stop < 0) stop += size;
    if (actual_step > 0) {
        for (int index = start; index < stop && index < size; index += actual_step) {
            result.push_back(value.at(static_cast<std::size_t>(index)));
        }
    } else {
        for (int index = start; index > stop && index >= 0; index += actual_step) {
            result.push_back(value.at(static_cast<std::size_t>(index)));
        }
    }
    return result;
}

inline std::string slice_value(const std::string& value, std::optional<int> lower, std::optional<int> upper, std::optional<int> step) {
    auto chars = std::vector<char>(value.begin(), value.end());
    auto sliced = slice_value(chars, lower, upper, step);
    return std::string(sliced.begin(), sliced.end());
}

template <typename T>
using Stored = std::conditional_t<std::is_void_v<T>, Void, T>;

template <typename T>
struct CallResult {
    bool raised = false;
    std::optional<T> value;
    std::string exception_type;
    std::string message;
};

inline std::string demangle(const char* name) {
    int status = 0;
    std::unique_ptr<char, void(*)(void*)> demangled(abi::__cxa_demangle(name, nullptr, nullptr, &status), std::free);
    return status == 0 && demangled ? std::string(demangled.get()) : std::string(name);
}

template <typename F>
auto call(F&& function) {
    using Raw = decltype(function());
    using Result = Stored<Raw>;
    CallResult<Result> outcome;
    try {
        if constexpr (std::is_void_v<Raw>) {
            function();
            outcome.value = Void{};
        } else {
            outcome.value = function();
        }
    } catch (const std::exception& error) {
        outcome.raised = true;
        outcome.exception_type = demangle(typeid(error).name());
        outcome.message = error.what();
    } catch (...) {
        outcome.raised = true;
        outcome.exception_type = "Exception";
        outcome.message = "";
    }
    return outcome;
}

template <typename T>
bool exception_matches(const CallResult<T>& outcome, const std::string& expected_type, const std::string& message_mode, const std::string& pattern) {
    if (!outcome.raised) {
        return false;
    }
    if (!expected_type.empty()
        && expected_type != "Exception"
        && outcome.exception_type != expected_type
        && outcome.exception_type.find(expected_type) == std::string::npos) {
        return false;
    }
    if (message_mode.empty()) {
        return true;
    }
    if (message_mode == "contains") {
        return outcome.message.find(pattern) != std::string::npos;
    }
    if (message_mode == "regex") {
        try {
            return std::regex_search(outcome.message, std::regex(pattern));
        } catch (const std::regex_error&) {
            return false;
        }
    }
    return false;
}
}
'''


def cpp_include_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def render_cpp_harness(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
) -> str:
    arg_decls = "\n    ".join(
        f"auto arg{index} = {cpp_literal(value)};"
        for index, value in enumerate(case.args)
    )
    call_args = ", ".join(f"arg{index}" for index in range(len(case.args)))
    match_code = cpp_match_code(case, default_abs_tol)
    return (
        CPP_HARNESS_SUPPORT
        + f'\n#include "{cpp_include_path(solution_path)}"\n\n'
        + textwrap.dedent(
            f"""
            int main(int argc, char** argv) {{
                if (argc < 2) {{
                    return 2;
                }}
                {arg_decls}
                auto call_result = bcg::call([&]() {{ return {entrypoint}({call_args}); }});
                bool passed = false;
                {match_code}
                std::ofstream result_file(argv[1]);
                result_file << "{{\\"passed\\":" << (passed ? "true" : "false") << "}}";
                return 0;
            }}
            """
        )
    )


RUST_HARNESS_SUPPORT = r'''
mod bcg {
    use std::collections::{HashMap, HashSet};
    use std::hash::Hash;

    pub fn set_from<T: Eq + Hash>(items: Vec<T>) -> HashSet<T> {
        items.into_iter().collect()
    }

    pub fn map_from<K: Eq + Hash, V>(items: Vec<(K, V)>) -> HashMap<K, V> {
        items.into_iter().collect()
    }

    pub fn numeric_close(left: f64, right: f64, abs_tol: Option<f64>, rel_tol: Option<f64>) -> bool {
        let absolute = abs_tol.unwrap_or(0.0);
        let relative = rel_tol.unwrap_or(0.0);
        let diff = (left - right).abs();
        let limit = absolute.max(relative * left.abs().max(right.abs()));
        diff <= limit
    }

    pub trait PyTruthy {
        fn py_truthy(&self) -> bool;
    }

    impl PyTruthy for bool { fn py_truthy(&self) -> bool { *self } }
    impl PyTruthy for i32 { fn py_truthy(&self) -> bool { *self != 0 } }
    impl PyTruthy for i64 { fn py_truthy(&self) -> bool { *self != 0 } }
    impl PyTruthy for f64 { fn py_truthy(&self) -> bool { *self != 0.0 && !self.is_nan() } }
    impl PyTruthy for String { fn py_truthy(&self) -> bool { !self.is_empty() } }
    impl<T> PyTruthy for Vec<T> { fn py_truthy(&self) -> bool { !self.is_empty() } }
    impl<T> PyTruthy for Option<T> { fn py_truthy(&self) -> bool { self.is_some() } }
    impl<T: Eq + Hash> PyTruthy for HashSet<T> { fn py_truthy(&self) -> bool { !self.is_empty() } }
    impl<K: Eq + Hash, V> PyTruthy for HashMap<K, V> { fn py_truthy(&self) -> bool { !self.is_empty() } }

    pub fn truthy<T: PyTruthy>(value: &T) -> bool { value.py_truthy() }
    pub fn len<T>(value: &Vec<T>) -> i32 { value.len() as i32 }
    pub fn sorted<T: Ord + Clone>(value: &Vec<T>) -> Vec<T> {
        let mut output = value.clone();
        output.sort();
        output
    }
    pub fn sorted_f64(value: &Vec<f64>) -> Vec<f64> {
        let mut output = value.clone();
        output.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        output
    }
    pub fn contains<T: PartialEq>(container: &Vec<T>, item: &T) -> bool {
        container.iter().any(|value| value == item)
    }
    pub fn upper(value: &String) -> String { value.to_uppercase() }
    pub fn lower(value: &String) -> String { value.to_lowercase() }
    pub fn strip(value: &String) -> String { value.trim().to_string() }
    pub fn startswith(value: &String, prefix: &String) -> bool { value.starts_with(prefix) }
    pub fn endswith(value: &String, suffix: &String) -> bool { value.ends_with(suffix) }
    pub fn find(value: &String, needle: &String) -> i32 {
        value.find(needle).map(|index| index as i32).unwrap_or(-1)
    }
}
'''


def rust_expr(expr: dict[str, Any], variables: dict[str, str]) -> str:
    op = expr["op"]
    if op == "result":
        return "result.clone()"
    if op == "var":
        return f"{variables[expr['name']]}.clone()"
    if op == "value":
        return rust_literal(expr["value"])
    if op in {"list", "tuple"}:
        items = ", ".join(rust_expr(item, variables) for item in expr["items"])
        return f"vec![{items}]"
    if op == "set":
        items = ", ".join(rust_expr(item, variables) for item in expr["items"])
        return f"bcg::set_from(vec![{items}])"
    if op == "unary":
        operand = rust_expr(expr["operand"], variables)
        if expr["operator"] == "not":
            return f"!({operand})"
        if expr["operator"] == "usub":
            return f"-({operand})"
        return operand
    if op == "binary":
        left = rust_expr(expr["left"], variables)
        right = rust_expr(expr["right"], variables)
        operator = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }.get(expr["operator"])
        if operator is None:
            return f"({left}).pow({right} as u32)"
        return f"({left} {operator} {right})"
    if op == "compare":
        left = rust_expr(expr["left"], variables)
        right = rust_expr(expr["right"], variables)
        operator = expr["operator"]
        if operator == "eq":
            return f"({left} == {right})"
        if operator == "ne":
            return f"({left} != {right})"
        if operator == "lt":
            return f"({left} < {right})"
        if operator == "lte":
            return f"({left} <= {right})"
        if operator == "gt":
            return f"({left} > {right})"
        if operator == "gte":
            return f"({left} >= {right})"
        if operator == "in":
            return f"bcg::contains(&{right}, &{left})"
        if operator == "not_in":
            return f"!bcg::contains(&{right}, &{left})"
    if op == "call":
        name = expr["name"]
        args = [rust_expr(arg, variables) for arg in expr["args"]]
        if name in {"list", "tuple"}:
            return args[0]
        if name == "len":
            return f"bcg::len(&{args[0]})"
        if name == "sorted":
            return f"bcg::sorted(&{args[0]})"
        if name == "abs":
            return f"({args[0]}).abs()"
        if name == "bool":
            return f"({args[0]})"
        if name == "int":
            return f"({args[0]} as i32)"
        if name == "float":
            return f"({args[0]} as f64)"
        if name == "str":
            return f"format!(\"{{:?}}\", {args[0]})"
        if name in {"set", "frozenset"}:
            return f"bcg::set_from({args[0]})"
        if name == "sum":
            return f"({args[0]}).iter().sum()"
        if name == "max":
            return f"*({args[0]}).iter().max().unwrap()"
        if name == "min":
            return f"*({args[0]}).iter().min().unwrap()"
    if op == "method":
        receiver = rust_expr(expr["receiver"], variables)
        args = [rust_expr(arg, variables) for arg in expr["args"]]
        name = expr["name"]
        if name == "upper":
            return f"bcg::upper(&{receiver})"
        if name == "lower":
            return f"bcg::lower(&{receiver})"
        if name == "strip":
            return f"bcg::strip(&{receiver})"
        if name == "startswith":
            return f"bcg::startswith(&{receiver}, &{args[0]})"
        if name == "endswith":
            return f"bcg::endswith(&{receiver}, &{args[0]})"
        if name == "find":
            return f"bcg::find(&{receiver}, &{args[0]})"
        if name == "is_empty":
            return f"({receiver}).is_empty()"
    if op == "subscript":
        return f"({rust_expr(expr['value'], variables)})[{rust_expr(expr['index'], variables)} as usize].clone()"
    raise ExecutionSetupError(f"unsupported Rust expression operation: {op}")


def rust_variables(case: TestCase) -> dict[str, str]:
    variables: dict[str, str] = {}
    for name, binding in case.mutation_bindings.items():
        if binding.get("source") == "arg":
            variables[name] = f"arg{binding['index']}"
        elif binding.get("source") == "result":
            variables[name] = "result"
    return variables


def rust_call_args(case: TestCase) -> str:
    mutable_arg_indexes = {
        binding["index"]
        for binding in case.mutation_bindings.values()
        if binding.get("source") == "arg"
    }
    args: list[str] = []
    for index in range(len(case.args)):
        if index in mutable_arg_indexes:
            args.append(f"&mut arg{index}")
        else:
            args.append(f"arg{index}.clone()")
    return ", ".join(args)


def rust_match_code(case: TestCase, default_abs_tol: float | None) -> str:
    if case.kind == "raises":
        pattern = "" if case.message_pattern is None else case.message_pattern
        mode = "" if case.message_match is None else case.message_match
        return (
            "let mut passed = call_result.is_err();\n"
            f"    let message_mode = {rust_string_literal(mode)};\n"
            f"    let message_pattern = {rust_string_literal(pattern)};\n"
            "    if passed && !message_mode.is_empty() {\n"
            "        let payload = call_result.err().unwrap();\n"
            "        let message = if let Some(text) = payload.downcast_ref::<&str>() {\n"
            "            text.to_string()\n"
            "        } else if let Some(text) = payload.downcast_ref::<String>() {\n"
            "            text.clone()\n"
            "        } else {\n"
            "            String::new()\n"
            "        };\n"
            "        passed = if message_mode == \"contains\" { message.contains(&message_pattern) } else { message.contains(&message_pattern) };\n"
            "    }\n"
        )
    variables = rust_variables(case)
    actual = rust_expr(case.actual_expr, variables)
    if case.kind in {"eq", "ne"}:
        expected = rust_literal(case.expected)
        operator = "==" if case.kind == "eq" else "!="
        if case.abs_tol is not None or default_abs_tol is not None or case.rel_tol is not None:
            abs_tol = case.abs_tol if case.abs_tol is not None else default_abs_tol
            abs_expr = "None" if abs_tol is None else f"Some({numeric_literal(abs_tol)})"
            rel_expr = "None" if case.rel_tol is None else f"Some({numeric_literal(case.rel_tol)})"
            base = f"bcg::numeric_close(actual as f64, expected as f64, {abs_expr}, {rel_expr})"
            if case.kind == "ne":
                base = f"!{base}"
            return (
                "let mut passed = false;\n"
                "    if let Ok(result) = call_result {\n"
                f"        let actual = {actual};\n"
                f"        let expected = {expected};\n"
                f"        passed = {base};\n"
                "    }\n"
            )
        return (
            "let mut passed = false;\n"
            "    if let Ok(result) = call_result {\n"
            f"        let actual = {actual};\n"
            f"        let expected = {expected};\n"
            f"        passed = actual {operator} expected;\n"
            "    }\n"
        )
    if case.kind == "isclose":
        expected = rust_literal(case.expected)
        abs_expr = "None" if case.abs_tol is None else f"Some({numeric_literal(case.abs_tol)})"
        rel_expr = "None" if case.rel_tol is None else f"Some({numeric_literal(case.rel_tol)})"
        return (
            "let mut passed = false;\n"
            "    if let Ok(result) = call_result {\n"
            f"        let actual = {actual};\n"
            f"        let expected = {expected};\n"
            f"        passed = bcg::numeric_close(actual as f64, expected as f64, {abs_expr}, {rel_expr});\n"
            "    }\n"
        )
    if case.kind == "absdiff":
        expected = rust_literal(case.expected)
        comparator = "<" if case.comparison == "abs_lt" else "<="
        return (
            "let mut passed = false;\n"
            "    if let Ok(result) = call_result {\n"
            f"        let actual = {actual};\n"
            f"        let expected = {expected};\n"
            f"        passed = ((actual as f64) - (expected as f64)).abs() {comparator} {numeric_literal(case.abs_tol)};\n"
            "    }\n"
        )
    if case.kind == "truthy":
        return (
            "let mut passed = false;\n"
            "    if let Ok(result) = call_result {\n"
            f"        let actual = {actual};\n"
            "        passed = bcg::truthy(&actual);\n"
            "    }\n"
        )
    if case.kind == "not":
        return (
            "let mut passed = false;\n"
            "    if let Ok(result) = call_result {\n"
            f"        let actual = {actual};\n"
            "        passed = !bcg::truthy(&actual);\n"
            "    }\n"
        )
    raise ExecutionSetupError(f"unsupported compiled test kind: {case.kind}")


def render_rust_harness(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
) -> str:
    arg_decls = "\n    ".join(
        f"let mut arg{index}: {rust_type(value_shape(value))} = {rust_literal(value)};"
        for index, value in enumerate(case.args)
    )
    call_args = rust_call_args(case)
    match_code = rust_match_code(case, default_abs_tol)
    return (
        RUST_HARNESS_SUPPORT
        + f'\ninclude!({rust_string_literal(str(solution_path))});\n\n'
        + textwrap.dedent(
            f"""
            fn main() {{
                let result_path = std::env::args().nth(1).unwrap_or_default();
                {arg_decls}
                let call_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {entrypoint}({call_args})));
                {match_code}
                std::fs::write(result_path, format!("{{\\"passed\\":{{}}}}", if passed {{ "true" }} else {{ "false" }})).unwrap();
            }}
            """
        )
    )


def run_compiled_executable(
    executable: Path,
    case: TestCase,
    cwd: Path,
) -> bool:
    result_file = cwd / "result.json"
    try:
        proc = subprocess.run(
            [str(executable), str(result_file)],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0 or not result_file.is_file():
        return False
    try:
        data = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    passed = data.get("passed") is True
    if case.expect_stdout is not None:
        passed = passed and proc.stdout == case.expect_stdout
    if case.expect_stderr is not None:
        passed = passed and proc.stderr == case.expect_stderr
    return passed


def run_cpp_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
) -> bool:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        raise ExecutionSetupError("C++ compiler not found")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        source = workdir / "tester.cpp"
        executable = workdir / "tester"
        source.write_text(
            render_cpp_harness(solution_path, entrypoint, case, default_abs_tol),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [compiler, "-std=c++17", str(source), "-o", str(executable)],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutionSetupError("C++ compile failed") from exc
        if proc.returncode != 0:
            raise ExecutionSetupError("C++ compile failed")
        return run_compiled_executable(executable, case, workdir)


def run_rust_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
) -> bool:
    compiler = shutil.which("rustc")
    if compiler is None:
        raise ExecutionSetupError("Rust compiler not found")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        source = workdir / "tester.rs"
        executable = workdir / "tester"
        source.write_text(
            render_rust_harness(solution_path, entrypoint, case, default_abs_tol),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [compiler, "--edition=2021", str(source), "-o", str(executable)],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutionSetupError("Rust compile failed") from exc
        if proc.returncode != 0:
            raise ExecutionSetupError("Rust compile failed")
        return run_compiled_executable(executable, case, workdir)


def run_python_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
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
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(proc)


PYTHON_CASE_RUNNER = r'''
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
    decoded["mutation_bindings"] = case.get("mutation_bindings") or {}
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
    if variables is None:
        variables = {}
    op = expr["op"]
    if op == "result":
        return result
    if op == "var":
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
        return _eval_call(
            expr["name"],
            [_eval_expr(arg, result, variables) for arg in expr["args"]],
        )
    if op == "method":
        receiver = _eval_expr(expr["receiver"], result, variables)
        args = [_eval_expr(arg, result, variables) for arg in expr["args"]]
        return _eval_method(expr["name"], receiver, args)
    if op == "subscript":
        return _eval_expr(expr["value"], result, variables)[
            _eval_expr(expr["index"], result, variables)
        ]
    if op == "slice":
        value = _eval_expr(expr["value"], result, variables)
        lower = _eval_expr(expr["lower"], result, variables) if expr["lower"] is not None else None
        upper = _eval_expr(expr["upper"], result, variables) if expr["upper"] is not None else None
        step = _eval_expr(expr["step"], result, variables) if expr["step"] is not None else None
        return value[slice(lower, upper, step)]
    raise ValueError("unsupported expression operation")


def _mutation_variables(case, result):
    variables = {}
    for name, binding in case.get("mutation_bindings", {}).items():
        if binding.get("source") == "arg":
            variables[name] = case["args"][binding["index"]]
        elif binding.get("source") == "result":
            variables[name] = result
    return variables


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
        actual = _eval_expr(case["actual_expr"], value, _mutation_variables(case, value))
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

function evalExpr(expr, result, variables = {}) {
  if (expr.op === "result") {
    return result;
  }
  if (expr.op === "var") {
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

function mutationVariables(testCase, result) {
  const variables = {};
  const bindings = testCase.mutation_bindings || {};
  for (const [name, binding] of Object.entries(bindings)) {
    if (binding.source === "arg") {
      variables[name] = testCase.args[binding.index];
    } else if (binding.source === "result") {
      variables[name] = result;
    }
  }
  return variables;
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
    actual = evalExpr(
      testCase.actual_expr,
      callResult.value,
      mutationVariables(testCase, callResult.value),
    );
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
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(proc)


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
) -> bool:
    if case.kind == "loop":
        return case.loop_pass is True
    if lang == "python":
        return run_python_case(solution_path, entrypoint, case, default_abs_tol)
    if lang in {"javascript", "typescript"}:
        return run_node_case(solution_path, entrypoint, lang, case, default_abs_tol)
    if lang == "cpp":
        return run_cpp_case(solution_path, entrypoint, case, default_abs_tol)
    if lang == "rust":
        return run_rust_case(solution_path, entrypoint, case, default_abs_tol)
    return False


def aggregate_results(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None = None,
) -> dict[str, Any]:
    passed: list[str] = []
    failed: list[str] = []
    for case in cases:
        if execute_case(solution_path, lang, entrypoint, case, default_abs_tol):
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

    try:
        result = aggregate_results(Path(args.solution_path), lang, entrypoint, cases, default_abs_tol)
    except ExecutionSetupError:
        print_json_result(error_result())
        return 2
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
    test.set_defaults(func=command_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
