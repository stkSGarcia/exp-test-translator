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
LOOP_ITERATION_LIMIT = 10000
HELPER_MODULES = {"math", "re", "collections", "decimal", "pytest"}
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
    mutation_checks: list[dict[str, Any]] = field(default_factory=list)


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
    mutation_checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedRun:
    solution_path: Path
    lang: str
    entrypoint: str
    cases: list[TestCase]
    all_cases: list[TestCase]
    default_abs_tol: float | None
    per_test_timeout_ms: int | None
    total_timeout_ms: int | None


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


def parse_timeout_ms(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise DiscoveryError("invalid timeout") from exc
    if value < 0:
        raise DiscoveryError("invalid timeout")
    return value


def parse_nonnegative_int(raw: str, name: str) -> int:
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise DiscoveryError(f"invalid {name}") from exc
    if value < 0:
        raise DiscoveryError(f"invalid {name}")
    return value


def timeout_seconds(timeout_ms: int | None) -> float | None:
    return None if timeout_ms is None else timeout_ms / 1000.0


def remaining_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def combine_timeouts(*values: float | None) -> float | None:
    concrete = [value for value in values if value is not None]
    if not concrete:
        return None
    return min(concrete)


def render_tester(lang: str, entrypoint: str) -> str:
    metadata = {
        "version": METADATA_VERSION,
        "entrypoint": entrypoint,
        "lang": lang,
    }
    prefix = "#" if lang == "python" else "//"
    body = ""
    if lang == "cpp":
        body = "\n#include <optional>\n#include <stdexcept>\n// C++17 test harness body is generated at test time from discovered cases.\n"
    elif lang == "rust":
        body = "\nuse std::panic;\n// Rust test harness body is generated at test time from discovered cases.\n"
    return (
        f"{prefix} Generated by babel_code_goat.py.\n"
        f"{prefix} {METADATA_MARKER} {json_line(metadata)}\n"
        f"{body}"
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
        target_lang: str | None = None,
    ) -> None:
        self.entrypoint = entrypoint
        self.source_lines = source_lines
        self.source_path = source_path
        self.target_lang = target_lang
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
            mutation_call = self.mutation_call_from_statement(stmt)
            if mutation_call is not None:
                index = self.visit_mutation_group(body, index, mutation_call)
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
        rust_skip = any(self.is_rust_skip_decorator(decorator) for decorator in stmt.decorator_list)
        if stmt.decorator_list and not rust_skip:
            raise DiscoveryError(f"decorators are unsupported at line {stmt.lineno}")
        if rust_skip and self.target_lang == "rust":
            return
        module_aliases = self.module_aliases.copy()
        constructor_aliases = self.constructor_aliases.copy()
        env = self.env.copy()
        try:
            self.visit_body(stmt.body)
        finally:
            self.module_aliases = module_aliases
            self.constructor_aliases = constructor_aliases
            self.env = env

    def is_rust_skip_decorator(self, decorator: ast.expr) -> bool:
        if not isinstance(decorator, ast.Call):
            return False
        if not self.is_pytest_skipif(decorator.func):
            return False
        try:
            text = ast.unparse(decorator).lower()
        except Exception:
            text = ""
        return "rust" in text and "deque" in text

    def is_pytest_skipif(self, node: ast.AST) -> bool:
        if not (isinstance(node, ast.Attribute) and node.attr == "skipif"):
            return False
        mark = node.value
        return (
            isinstance(mark, ast.Attribute)
            and mark.attr == "mark"
            and isinstance(mark.value, ast.Name)
            and self.module_aliases.get(mark.value.id) == "pytest"
        )

    def visit_assign(self, stmt: ast.Assign) -> None:
        if len(stmt.targets) != 1:
            raise DiscoveryError(f"multiple assignment targets are unsupported at line {stmt.lineno}")
        value = self.parse_value(stmt.value)
        self.bind_target(stmt.targets[0], value, stmt.lineno)

    def mutation_call_from_statement(
        self,
        stmt: ast.stmt,
    ) -> tuple[int, list[Any], dict[str, dict[str, Any]]] | None:
        call: ast.Call | None = None
        assigned_name: str | None = None
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                return None
            call = stmt.value
            assigned_name = stmt.targets[0].id
        if call is None or not (
            isinstance(call.func, ast.Name) and call.func.id == self.entrypoint
        ):
            return None
        if call.keywords:
            raise DiscoveryError(f"keyword arguments are unsupported at line {stmt.lineno}")
        args = self.parse_call_args(call.args, stmt.lineno)
        tracked: dict[str, dict[str, Any]] = {}
        arg_index = 0
        for arg in call.args:
            if isinstance(arg, ast.Starred):
                value = self.parse_value(arg.value)
                arg_count = len(as_iterable_items(value, stmt.lineno, "starred argument"))
                arg_index += arg_count
                continue
            if isinstance(arg, ast.Name):
                tracked[arg.id] = {"op": "arg", "index": arg_index}
            arg_index += 1
        if assigned_name is not None:
            if assigned_name == self.entrypoint:
                raise DiscoveryError(f"assignment to entrypoint is unsupported at line {stmt.lineno}")
            tracked[assigned_name] = result_expr()
        return stmt.lineno, args, tracked

    def visit_mutation_group(
        self,
        body: list[ast.stmt],
        index: int,
        mutation_call: tuple[int, list[Any], dict[str, dict[str, Any]]],
    ) -> int:
        line_no, args, tracked = mutation_call
        next_index = index + 1
        checks: list[dict[str, Any]] = []
        while next_index < len(body) and isinstance(body[next_index], ast.Assert):
            checks.append(self.parse_mutation_assert(body[next_index], tracked))
            next_index += 1
        if not checks:
            raise DiscoveryError(f"mutation call at line {line_no} must be immediately followed by assertions")
        self.add_mutation_test(line_no, args, checks)
        return next_index

    def parse_mutation_assert(
        self,
        stmt: ast.Assert,
        tracked: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if stmt.msg is not None:
            raise DiscoveryError(f"assert messages are unsupported at line {stmt.lineno}")
        if self.count_entrypoint_calls(stmt.test):
            raise DiscoveryError(f"mutation assertion must not call {self.entrypoint} at line {stmt.lineno}")
        referenced = self.referenced_names(stmt.test)
        if not (referenced & set(tracked)):
            raise DiscoveryError(f"mutation assertion must reference mutated state at line {stmt.lineno}")
        if isinstance(stmt.test, ast.UnaryOp) and isinstance(stmt.test.op, ast.Not):
            return {
                "kind": "not",
                "actual_expr": self.parse_mutation_expression(stmt.test.operand, tracked),
                "expected": None,
                "comparison": "standard",
                "abs_tol": None,
                "rel_tol": None,
            }
        return {
            "kind": "truthy",
            "actual_expr": self.parse_mutation_expression(stmt.test, tracked),
            "expected": None,
            "comparison": "standard",
            "abs_tol": None,
            "rel_tol": None,
        }

    def referenced_names(self, node: ast.AST) -> set[str]:
        return {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        }

    def parse_mutation_expression(
        self,
        node: ast.AST,
        tracked: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name) and node.id in tracked:
            return tracked[node.id]
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return {"op": "value", "value": node.value}
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            return {"op": "value", "value": self.resolve_name(node.id, line_no)}
        if isinstance(node, ast.List):
            return {
                "op": "list",
                "items": [self.parse_mutation_expression(item, tracked) for item in node.elts],
            }
        if isinstance(node, ast.Tuple):
            return {
                "op": "tuple",
                "items": [self.parse_mutation_expression(item, tracked) for item in node.elts],
            }
        if isinstance(node, ast.Set):
            return {
                "op": "set",
                "items": [self.parse_mutation_expression(item, tracked) for item in node.elts],
            }
        if isinstance(node, ast.Dict):
            entries: list[list[dict[str, Any]]] = []
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise DiscoveryError(f"dictionary unpacking is unsupported at line {line_no}")
                entries.append(
                    [
                        self.parse_mutation_expression(key_node, tracked),
                        self.parse_mutation_expression(value_node, tracked),
                    ]
                )
            return {"op": "dict", "entries": entries}
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return {
                "op": "unary",
                "operator": UNARY_OPERATORS[type(node.op)],
                "operand": self.parse_mutation_expression(node.operand, tracked),
            }
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return {
                "op": "binary",
                "operator": BINARY_OPERATORS[type(node.op)],
                "left": self.parse_mutation_expression(node.left, tracked),
                "right": self.parse_mutation_expression(node.right, tracked),
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
                "left": self.parse_mutation_expression(node.left, tracked),
                "right": self.parse_mutation_expression(node.comparators[0], tracked),
            }
        if isinstance(node, ast.Subscript):
            value = self.parse_mutation_expression(node.value, tracked)
            if isinstance(node.slice, ast.Slice):
                return {
                    "op": "slice",
                    "value": value,
                    "lower": self.parse_mutation_expression(node.slice.lower, tracked)
                    if node.slice.lower is not None
                    else None,
                    "upper": self.parse_mutation_expression(node.slice.upper, tracked)
                    if node.slice.upper is not None
                    else None,
                    "step": self.parse_mutation_expression(node.slice.step, tracked)
                    if node.slice.step is not None
                    else None,
                }
            return {
                "op": "subscript",
                "value": value,
                "index": self.parse_mutation_expression(node.slice, tracked),
            }
        if isinstance(node, ast.Call):
            return self.parse_mutation_call_expression(node, tracked)
        raise DiscoveryError(f"unsupported expression at line {line_no}")

    def parse_mutation_call_expression(
        self,
        node: ast.Call,
        tracked: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node.func, ast.Name) and node.func.id in PRIMITIVE_FUNCTIONS:
            if node.keywords:
                raise DiscoveryError(f"primitive call keywords are unsupported at line {line_no}")
            self.validate_primitive_call(node.func.id, len(node.args), line_no)
            return {
                "op": "call",
                "name": node.func.id,
                "args": [self.parse_mutation_expression(arg, tracked) for arg in node.args],
            }
        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHODS:
            if node.keywords:
                raise DiscoveryError(f"method call keywords are unsupported at line {line_no}")
            self.validate_string_method_call(node.func.attr, len(node.args), line_no)
            return {
                "op": "method",
                "name": node.func.attr,
                "receiver": self.parse_mutation_expression(node.func.value, tracked),
                "args": [self.parse_mutation_expression(arg, tracked) for arg in node.args],
            }
        name = self.call_name(node.func)
        if name is not None:
            value = self.parse_constructor_call(node)
            return {"op": "value", "value": value}
        raise DiscoveryError(f"unsupported function call at line {line_no}")

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
    ) -> dict[str, Any]:
        line_no = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            if is_supported_scalar(node.value):
                return {"op": "value", "value": node.value}
            raise DiscoveryError(f"unsupported literal value at line {line_no}")
        if isinstance(node, ast.Name):
            return {"op": "value", "value": self.resolve_name(node.id, line_no)}
        if isinstance(node, ast.List):
            return {
                "op": "list",
                "items": [self.parse_expression(item, entrypoint_args) for item in node.elts],
            }
        if isinstance(node, ast.Tuple):
            return {
                "op": "tuple",
                "items": [self.parse_expression(item, entrypoint_args) for item in node.elts],
            }
        if isinstance(node, ast.Set):
            return {
                "op": "set",
                "items": [self.parse_expression(item, entrypoint_args) for item in node.elts],
            }
        if isinstance(node, ast.Dict):
            entries: list[list[dict[str, Any]]] = []
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise DiscoveryError(f"dictionary unpacking is unsupported at line {line_no}")
                entries.append(
                    [
                        self.parse_expression(key_node, entrypoint_args),
                        self.parse_expression(value_node, entrypoint_args),
                    ]
                )
            return {"op": "dict", "entries": entries}
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
            return {
                "op": "unary",
                "operator": UNARY_OPERATORS[type(node.op)],
                "operand": self.parse_expression(node.operand, entrypoint_args),
            }
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return {
                "op": "binary",
                "operator": BINARY_OPERATORS[type(node.op)],
                "left": self.parse_expression(node.left, entrypoint_args),
                "right": self.parse_expression(node.right, entrypoint_args),
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
                "left": self.parse_expression(node.left, entrypoint_args),
                "right": self.parse_expression(node.comparators[0], entrypoint_args),
            }
        if isinstance(node, ast.Subscript):
            return self.parse_subscript_expression(node, entrypoint_args)
        if isinstance(node, ast.Call):
            return self.parse_call_expression(node, entrypoint_args)
        raise DiscoveryError(f"unsupported expression at line {line_no}")

    def parse_call_expression(
        self,
        node: ast.Call,
        entrypoint_args: list[list[Any]],
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
                "args": [self.parse_expression(arg, entrypoint_args) for arg in node.args],
            }

        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHODS:
            if node.keywords:
                raise DiscoveryError(f"method call keywords are unsupported at line {line_no}")
            self.validate_string_method_call(node.func.attr, len(node.args), line_no)
            return {
                "op": "method",
                "name": node.func.attr,
                "receiver": self.parse_expression(node.func.value, entrypoint_args),
                "args": [self.parse_expression(arg, entrypoint_args) for arg in node.args],
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
    ) -> dict[str, Any]:
        value = self.parse_expression(node.value, entrypoint_args)
        if isinstance(node.slice, ast.Slice):
            return {
                "op": "slice",
                "value": value,
                "lower": self.parse_expression(node.slice.lower, entrypoint_args)
                if node.slice.lower is not None
                else None,
                "upper": self.parse_expression(node.slice.upper, entrypoint_args)
                if node.slice.upper is not None
                else None,
                "step": self.parse_expression(node.slice.step, entrypoint_args)
                if node.slice.step is not None
                else None,
            }
        return {
            "op": "subscript",
            "value": value,
            "index": self.parse_expression(node.slice, entrypoint_args),
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

    def add_mutation_test(
        self,
        line_no: int,
        args: list[Any],
        checks: list[dict[str, Any]],
    ) -> None:
        expectations = self.expectations_for(line_no)
        self.pending.append(
            PendingTest(
                line=line_no,
                kind="mutation",
                source_path=self.source_path,
                args=args,
                iteration_path=self.active_path,
                mutation_checks=checks,
                expect_stdout=expectations.get("expect_stdout"),
                expect_stderr=expectations.get("expect_stderr"),
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
                mutation_checks=test.mutation_checks,
            )
        )
    return cases


def test_id_base(source_path: str, line_no: int, iteration_path: tuple[int, ...]) -> str:
    suffix = "".join(f":{index}" for index in iteration_path)
    return f"{source_path}:{line_no}{suffix}"


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_generated_tester_path(path: Path) -> bool:
    return path.name in set(SUPPORTED_LANGS.values())


def is_internal_non_test_path(path: Path) -> bool:
    return is_generated_tester_path(path) or path.name == "solution.py"


def is_test_like_non_python(path: Path) -> bool:
    if path.suffix == ".py" or not path.suffix:
        return False
    name = path.name
    stem = path.stem
    return (
        name.startswith("test")
        or stem.endswith("_test")
        or stem == "tests"
        or stem.endswith("_tests")
    )


def discover_tests(
    tests_dir: Path | str,
    entrypoint: str,
    *,
    exclude_paths: set[Path] | None = None,
    target_lang: str | None = None,
) -> list[TestCase]:
    root = Path(tests_dir)
    excluded = {path.resolve() for path in (exclude_paths or set())}
    python_paths: list[Path] = []
    try:
        candidates = list(root.rglob("*"))
    except OSError as exc:
        raise DiscoveryError("cannot scan tests directory") from exc

    for path in candidates:
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise DiscoveryError("cannot scan tests directory") from exc
        if resolved in excluded or is_internal_non_test_path(path):
            continue
        if is_test_like_non_python(path):
            raise DiscoveryError(f"non-Python test-like file is unsupported: {relative_posix(path, root)}")
        if path.suffix == ".py":
            python_paths.append(path)

    cases: list[TestCase] = []
    for path in sorted(python_paths, key=lambda item: relative_posix(item, root)):
        source_path = relative_posix(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=source_path)
        except (OSError, SyntaxError) as exc:
            raise DiscoveryError(f"cannot read or parse {source_path}") from exc
        cases.extend(
            TestDiscoverer(
                entrypoint,
                source.splitlines(),
                source_path,
                target_lang,
            ).discover(tree)
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


def encode_mutation_check(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": check["kind"],
        "comparison": check.get("comparison", "standard"),
        "actual_expr": encode_expr(check["actual_expr"]),
        "expected": encode_optional_value(check.get("expected")),
        "abs_tol": encode_optional_value(check.get("abs_tol")),
        "rel_tol": encode_optional_value(check.get("rel_tol")),
    }


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
        "mutation_checks": [encode_mutation_check(check) for check in case.mutation_checks],
    }


def run_python_case(
    solution_path: Path,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout: float | None,
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
            timeout=10 if timeout is None else timeout,
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
    decoded["mutation_checks"] = []
    for check in case.get("mutation_checks", []):
        decoded["mutation_checks"].append({
            **check,
            "actual_expr": _decode_expr(check["actual_expr"]),
            "expected": _decode_value(check["expected"]),
            "abs_tol": _decode_value(check["abs_tol"]),
            "rel_tol": _decode_value(check["rel_tol"]),
        })
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


def _eval_expr(expr, result, args=None):
    if args is None:
        args = []
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


def _check_matches(check, value, args):
    kind = check["kind"]
    try:
        actual = _eval_expr(check["actual_expr"], value, args)
    except Exception:
        return False
    if kind == "eq":
        return _deep_equal(actual, check["expected"], check["abs_tol"], check["rel_tol"])
    if kind == "ne":
        return not _deep_equal(actual, check["expected"], check["abs_tol"], check["rel_tol"])
    if kind == "truthy":
        return bool(actual)
    if kind == "not":
        return not bool(actual)
    return False


def _matches(case, value, raised):
    kind = case["kind"]
    if kind == "mutation":
        if raised is not None:
            return False
        return all(_check_matches(check, value, case["args"]) for check in case["mutation_checks"])
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
    mutation_checks: (testCase.mutation_checks || []).map((check) => ({
      ...check,
      actual_expr: decodeExpr(check.actual_expr),
      expected: decodeValue(check.expected),
      abs_tol: decodeValue(check.abs_tol),
      rel_tol: decodeValue(check.rel_tol),
    })),
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

function evalExpr(expr, result, args = []) {
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
    const entries = expr.entries.map(([key, value]) => [evalExpr(key, result, args), evalExpr(value, result, args)]);
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
    return binaryValue(expr.operator, evalExpr(expr.left, result, args), evalExpr(expr.right, result, args));
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
  if (testCase.kind === "mutation") {
    if (callResult.raised) {
      return false;
    }
    return testCase.mutation_checks.every((check) => {
      let actual;
      try {
        actual = evalExpr(check.actual_expr, callResult.value, testCase.args);
      } catch (_) {
        return false;
      }
      if (check.kind === "eq") {
        return deepEqual(actual, check.expected, check.abs_tol, check.rel_tol);
      }
      if (check.kind === "ne") {
        return !deepEqual(actual, check.expected, check.abs_tol, check.rel_tol);
      }
      if (check.kind === "truthy") {
        return pyTruthy(actual);
      }
      if (check.kind === "not") {
        return !pyTruthy(actual);
      }
      return false;
    });
  }
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
    timeout: float | None,
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
            timeout=10 if timeout is None else timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return parse_subprocess_result(proc)


def cpp_string(value: str) -> str:
    return json.dumps(value)


def cpp_type_for_values(values: list[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "std::optional<int64_t>"
    inner = cpp_non_optional_type(non_null)
    if len(non_null) != len(values):
        return f"std::optional<{inner}>"
    return inner


def cpp_non_optional_type(values: list[Any]) -> str:
    if any(isinstance(value, str) for value in values):
        return "std::string"
    if any(isinstance(value, bool) for value in values):
        return "bool"
    if any(isinstance(value, (float, Decimal)) for value in values):
        return "long double"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "int64_t"
    if all(isinstance(value, (list, tuple, deque)) for value in values):
        items: list[Any] = []
        for value in values:
            items.extend(list(value))
        return f"std::vector<{cpp_type_for_values(items)}>"
    if all(isinstance(value, (set, frozenset)) for value in values):
        items = []
        for value in values:
            items.extend(list(value))
        return f"std::set<{cpp_type_for_values(items)}>"
    if all(isinstance(value, (dict, defaultdict, Counter)) for value in values):
        keys: list[Any] = []
        items: list[Any] = []
        for value in values:
            keys.extend(list(value.keys()))
            items.extend(list(value.values()))
        return f"std::map<{cpp_type_for_values(keys)}, {cpp_type_for_values(items)}>"
    return "std::string"


def cpp_literal(value: Any, type_hint: str | None = None) -> str:
    if type_hint is None:
        type_hint = cpp_type_for_values([value])
    if type_hint.startswith("std::optional<"):
        inner = type_hint[len("std::optional<"):-1]
        if value is None:
            return "std::nullopt"
        return f"{type_hint}{{{cpp_literal(value, inner)}}}"
    if value is None:
        return "std::nullopt"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"int64_t{{{value}}}"
    if isinstance(value, (float, Decimal)):
        return f"static_cast<long double>({str(value)})"
    if isinstance(value, str):
        return f"std::string{{{cpp_string(value)}}}"
    if isinstance(value, (list, tuple, deque)):
        inner = "int64_t"
        if type_hint.startswith("std::vector<") and type_hint.endswith(">"):
            inner = type_hint[len("std::vector<"):-1]
        return f"{type_hint}{{{', '.join(cpp_literal(item, inner) for item in value)}}}"
    if isinstance(value, (set, frozenset)):
        inner = "int64_t"
        if type_hint.startswith("std::set<") and type_hint.endswith(">"):
            inner = type_hint[len("std::set<"):-1]
        return f"{type_hint}{{{', '.join(cpp_literal(item, inner) for item in value)}}}"
    if isinstance(value, (dict, defaultdict, Counter)):
        key_type = "std::string"
        value_type = "int64_t"
        if type_hint.startswith("std::map<") and type_hint.endswith(">"):
            parts = split_cpp_template_args(type_hint[len("std::map<"):-1])
            if len(parts) == 2:
                key_type, value_type = parts
        entries = ", ".join(
            "{" + cpp_literal(key, key_type) + ", " + cpp_literal(item, value_type) + "}"
            for key, item in value.items()
        )
        return f"{type_hint}{{{entries}}}"
    return f"std::string{{{cpp_string(str(value))}}}"


def split_cpp_template_args(text: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    args.append(text[start:].strip())
    return args


def cpp_numeric(value: Any | None, fallback: str = "-1.0L") -> str:
    if value is None:
        return fallback
    if isinstance(value, Decimal):
        return f"static_cast<long double>({str(value)})"
    return f"static_cast<long double>({value})"


def cpp_expr(expr: dict[str, Any], result_name: str, arg_names: list[str]) -> str:
    op = expr["op"]
    if op == "result":
        return result_name
    if op == "arg":
        return arg_names[expr["index"]]
    if op == "value":
        return cpp_literal(expr["value"])
    if op in {"list", "tuple"}:
        values = [cpp_expr(item, result_name, arg_names) for item in expr["items"]]
        return f"std::vector{{{', '.join(values)}}}"
    if op == "set":
        values = [cpp_expr(item, result_name, arg_names) for item in expr["items"]]
        return f"std::set{{{', '.join(values)}}}"
    if op == "unary":
        operand = cpp_expr(expr["operand"], result_name, arg_names)
        return {"uadd": f"(+{operand})", "usub": f"(-{operand})", "not": f"(!bcg_truthy({operand}))"}[expr["operator"]]
    if op == "binary":
        left = cpp_expr(expr["left"], result_name, arg_names)
        right = cpp_expr(expr["right"], result_name, arg_names)
        operator = {
            "add": "+",
            "sub": "-",
            "mult": "*",
            "truediv": "/",
            "floordiv": "/",
            "mod": "%",
        }.get(expr["operator"])
        if operator is None:
            return f"std::pow({left}, {right})"
        return f"({left} {operator} {right})"
    if op == "compare":
        left = cpp_expr(expr["left"], result_name, arg_names)
        right = cpp_expr(expr["right"], result_name, arg_names)
        return f"bcg_compare({cpp_string(expr['operator'])}, {left}, {right})"
    if op == "call":
        args = [cpp_expr(arg, result_name, arg_names) for arg in expr["args"]]
        name = expr["name"]
        if name == "sorted":
            return f"bcg_sorted({args[0]})"
        if name == "len":
            return f"bcg_len({args[0]})"
        if name == "abs":
            return f"std::abs({args[0]})"
        if name == "sum":
            return f"bcg_sum({args[0]})"
        if name in {"list", "tuple", "set", "frozenset"}:
            return args[0]
        if name == "str":
            return f"bcg_to_string({args[0]})"
        if name == "bool":
            return f"bcg_truthy({args[0]})"
        if name == "int":
            return f"static_cast<int64_t>({args[0]})"
        if name == "float":
            return f"static_cast<long double>({args[0]})"
        if name == "min":
            return f"bcg_min({', '.join(args)})"
        if name == "max":
            return f"bcg_max({', '.join(args)})"
    if op == "method":
        receiver = cpp_expr(expr["receiver"], result_name, arg_names)
        args = [cpp_expr(arg, result_name, arg_names) for arg in expr["args"]]
        return f"bcg_method({cpp_string(expr['name'])}, {receiver}, std::vector<std::string>{{{', '.join(args)}}})"
    if op == "subscript":
        value = cpp_expr(expr["value"], result_name, arg_names)
        index = cpp_expr(expr["index"], result_name, arg_names)
        return f"bcg_subscript({value}, {index})"
    return result_name


CPP_HARNESS_PREAMBLE = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>
using namespace std;

template <typename T>
bool bcg_truthy(const optional<T>& value) { return value.has_value() && bcg_truthy(*value); }
inline bool bcg_truthy(bool value) { return value; }
inline bool bcg_truthy(const string& value) { return !value.empty(); }
template <typename T>
bool bcg_truthy(const vector<T>& value) { return !value.empty(); }
template <typename T>
bool bcg_truthy(const set<T>& value) { return !value.empty(); }
template <typename K, typename V>
bool bcg_truthy(const map<K, V>& value) { return !value.empty(); }
template <typename T>
bool bcg_truthy(const T& value) { return value != T{}; }

template <typename T>
bool bcg_is_none(const optional<T>& value) { return !value.has_value(); }
template <typename T>
bool bcg_is_none(const T&) { return false; }

template <typename A, typename B>
bool bcg_equal(const A& left, const B& right, long double abs_tol = -1.0L, long double rel_tol = -1.0L) {
    if constexpr (is_arithmetic_v<A> && is_arithmetic_v<B>) {
        if (abs_tol >= 0.0L || rel_tol >= 0.0L) {
            long double l = static_cast<long double>(left);
            long double r = static_cast<long double>(right);
            long double diff = fabsl(l - r);
            long double limit = max(abs_tol < 0.0L ? 0.0L : abs_tol, (rel_tol < 0.0L ? 0.0L : rel_tol) * max(fabsl(l), fabsl(r)));
            return diff <= limit;
        }
    }
    return left == right;
}

template <typename T>
auto bcg_sorted(T value) { sort(value.begin(), value.end()); return value; }
template <typename T>
int64_t bcg_len(const T& value) { return static_cast<int64_t>(value.size()); }
template <typename T>
auto bcg_sum(const T& value) { typename T::value_type total{}; for (const auto& item : value) total += item; return total; }
template <typename T>
T bcg_min(const T& value) { return *min_element(value.begin(), value.end()); }
template <typename T>
T bcg_max(const T& value) { return *max_element(value.begin(), value.end()); }
template <typename T>
T bcg_min(const T& left, const T& right) { return min(left, right); }
template <typename T>
T bcg_max(const T& left, const T& right) { return max(left, right); }
template <typename T>
string bcg_to_string(const T& value) { ostringstream out; out << value; return out.str(); }
inline string bcg_to_string(const string& value) { return value; }
inline string bcg_upper(string value) { transform(value.begin(), value.end(), value.begin(), ::toupper); return value; }
inline string bcg_lower(string value) { transform(value.begin(), value.end(), value.begin(), ::tolower); return value; }
inline string bcg_method(const string& name, const string& receiver, const vector<string>& args) {
    if (name == "upper") return bcg_upper(receiver);
    if (name == "lower") return bcg_lower(receiver);
    if (name == "find") { auto pos = receiver.find(args.at(0)); return to_string(pos == string::npos ? -1 : static_cast<int64_t>(pos)); }
    if (name == "strip" || name == "trim") {
        size_t start = receiver.find_first_not_of(" \t\n\r");
        size_t end = receiver.find_last_not_of(" \t\n\r");
        return start == string::npos ? string{} : receiver.substr(start, end - start + 1);
    }
    return receiver;
}
template <typename T>
auto bcg_subscript(const vector<T>& value, int64_t index) { if (index < 0) index += value.size(); return value.at(static_cast<size_t>(index)); }
inline char bcg_subscript(const string& value, int64_t index) { if (index < 0) index += value.size(); return value.at(static_cast<size_t>(index)); }
template <typename K, typename V>
auto bcg_subscript(const map<K, V>& value, const K& key) { return value.at(key); }
template <typename A, typename B>
bool bcg_contains(const A& container, const B& value) { return find(container.begin(), container.end(), value) != container.end(); }
template <typename K, typename V>
bool bcg_contains(const map<K, V>& container, const K& key) { return container.find(key) != container.end(); }
template <typename A, typename B>
bool bcg_compare(const string& op, const A& left, const B& right) {
    if (op == "eq") return bcg_equal(left, right);
    if (op == "ne") return !bcg_equal(left, right);
    if (op == "lt") return left < right;
    if (op == "lte") return left <= right;
    if (op == "gt") return left > right;
    if (op == "gte") return left >= right;
    if (op == "in") return bcg_contains(right, left);
    if (op == "not_in") return !bcg_contains(right, left);
    return false;
}
'''


def cpp_case_code(case: TestCase, entrypoint: str, default_abs_tol: float | None, arg_types: list[str]) -> str:
    lines = ["{"]
    arg_names: list[str] = []
    for index, value in enumerate(case.args):
        name = f"arg{index}"
        arg_names.append(name)
        lines.append(f"  auto {name} = {cpp_literal(value, arg_types[index])};")
    call = f"{entrypoint}({', '.join(arg_names)})"
    if case.kind == "raises":
        lines.append("  bool raised = false; std::string message;")
        lines.append(f"  try {{ (void){call}; }} catch (const std::exception& e) {{ raised = true; message = e.what(); }} catch (...) {{ raised = true; }}")
        lines.append("  passed = raised;")
        if case.message_match == "contains":
            lines.append(f"  passed = passed && message.find({cpp_string(case.message_pattern or '')}) != std::string::npos;")
    elif case.kind == "mutation":
        lines.append(f"  auto result = {call};")
        checks: list[str] = []
        for check in case.mutation_checks:
            actual = cpp_expr(check["actual_expr"], "result", arg_names)
            if check["kind"] == "not":
                checks.append(f"!bcg_truthy({actual})")
            elif check["kind"] == "truthy":
                checks.append(f"bcg_truthy({actual})")
            elif check["expected"] is None:
                checks.append(f"bcg_is_none({actual})")
            else:
                checks.append(f"bcg_equal({actual}, {cpp_literal(check['expected'])}, {cpp_numeric(check.get('abs_tol'))}, {cpp_numeric(check.get('rel_tol'))})")
        lines.append(f"  passed = {' && '.join(checks) if checks else 'false'};")
    else:
        lines.append(f"  auto result = {call};")
        actual = cpp_expr(case.actual_expr, "result", arg_names)
        if case.kind == "eq":
            if case.expected is None:
                lines.append(f"  passed = bcg_is_none({actual});")
            else:
                abs_tol = case.abs_tol if case.abs_tol is not None else default_abs_tol
                lines.append(f"  passed = bcg_equal({actual}, {cpp_literal(case.expected)}, {cpp_numeric(abs_tol)}, {cpp_numeric(case.rel_tol)});")
        elif case.kind == "ne":
            if case.expected is None:
                lines.append(f"  passed = !bcg_is_none({actual});")
            else:
                abs_tol = case.abs_tol if case.abs_tol is not None else default_abs_tol
                lines.append(f"  passed = !bcg_equal({actual}, {cpp_literal(case.expected)}, {cpp_numeric(abs_tol)}, {cpp_numeric(case.rel_tol)});")
        elif case.kind == "truthy":
            lines.append(f"  passed = bcg_truthy({actual});")
        elif case.kind == "not":
            lines.append(f"  passed = !bcg_truthy({actual});")
        elif case.kind == "isclose":
            lines.append(f"  passed = bcg_equal({actual}, {cpp_literal(case.expected)}, {cpp_numeric(case.abs_tol)}, {cpp_numeric(case.rel_tol)});")
        elif case.kind == "absdiff":
            op = "<" if case.comparison == "abs_lt" else "<="
            lines.append(f"  passed = std::abs(static_cast<long double>({actual}) - static_cast<long double>({cpp_literal(case.expected)})) {op} {cpp_numeric(case.abs_tol)};")
        else:
            lines.append("  passed = false;")
    lines.append(f"  std::cout << {cpp_string(case.id)} << \"\\t\" << (passed ? \"1\" : \"0\") << \"\\n\";")
    lines.append("}")
    return "\n".join(lines)


def run_cpp_cases(
    solution_path: Path,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None,
    run_timeout: float | None = None,
) -> set[str] | None:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        return None
    max_args = max((len(case.args) for case in cases), default=0)
    arg_types = [
        cpp_type_for_values([case.args[index] for case in cases if len(case.args) > index])
        for index in range(max_args)
    ]
    body = "\n".join(
        "passed = false; try " + cpp_case_code(case, entrypoint, default_abs_tol, arg_types) + " catch (...) { std::cout << " + cpp_string(case.id) + " << \"\\t0\\n\"; }"
        for case in cases
        if case.kind != "loop"
    )
    loop_lines = "\n".join(
        f"std::cout << {cpp_string(case.id)} << \"\\t\" << ({'true' if case.loop_pass else 'false'} ? \"1\" : \"0\") << \"\\n\";"
        for case in cases
        if case.kind == "loop"
    )
    source = (
        CPP_HARNESS_PREAMBLE
        + f"\n#include {cpp_string(str(solution_path.resolve()))}\n"
        + "\nint main() { bool passed = false;\n"
        + loop_lines
        + "\n"
        + body
        + "\nreturn 0;\n}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        harness = root / "harness.cpp"
        binary = root / "harness"
        harness.write_text(source, encoding="utf-8")
        try:
            compile_proc = subprocess.run(
                [compiler, "-std=c++17", str(harness), "-o", str(binary)],
                text=True,
                capture_output=True,
                timeout=20,
            )
            if compile_proc.returncode != 0:
                return None
            run_proc = subprocess.run(
                [str(binary)],
                text=True,
                capture_output=True,
                timeout=10 if run_timeout is None else run_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    if run_proc.returncode != 0:
        return None
    return parse_compiled_output(run_proc.stdout)


def rust_string(value: str) -> str:
    return json.dumps(value)


def rust_type_for_values(values: list[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "Option<i64>"
    inner = rust_non_option_type(non_null)
    if len(non_null) != len(values):
        return f"Option<{inner}>"
    return inner


def rust_non_option_type(values: list[Any]) -> str:
    if any(isinstance(value, str) for value in values):
        return "String"
    if any(isinstance(value, bool) for value in values):
        return "bool"
    if any(isinstance(value, (float, Decimal)) for value in values):
        return "f64"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "i64"
    if all(isinstance(value, (list, tuple, deque)) for value in values):
        items: list[Any] = []
        for value in values:
            items.extend(list(value))
        return f"Vec<{rust_type_for_values(items)}>"
    if all(isinstance(value, (set, frozenset)) for value in values):
        items = []
        for value in values:
            items.extend(list(value))
        return f"HashSet<{rust_type_for_values(items)}>"
    if all(isinstance(value, (dict, defaultdict, Counter)) for value in values):
        keys: list[Any] = []
        items: list[Any] = []
        for value in values:
            keys.extend(list(value.keys()))
            items.extend(list(value.values()))
        return f"HashMap<{rust_type_for_values(keys)}, {rust_type_for_values(items)}>"
    return "String"


def rust_literal(value: Any, type_hint: str | None = None) -> str:
    if type_hint is None:
        type_hint = rust_type_for_values([value])
    if type_hint.startswith("Option<"):
        inner = type_hint[len("Option<"):-1]
        if value is None:
            return "None"
        return f"Some({rust_literal(value, inner)})"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value}i64"
    if isinstance(value, (float, Decimal)):
        return f"{str(value)}f64"
    if isinstance(value, str):
        return f"String::from({rust_string(value)})"
    if isinstance(value, (list, tuple, deque)):
        inner = "i64"
        if type_hint.startswith("Vec<") and type_hint.endswith(">"):
            inner = type_hint[len("Vec<"):-1]
        return f"vec![{', '.join(rust_literal(item, inner) for item in value)}]"
    if isinstance(value, (set, frozenset)):
        inner = "i64"
        if type_hint.startswith("HashSet<") and type_hint.endswith(">"):
            inner = type_hint[len("HashSet<"):-1]
        return f"{{ let mut s = HashSet::new(); {''.join(f's.insert({rust_literal(item, inner)}); ' for item in value)}s }}"
    if isinstance(value, (dict, defaultdict, Counter)):
        key_type = "String"
        value_type = "i64"
        if type_hint.startswith("HashMap<") and type_hint.endswith(">"):
            parts = split_rust_template_args(type_hint[len("HashMap<"):-1])
            if len(parts) == 2:
                key_type, value_type = parts
        inserts = "".join(
            f"m.insert({rust_literal(key, key_type)}, {rust_literal(item, value_type)}); "
            for key, item in value.items()
        )
        return f"{{ let mut m = HashMap::new(); {inserts}m }}"
    return f"String::from({rust_string(str(value))})"


def split_rust_template_args(text: str) -> list[str]:
    return split_cpp_template_args(text)


def rust_numeric(value: Any | None, fallback: str = "-1.0f64") -> str:
    if value is None:
        return fallback
    return f"{str(value)}f64"


def rust_expr(expr: dict[str, Any], result_name: str, arg_names: list[str]) -> str:
    op = expr["op"]
    if op == "result":
        return result_name
    if op == "arg":
        return arg_names[expr["index"]]
    if op == "value":
        return rust_literal(expr["value"])
    if op in {"list", "tuple"}:
        return f"vec![{', '.join(rust_expr(item, result_name, arg_names) for item in expr['items'])}]"
    if op == "unary":
        operand = rust_expr(expr["operand"], result_name, arg_names)
        return {"uadd": operand, "usub": f"(-{operand})", "not": f"(!bcg_truthy(&{operand}))"}[expr["operator"]]
    if op == "binary":
        left = rust_expr(expr["left"], result_name, arg_names)
        right = rust_expr(expr["right"], result_name, arg_names)
        operator = {"add": "+", "sub": "-", "mult": "*", "truediv": "/", "floordiv": "/", "mod": "%"}.get(expr["operator"], "+")
        return f"({left} {operator} {right})"
    if op == "compare":
        left = rust_expr(expr["left"], result_name, arg_names)
        right = rust_expr(expr["right"], result_name, arg_names)
        return f"bcg_compare({rust_string(expr['operator'])}, &{left}, &{right})"
    if op == "call":
        args = [rust_expr(arg, result_name, arg_names) for arg in expr["args"]]
        name = expr["name"]
        if name == "sorted":
            return f"bcg_sorted({args[0]})"
        if name == "len":
            return f"bcg_len(&{args[0]})"
        if name == "abs":
            return f"({args[0]}).abs()"
        if name == "sum":
            return f"bcg_sum(&{args[0]})"
        if name in {"list", "tuple", "set", "frozenset"}:
            return args[0]
        if name == "str":
            return f"format!(\"{{:?}}\", {args[0]})"
        if name == "bool":
            return f"bcg_truthy(&{args[0]})"
        if name == "int":
            return f"({args[0]} as i64)"
        if name == "float":
            return f"({args[0]} as f64)"
    if op == "method":
        receiver = rust_expr(expr["receiver"], result_name, arg_names)
        args = [rust_expr(arg, result_name, arg_names) for arg in expr["args"]]
        name = expr["name"]
        if name == "upper":
            return f"({receiver}).to_uppercase()"
        if name == "lower":
            return f"({receiver}).to_lowercase()"
        if name == "find":
            return f"({receiver}).find(&{args[0]}).map(|v| v as i64).unwrap_or(-1)"
        if name in {"strip", "trim"}:
            return f"({receiver}).trim().to_string()"
        if name == "is_empty":
            return f"({receiver}).is_empty()"
    if op == "subscript":
        value = rust_expr(expr["value"], result_name, arg_names)
        index = rust_expr(expr["index"], result_name, arg_names)
        return f"({value})[{index} as usize].clone()"
    return result_name


RUST_HARNESS_PREAMBLE = r'''
use std::collections::{HashMap, HashSet};
use std::hash::Hash;
use std::panic;

fn bcg_equal<T: PartialEq>(left: &T, right: &T, abs_tol: f64, rel_tol: f64) -> bool {
    let _ = (abs_tol, rel_tol);
    left == right
}
fn bcg_equal_f64(left: f64, right: f64, abs_tol: f64, rel_tol: f64) -> bool {
    if abs_tol >= 0.0 || rel_tol >= 0.0 {
        let abs = if abs_tol < 0.0 { 0.0 } else { abs_tol };
        let rel = if rel_tol < 0.0 { 0.0 } else { rel_tol };
        (left - right).abs() <= abs.max(rel * left.abs().max(right.abs()))
    } else {
        left == right
    }
}
trait BcgTruthy { fn bcg_truthy(&self) -> bool; }
impl BcgTruthy for bool { fn bcg_truthy(&self) -> bool { *self } }
impl BcgTruthy for i64 { fn bcg_truthy(&self) -> bool { *self != 0 } }
impl BcgTruthy for f64 { fn bcg_truthy(&self) -> bool { *self != 0.0 && !self.is_nan() } }
impl BcgTruthy for String { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T> BcgTruthy for Vec<T> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T: Eq + Hash> BcgTruthy for HashSet<T> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<K: Eq + Hash, V> BcgTruthy for HashMap<K, V> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T: BcgTruthy> BcgTruthy for Option<T> { fn bcg_truthy(&self) -> bool { self.as_ref().map(|v| v.bcg_truthy()).unwrap_or(false) } }
fn bcg_truthy<T: BcgTruthy>(value: &T) -> bool { value.bcg_truthy() }
fn bcg_len<T>(value: &Vec<T>) -> i64 { value.len() as i64 }
fn bcg_sorted<T: Ord>(mut value: Vec<T>) -> Vec<T> { value.sort(); value }
fn bcg_sum<T>(value: &Vec<T>) -> T where T: Copy + Default + std::ops::Add<Output = T> {
    value.iter().copied().fold(T::default(), |a, b| a + b)
}
fn bcg_compare<T: PartialEq + PartialOrd>(op: &str, left: &T, right: &T) -> bool {
    match op {
        "eq" => left == right,
        "ne" => left != right,
        "lt" => left < right,
        "lte" => left <= right,
        "gt" => left > right,
        "gte" => left >= right,
        _ => false,
    }
}
'''


def rust_case_code(case: TestCase, entrypoint: str, default_abs_tol: float | None, arg_types: list[str]) -> str:
    lines = ["{"]
    arg_names: list[str] = []
    for index, value in enumerate(case.args):
        name = f"arg{index}"
        arg_names.append(name)
        lines.append(f"  let {name}: {arg_types[index]} = {rust_literal(value, arg_types[index])};")
    call = f"{entrypoint}({', '.join(name + '.clone()' for name in arg_names)})"
    if case.kind == "raises":
        lines.append(f"  let raised = panic::catch_unwind(|| {{ let _ = {call}; }}).is_err();")
        lines.append("  passed = raised;")
    else:
        lines.append(f"  let result = {call};")
        actual = rust_expr(case.actual_expr, "result", arg_names)
        if case.kind == "eq":
            if case.expected is None:
                lines.append(f"  passed = ({actual}).is_none();")
            elif isinstance(case.expected, (float, Decimal)):
                abs_tol = case.abs_tol if case.abs_tol is not None else default_abs_tol
                lines.append(f"  passed = bcg_equal_f64({actual} as f64, {rust_literal(case.expected)} as f64, {rust_numeric(abs_tol)}, {rust_numeric(case.rel_tol)});")
            else:
                lines.append(f"  passed = bcg_equal(&{actual}, &{rust_literal(case.expected)}, {rust_numeric(case.abs_tol if case.abs_tol is not None else default_abs_tol)}, {rust_numeric(case.rel_tol)});")
        elif case.kind == "ne":
            lines.append(f"  passed = !bcg_equal(&{actual}, &{rust_literal(case.expected)}, {rust_numeric(case.abs_tol if case.abs_tol is not None else default_abs_tol)}, {rust_numeric(case.rel_tol)});")
        elif case.kind == "truthy":
            lines.append(f"  passed = bcg_truthy(&{actual});")
        elif case.kind == "not":
            lines.append(f"  passed = !bcg_truthy(&{actual});")
        elif case.kind == "isclose":
            lines.append(f"  passed = bcg_equal_f64({actual} as f64, {rust_literal(case.expected)} as f64, {rust_numeric(case.abs_tol)}, {rust_numeric(case.rel_tol)});")
        elif case.kind == "absdiff":
            op = "<" if case.comparison == "abs_lt" else "<="
            lines.append(f"  passed = (({actual} as f64) - ({rust_literal(case.expected)} as f64)).abs() {op} {rust_numeric(case.abs_tol)};")
        elif case.kind == "mutation":
            lines.append("  passed = false;")
        else:
            lines.append("  passed = false;")
    lines.append(f"  println!(\"{{}}\\t{{}}\", {rust_string(case.id)}, if passed {{ \"1\" }} else {{ \"0\" }});")
    lines.append("}")
    return "\n".join(lines)


def run_rust_cases(
    solution_path: Path,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None,
    run_timeout: float | None = None,
) -> set[str] | None:
    compiler = shutil.which("rustc")
    if compiler is None:
        return None
    max_args = max((len(case.args) for case in cases), default=0)
    arg_types = [
        rust_type_for_values([case.args[index] for case in cases if len(case.args) > index])
        for index in range(max_args)
    ]
    body = "\n".join(
        "passed = false; let case_result = panic::catch_unwind(|| " + rust_case_code(case, entrypoint, default_abs_tol, arg_types) + "); if case_result.is_err() { println!(\"{}\\t0\", " + rust_string(case.id) + "); }"
        for case in cases
        if case.kind != "loop"
    )
    loop_lines = "\n".join(
        f"println!(\"{{}}\\t{{}}\", {rust_string(case.id)}, if {'true' if case.loop_pass else 'false'} {{ \"1\" }} else {{ \"0\" }});"
        for case in cases
        if case.kind == "loop"
    )
    source = (
        RUST_HARNESS_PREAMBLE
        + f"\ninclude!({rust_string(str(solution_path.resolve()))});\n"
        + "\nfn main() { let mut passed: bool;\n"
        + loop_lines
        + "\n"
        + body
        + "\n}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        harness = root / "harness.rs"
        binary = root / "harness"
        harness.write_text(source, encoding="utf-8")
        try:
            compile_proc = subprocess.run(
                [compiler, str(harness), "-o", str(binary)],
                text=True,
                capture_output=True,
                timeout=20,
            )
            if compile_proc.returncode != 0:
                return None
            run_proc = subprocess.run(
                [str(binary)],
                text=True,
                capture_output=True,
                timeout=10 if run_timeout is None else run_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    if run_proc.returncode != 0:
        return None
    return parse_compiled_output(run_proc.stdout)


def parse_compiled_output(stdout: str) -> set[str]:
    passed: set[str] = set()
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        test_id, status = line.rsplit("\t", 1)
        if status == "1":
            passed.add(test_id)
    return passed


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
    timeout: float | None = None,
) -> bool:
    if case.kind == "loop":
        return case.loop_pass is True
    if lang == "python":
        return run_python_case(solution_path, entrypoint, case, default_abs_tol, timeout)
    if lang in {"javascript", "typescript"}:
        return run_node_case(solution_path, entrypoint, lang, case, default_abs_tol, timeout)
    return False


def aggregate_results(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None = None,
    per_test_timeout_ms: int | None = None,
    total_timeout_ms: int | None = None,
) -> dict[str, Any]:
    per_case_timeout = timeout_seconds(per_test_timeout_ms)
    deadline = None if total_timeout_ms is None else time.monotonic() + timeout_seconds(total_timeout_ms)

    if lang in {"cpp", "rust"}:
        remaining = remaining_seconds(deadline)
        if remaining == 0:
            return {"status": "fail", "passed": [], "failed": [case.id for case in cases]}
        non_loop_count = sum(1 for case in cases if case.kind != "loop")
        compiled_timeout = remaining
        if per_case_timeout is not None:
            compiled_timeout = combine_timeouts(compiled_timeout, per_case_timeout * max(1, non_loop_count))
        compiled_passed = (
            run_cpp_cases(solution_path, entrypoint, cases, default_abs_tol, compiled_timeout)
            if lang == "cpp"
            else run_rust_cases(solution_path, entrypoint, cases, default_abs_tol, compiled_timeout)
        )
        if compiled_passed is None:
            compiled_passed = {case.id for case in cases if case.kind == "loop" and case.loop_pass is True}
        passed = [case.id for case in cases if case.id in compiled_passed]
        failed = [case.id for case in cases if case.id not in compiled_passed]
        status = "pass" if not failed else "fail"
        return {"status": status, "passed": passed, "failed": failed}

    passed: list[str] = []
    failed: list[str] = []
    for index, case in enumerate(cases):
        remaining = remaining_seconds(deadline)
        if remaining == 0:
            failed.extend(item.id for item in cases[index:])
            break
        case_timeout = combine_timeouts(per_case_timeout, remaining)
        if execute_case(solution_path, lang, entrypoint, case, default_abs_tol, case_timeout):
            passed.append(case.id)
        else:
            failed.append(case.id)
    status = "pass" if not failed else "fail"
    return {"status": status, "passed": passed, "failed": failed}


def numeric_stats(samples: list[float | int]) -> dict[str, float]:
    mean = sum(samples) / len(samples)
    variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
    return {"mean": mean, "std": math.sqrt(variance)}


def child_memory_kb() -> int:
    try:
        import resource
    except ImportError:
        return 0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return max(0, int(getattr(usage, "ru_maxrss", 0)))


def profile_compiled_trial(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None,
    per_test_timeout_ms: int | None,
    total_timeout_ms: int | None,
    collect_memory: bool,
) -> tuple[dict[str, Any], int, int]:
    memory_before = child_memory_kb() if collect_memory else 0
    started = time.perf_counter_ns()
    result = aggregate_results(
        solution_path,
        lang,
        entrypoint,
        cases,
        default_abs_tol,
        per_test_timeout_ms,
        total_timeout_ms,
    )
    runtime_ns = time.perf_counter_ns() - started
    memory_after = child_memory_kb() if collect_memory else memory_before
    return result, runtime_ns, max(0, memory_after - memory_before)


def profile_interpreted_case(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    case: TestCase,
    default_abs_tol: float | None,
    timeout: float | None,
    collect_memory: bool,
) -> tuple[bool, int, int]:
    memory_before = child_memory_kb() if collect_memory else 0
    started = time.perf_counter_ns()
    passed = execute_case(solution_path, lang, entrypoint, case, default_abs_tol, timeout)
    runtime_ns = time.perf_counter_ns() - started
    memory_after = child_memory_kb() if collect_memory else memory_before
    return passed, runtime_ns, max(0, memory_after - memory_before)


def timeout_sample_ns(total_timeout_ms: int | None, per_test_timeout_ms: int | None) -> int:
    timeout_ms = total_timeout_ms if total_timeout_ms is not None else per_test_timeout_ms
    return 0 if timeout_ms is None else timeout_ms * 1_000_000


def profile_cases(
    solution_path: Path,
    lang: str,
    entrypoint: str,
    cases: list[TestCase],
    default_abs_tol: float | None = None,
    per_test_timeout_ms: int | None = None,
    total_timeout_ms: int | None = None,
    trials: int = 1,
    warmup: int = 0,
    collect_memory: bool = False,
) -> dict[str, Any]:
    runtime_samples: list[int] = []
    memory_samples: list[int] = []
    failed_ids: set[str] = set()
    passed_ids: set[str] = set()
    per_case_timeout = timeout_seconds(per_test_timeout_ms)
    deadline = None if total_timeout_ms is None else time.monotonic() + timeout_seconds(total_timeout_ms)

    for trial_index in range(trials):
        measured = trial_index >= warmup
        if lang in {"cpp", "rust"}:
            remaining = remaining_seconds(deadline)
            if remaining == 0:
                trial_result = {"status": "fail", "passed": [], "failed": [case.id for case in cases]}
                runtime_ns = timeout_sample_ns(total_timeout_ms, per_test_timeout_ms)
                memory_kb = 0
            else:
                trial_total_timeout_ms = None if remaining is None else int(remaining * 1000)
                trial_result, runtime_ns, memory_kb = profile_compiled_trial(
                    solution_path,
                    lang,
                    entrypoint,
                    cases,
                    default_abs_tol,
                    per_test_timeout_ms,
                    trial_total_timeout_ms,
                    collect_memory,
                )
            passed_ids.update(str(case_id) for case_id in trial_result["passed"])
            failed_ids.update(str(case_id) for case_id in trial_result["failed"])
            if measured:
                sample_count = max(1, len(cases))
                runtime_samples.extend([runtime_ns] * sample_count)
                if collect_memory:
                    memory_samples.extend([memory_kb] * sample_count)
            continue

        for index, case in enumerate(cases):
            remaining = remaining_seconds(deadline)
            if remaining == 0:
                remaining_cases = cases[index:]
                failed_ids.update(item.id for item in remaining_cases)
                if measured:
                    sample_ns = timeout_sample_ns(total_timeout_ms, per_test_timeout_ms)
                    runtime_samples.extend([sample_ns] * len(remaining_cases))
                    if collect_memory:
                        memory_samples.extend([0] * len(remaining_cases))
                break
            case_timeout = combine_timeouts(per_case_timeout, remaining)
            passed, runtime_ns, memory_kb = profile_interpreted_case(
                solution_path,
                lang,
                entrypoint,
                case,
                default_abs_tol,
                case_timeout,
                collect_memory,
            )
            if passed:
                passed_ids.add(case.id)
            else:
                failed_ids.add(case.id)
            if measured:
                runtime_samples.append(runtime_ns)
                if collect_memory:
                    memory_samples.append(memory_kb)

    passed = [case.id for case in cases if case.id in passed_ids and case.id not in failed_ids]
    failed = [case.id for case in cases if case.id in failed_ids]
    status = "pass" if not failed else "fail"
    result: dict[str, Any] = {
        "status": status,
        "passed": passed,
        "failed": failed,
        "runtime_ns": numeric_stats(runtime_samples),
    }
    if collect_memory:
        result["memory_kb"] = numeric_stats(memory_samples)
    return result


def prepare_run(args: argparse.Namespace) -> PreparedRun | None:
    lang = args.lang
    if not is_supported_lang(lang):
        return None
    try:
        default_abs_tol = parse_default_tolerance(args.tol)
        per_test_timeout_ms = parse_timeout_ms(args.timeout_ms)
        total_timeout_ms = parse_timeout_ms(args.total_timeout_ms)
    except DiscoveryError:
        return None

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / tester_filename(lang)
    if not tester_path.is_file():
        return None

    try:
        metadata = read_tester_metadata(tester_path)
    except MetadataError:
        return None
    if metadata["lang"] != lang:
        return None

    entrypoint = metadata["entrypoint"]
    solution_path = Path(args.solution_path)
    try:
        all_cases = discover_tests(
            tests_dir,
            entrypoint,
            exclude_paths={solution_path, tester_path},
            target_lang=lang,
        )
    except DiscoveryError:
        return None

    selected_cases = all_cases
    if args.run is not None:
        selected_cases = [case for case in all_cases if case.id == args.run]
        if not selected_cases:
            return None

    return PreparedRun(
        solution_path=solution_path,
        lang=lang,
        entrypoint=entrypoint,
        cases=selected_cases,
        all_cases=all_cases,
        default_abs_tol=default_abs_tol,
        per_test_timeout_ms=per_test_timeout_ms,
        total_timeout_ms=total_timeout_ms,
    )


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
        discover_tests(tests_dir, args.entrypoint, target_lang=lang)
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
    prepared = prepare_run(args)
    if prepared is None:
        print_json_result(error_result())
        return 2

    if args.list_tests:
        result = {"status": "pass", "passed": [case.id for case in prepared.all_cases], "failed": []}
        print_json_result(result)
        return status_exit_code(result["status"])

    result = aggregate_results(
        prepared.solution_path,
        prepared.lang,
        prepared.entrypoint,
        prepared.cases,
        prepared.default_abs_tol,
        prepared.per_test_timeout_ms,
        prepared.total_timeout_ms,
    )
    print_json_result(result)
    return status_exit_code(result["status"])


def command_profile(args: argparse.Namespace) -> int:
    try:
        trials = parse_nonnegative_int(args.trials, "trials")
        warmup = parse_nonnegative_int(args.warmup, "warmup")
    except DiscoveryError:
        print_json_result(error_result())
        return 2
    if trials < 1 or warmup >= trials:
        print_json_result(error_result())
        return 2

    prepared = prepare_run(args)
    if prepared is None:
        print_json_result(error_result())
        return 2

    if args.list_tests:
        result = {"status": "pass", "passed": [case.id for case in prepared.cases], "failed": []}
        print_json_result(result)
        return status_exit_code(result["status"])

    result = profile_cases(
        prepared.solution_path,
        prepared.lang,
        prepared.entrypoint,
        prepared.cases,
        prepared.default_abs_tol,
        prepared.per_test_timeout_ms,
        prepared.total_timeout_ms,
        trials,
        warmup,
        args.memory,
    )
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
