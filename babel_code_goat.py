#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import ast
from collections import Counter, defaultdict, deque
import contextlib
from decimal import Decimal, InvalidOperation
import importlib.util
import inspect
import io
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any


SUPPORTED_LANGS = {
    "python": {"tester": "tester.py", "runner": "python"},
    "javascript": {"tester": "tester.js", "runner": "node"},
    "typescript": {"tester": "tester.ts", "runner": "node"},
    "cpp": {"tester": "tester.cpp", "runner": "g++"},
    "rust": {"tester": "tester.rs", "runner": "rustc"},
}
RESULT_ERROR = {"status": "error", "passed": [], "failed": []}
EXPECT_RE = re.compile(r"^\s*#\s*expect_(stdout|stderr):\s*(.+?)\s*$")
TAG_KEY = "__bcg_type__"
RUN_ID_ENV = "BABEL_CODE_GOAT_RUN_ID"
TIMEOUT_MS_ENV = "BABEL_CODE_GOAT_TIMEOUT_MS"
TOTAL_TIMEOUT_MS_ENV = "BABEL_CODE_GOAT_TOTAL_TIMEOUT_MS"


class DiscoveryError(Exception):
    pass


class ExecutionTimeout(Exception):
    pass


@dataclass(frozen=True)
class TestCase:
    id: str
    line: int
    kind: str
    args: list[Any]
    source_path: str = "tests.py"
    expected: Any = None
    tolerance: dict[str, Any] | None = None
    expected_exception: str | None = None
    message_match: dict[str, str] | None = None
    expression: dict[str, Any] | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    in_loop: bool = False
    mutation_arg_index: int | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_path": self.source_path,
            "line": self.line,
            "kind": self.kind,
            "args": self.args,
            "expected": self.expected,
            "tolerance": self.tolerance,
            "expected_exception": self.expected_exception,
            "message_match": self.message_match,
            "expression": self.expression,
            "expect_stdout": self.expect_stdout,
            "expect_stderr": self.expect_stderr,
            "mutation_arg_index": self.mutation_arg_index,
        }


@dataclass
class DiscoveryContext:
    names: dict[str, str]
    values: dict[str, Any]

    def child(self) -> "DiscoveryContext":
        return DiscoveryContext(names=self.names.copy(), values=self.values.copy())


@dataclass(frozen=True)
class ExpressionBuild:
    expression: dict[str, Any]
    args: list[Any] | None
    call_count: int


MutationSource = tuple[str, int | None]


@dataclass(frozen=True)
class PreparedExecution:
    lang: str
    tests_dir: Path
    solution_path: Path
    tester: Path
    payload: dict[str, Any]
    all_ids: list[str]
    scope_ids: list[str]
    timeout_ms: int | None
    total_timeout_ms: int | None
    run_id: str | None
    tol: float


ALLOWED_IMPORTS = {
    "math": "math",
    "re": "re",
    "collections": "collections",
    "decimal": "decimal",
}
ALLOWED_FROM_IMPORTS = {
    "collections": {"Counter", "deque", "defaultdict"},
    "decimal": {"Decimal"},
    "math": {"isclose"},
    "re": {"search"},
}


def tagged(type_name: str, **values: Any) -> dict[str, Any]:
    return {TAG_KEY: type_name, **values}


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sort_tagged_values(values: list[Any]) -> list[Any]:
    return sorted(values, key=stable_json)


def normalize_runtime_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return tagged("decimal", value=str(value))
    if isinstance(value, Counter):
        items = [
            [normalize_runtime_value(key), normalize_runtime_value(count)]
            for key, count in value.items()
            if count != 0
        ]
        items.sort(key=lambda pair: stable_json(pair[0]))
        return tagged("counter", items=items)
    if isinstance(value, deque):
        return tagged("deque", items=[normalize_runtime_value(item) for item in value])
    if isinstance(value, defaultdict):
        return normalize_mapping(value)
    if isinstance(value, dict):
        return normalize_mapping(value)
    if isinstance(value, tuple | list):
        return [normalize_runtime_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return tagged("set", items=sort_tagged_values([normalize_runtime_value(item) for item in value]))
    raise DiscoveryError(f"unsupported literal value: {type(value).__name__}")


def normalize_mapping(value: dict[Any, Any]) -> Any:
    items = [[normalize_runtime_value(key), normalize_runtime_value(item)] for key, item in value.items()]
    items.sort(key=lambda pair: stable_json(pair[0]))
    return tagged("dict", items=items)


def literal_fallback(node: ast.AST) -> Any:
    try:
        value = ast.literal_eval(node)
    except Exception as exc:
        raise DiscoveryError("unsupported literal expression") from exc
    return normalize_runtime_value(value)


def resolve_callee(node: ast.AST, context: DiscoveryContext) -> str | None:
    if isinstance(node, ast.Name):
        return context.names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = resolve_callee(node.value, context)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def parse_tolerance_value(node: ast.AST, context: DiscoveryContext) -> float:
    value = value_from_node(node, context)
    if isinstance(value, dict) and value.get(TAG_KEY) == "decimal":
        return float(value["value"])
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DiscoveryError("tolerance must be numeric")
    return float(value)


def index_value(container: Any, index: Any) -> Any:
    if isinstance(index, bool) or not isinstance(index, int | str):
        raise DiscoveryError("unsupported index value")
    if isinstance(container, dict) and container.get(TAG_KEY) == "dict":
        exact_tolerance = {"mode": "default", "abs": 0.0, "rel": 0.0}
        normalized_index = normalize_runtime_value(index)
        for key, item in container["items"]:
            if deep_compare(key, normalized_index, exact_tolerance):
                return item
        raise DiscoveryError("missing indexed value")
    if isinstance(container, dict) and container.get(TAG_KEY) == "deque":
        return container["items"][index]
    try:
        return container[index]
    except Exception as exc:
        raise DiscoveryError("unsupported indexed value") from exc


def eval_binary(operator: ast.operator, left: Any, right: Any) -> Any:
    if isinstance(operator, ast.Add):
        return left + right
    if isinstance(operator, ast.Sub):
        return left - right
    if isinstance(operator, ast.Mult):
        return left * right
    if isinstance(operator, ast.Div):
        return left / right
    if isinstance(operator, ast.FloorDiv):
        return left // right
    if isinstance(operator, ast.Mod):
        return left % right
    raise DiscoveryError("unsupported binary value expression")


def eval_compare(operator: ast.cmpop, left: Any, right: Any) -> bool:
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
    raise DiscoveryError("unsupported comparison value expression")


def value_from_node(node: ast.AST, context: DiscoveryContext) -> Any:
    if isinstance(node, ast.Name):
        if node.id in context.values:
            return context.values[node.id]
        raise DiscoveryError("unsupported name")
    if isinstance(node, ast.Constant):
        return normalize_runtime_value(node.value)
    if isinstance(node, ast.List | ast.Tuple):
        return [value_from_node(item, context) for item in node.elts]
    if isinstance(node, ast.Set):
        return tagged("set", items=sort_tagged_values([value_from_node(item, context) for item in node.elts]))
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise DiscoveryError("dictionary unpacking is unsupported")
        items = [
            [value_from_node(key, context), value_from_node(item, context)]
            for key, item in zip(node.keys, node.values, strict=True)
        ]
        items.sort(key=lambda pair: stable_json(pair[0]))
        return tagged("dict", items=items)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = value_from_node(node.operand, context)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise DiscoveryError("unsupported unary literal")
        return -value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        value = value_from_node(node.operand, context)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise DiscoveryError("unsupported unary literal")
        return value
    if isinstance(node, ast.Subscript):
        return normalize_runtime_value(index_value(value_from_node(node.value, context), value_from_node(node.slice, context)))
    if isinstance(node, ast.BinOp):
        return normalize_runtime_value(
            eval_binary(node.op, value_from_node(node.left, context), value_from_node(node.right, context))
        )
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise DiscoveryError("unsupported comparison value expression")
        return eval_compare(node.ops[0], value_from_node(node.left, context), value_from_node(node.comparators[0], context))
    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee == "len":
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported len call")
            return len(value_from_node(node.args[0], context))
        if callee == "range":
            if node.keywords or len(node.args) not in {1, 2, 3}:
                raise DiscoveryError("unsupported range call")
            args = [value_from_node(arg, context) for arg in node.args]
            if any(isinstance(arg, bool) or not isinstance(arg, int) for arg in args):
                raise DiscoveryError("range requires integer arguments")
            return list(range(*args))
        if callee == "enumerate":
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported enumerate call")
            return [[index, item] for index, item in enumerate(iterable_from_node(node.args[0], context))]
        if callee in {"set", "frozenset"}:
            if node.keywords or len(node.args) > 1:
                raise DiscoveryError("unsupported set constructor")
            source = [] if not node.args else value_from_node(node.args[0], context)
            if not isinstance(source, list):
                raise DiscoveryError("set constructor requires iterable literal")
            return tagged("set", items=sort_tagged_values(source))
        if callee in {"collections.Counter", "Counter"}:
            if node.keywords or len(node.args) > 1:
                raise DiscoveryError("unsupported Counter constructor")
            if not node.args:
                items: list[Any] = []
            else:
                source = value_from_node(node.args[0], context)
                if isinstance(source, dict) and source.get(TAG_KEY) == "dict":
                    items = source["items"]
                elif isinstance(source, list):
                    counts: dict[str, list[Any]] = {}
                    for item in source:
                        key = stable_json(item)
                        if key not in counts:
                            counts[key] = [item, 0]
                        counts[key][1] += 1
                    items = [[item, count] for item, count in counts.values()]
                else:
                    raise DiscoveryError("unsupported Counter source")
            items.sort(key=lambda pair: stable_json(pair[0]))
            return tagged("counter", items=items)
        if callee in {"collections.deque", "deque"}:
            if node.keywords or len(node.args) > 1:
                raise DiscoveryError("unsupported deque constructor")
            items = [] if not node.args else value_from_node(node.args[0], context)
            if not isinstance(items, list):
                raise DiscoveryError("deque constructor requires iterable literal")
            return tagged("deque", items=items)
        if callee in {"collections.defaultdict", "defaultdict"}:
            if len(node.args) > 2:
                raise DiscoveryError("unsupported defaultdict constructor")
            if node.keywords:
                raise DiscoveryError("unsupported defaultdict keywords")
            mapping_arg = node.args[1] if len(node.args) == 2 else None
            if mapping_arg is None:
                items = []
            else:
                mapping = value_from_node(mapping_arg, context)
                if not (isinstance(mapping, dict) and mapping.get(TAG_KEY) == "dict"):
                    raise DiscoveryError("defaultdict requires mapping literal")
                items = mapping["items"]
            return tagged("dict", items=items)
        if callee in {"decimal.Decimal", "Decimal"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("Decimal requires one literal")
            raw = value_from_node(node.args[0], context)
            if isinstance(raw, dict):
                raise DiscoveryError("Decimal requires scalar literal")
            try:
                decimal_value = Decimal(str(raw))
            except InvalidOperation as exc:
                raise DiscoveryError("invalid Decimal literal") from exc
            return tagged("decimal", value=str(decimal_value))
    return literal_fallback(node)


def parse_expectations(lines: list[str], test_line: int) -> tuple[str | None, str | None]:
    stdout = None
    stderr = None
    index = test_line - 2
    while index >= 0:
        raw = lines[index]
        if not raw.strip():
            break
        match = EXPECT_RE.match(raw)
        if not match:
            break
        stream, literal = match.groups()
        try:
            value = ast.literal_eval(literal)
        except Exception as exc:
            raise DiscoveryError("invalid stdout/stderr expectation") from exc
        if not isinstance(value, str):
            raise DiscoveryError("stdout/stderr expectation must be a string")
        if stream == "stdout":
            if stdout is not None:
                raise DiscoveryError("duplicate stdout expectation")
            stdout = value
        else:
            if stderr is not None:
                raise DiscoveryError("duplicate stderr expectation")
            stderr = value
        index -= 1
    return stdout, stderr


def parse_entrypoint_call(node: ast.AST, entrypoint: str, context: DiscoveryContext) -> list[Any]:
    if not isinstance(node, ast.Call):
        raise DiscoveryError("expected entrypoint call")
    if not isinstance(node.func, ast.Name) or node.func.id != entrypoint:
        raise DiscoveryError("assertion must call the configured entrypoint")
    if node.keywords:
        raise DiscoveryError("keyword arguments are unsupported")
    args: list[Any] = []
    for arg in node.args:
        if isinstance(arg, ast.Starred):
            expanded = value_from_node(arg.value, context)
            if not isinstance(expanded, list):
                raise DiscoveryError("starred arguments require iterable literal")
            args.extend(expanded)
        else:
            args.append(value_from_node(arg, context))
    return args


def entrypoint_call_count(node: ast.AST, entrypoint: str) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == entrypoint:
            count += 1
    return count


def referenced_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def merge_expression_args(parts: list[ExpressionBuild]) -> tuple[list[Any] | None, int]:
    args = None
    call_count = 0
    for part in parts:
        call_count += part.call_count
        if part.args is not None:
            args = part.args
    return args, call_count


def const_expression(node: ast.AST, context: DiscoveryContext) -> ExpressionBuild:
    return ExpressionBuild({"op": "const", "value": value_from_node(node, context)}, None, 0)


def expression_from_node(
    node: ast.AST, entrypoint: str, context: DiscoveryContext, actual_names: set[str] | None = None
) -> ExpressionBuild:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint:
        return ExpressionBuild({"op": "actual"}, parse_entrypoint_call(node, entrypoint, context), 1)

    if actual_names and isinstance(node, ast.Name) and node.id in actual_names:
        return ExpressionBuild({"op": "actual"}, None, 0)

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = expression_from_node(node.args[0], entrypoint, context, actual_names)
            return ExpressionBuild(
                {"op": "call", "function": callee, "args": [operand.expression]},
                operand.args,
                operand.call_count,
            )
        if entrypoint_call_count(node, entrypoint):
            raise DiscoveryError("unsupported helper call")
        return const_expression(node, context)

    if isinstance(node, ast.Name | ast.Constant | ast.List | ast.Tuple | ast.Set | ast.Dict):
        if entrypoint_call_count(node, entrypoint):
            raise DiscoveryError("unsupported container expression")
        if actual_names and referenced_names(node) & actual_names:
            raise DiscoveryError("unsupported mutation assertion")
        return const_expression(node, context)

    if isinstance(node, ast.UnaryOp):
        unary_ops = {
            ast.Not: "not",
            ast.USub: "neg",
            ast.UAdd: "pos",
        }
        operator = next((name for op_type, name in unary_ops.items() if isinstance(node.op, op_type)), None)
        if operator is None:
            raise DiscoveryError("unsupported unary expression")
        operand = expression_from_node(node.operand, entrypoint, context, actual_names)
        return ExpressionBuild(
            {"op": "unary", "operator": operator, "operand": operand.expression},
            operand.args,
            operand.call_count,
        )

    if isinstance(node, ast.BinOp):
        binary_ops = {
            ast.Add: "add",
            ast.Sub: "sub",
            ast.Mult: "mul",
            ast.Div: "div",
            ast.FloorDiv: "floordiv",
            ast.Mod: "mod",
            ast.Pow: "pow",
        }
        operator = next((name for op_type, name in binary_ops.items() if isinstance(node.op, op_type)), None)
        if operator is None:
            raise DiscoveryError("unsupported binary expression")
        left = expression_from_node(node.left, entrypoint, context, actual_names)
        right = expression_from_node(node.right, entrypoint, context, actual_names)
        args, call_count = merge_expression_args([left, right])
        return ExpressionBuild(
            {"op": "binary", "operator": operator, "left": left.expression, "right": right.expression},
            args,
            call_count,
        )

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            operator = "and"
        elif isinstance(node.op, ast.Or):
            operator = "or"
        else:
            raise DiscoveryError("unsupported boolean expression")
        values = [expression_from_node(value, entrypoint, context, actual_names) for value in node.values]
        args, call_count = merge_expression_args(values)
        return ExpressionBuild(
            {"op": "bool", "operator": operator, "values": [value.expression for value in values]},
            args,
            call_count,
        )

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise DiscoveryError("unsupported comparison expression")
        compare_ops = {
            ast.Eq: "eq",
            ast.NotEq: "neq",
            ast.In: "in",
            ast.NotIn: "not_in",
            ast.Lt: "lt",
            ast.LtE: "lte",
            ast.Gt: "gt",
            ast.GtE: "gte",
        }
        operator = next((name for op_type, name in compare_ops.items() if isinstance(node.ops[0], op_type)), None)
        if operator is None:
            raise DiscoveryError("unsupported comparison expression")
        left = expression_from_node(node.left, entrypoint, context, actual_names)
        right = expression_from_node(node.comparators[0], entrypoint, context, actual_names)
        args, call_count = merge_expression_args([left, right])
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression},
            args,
            call_count,
        )

    if isinstance(node, ast.Subscript):
        if entrypoint_call_count(node, entrypoint) == 0 and not (actual_names and referenced_names(node) & actual_names):
            return const_expression(node, context)
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = expression_from_node(node.value, entrypoint, context, actual_names)
        index = expression_from_node(node.slice, entrypoint, context, actual_names)
        args, call_count = merge_expression_args([value, index])
        return ExpressionBuild(
            {"op": "index", "value": value.expression, "index": index.expression},
            args,
            call_count,
        )

    raise DiscoveryError("unsupported primitive expression")


def parse_expression_assertion(test: ast.AST, entrypoint: str, context: DiscoveryContext) -> tuple[list[Any], dict[str, Any]]:
    parsed = expression_from_node(test, entrypoint, context)
    if parsed.call_count != 1 or parsed.args is None:
        raise DiscoveryError("assertion must contain exactly one entrypoint call")
    return parsed.args, parsed.expression


def parse_math_isclose(test: ast.Call, entrypoint: str, context: DiscoveryContext) -> tuple[list[Any], Any, dict[str, Any]]:
    if resolve_callee(test.func, context) not in {"math.isclose", "isclose"}:
        raise DiscoveryError("unsupported function assertion")
    if len(test.args) != 2:
        raise DiscoveryError("math.isclose requires actual and expected values")
    if test.args[0].__class__ is ast.Starred:
        raise DiscoveryError("unsupported math.isclose arguments")
    args = parse_entrypoint_call(test.args[0], entrypoint, context)
    expected = value_from_node(test.args[1], context)
    tolerance = {"mode": "isclose", "abs": 0.0, "rel": 1e-09}
    for keyword in test.keywords:
        if keyword.arg not in {"abs_tol", "rel_tol"}:
            raise DiscoveryError("unsupported math.isclose keyword")
        tolerance["abs" if keyword.arg == "abs_tol" else "rel"] = parse_tolerance_value(keyword.value, context)
    return args, expected, tolerance


def parse_abs_difference(
    test: ast.Compare, entrypoint: str, context: DiscoveryContext
) -> tuple[list[Any], Any, dict[str, Any]]:
    if len(test.ops) != 1 or len(test.comparators) != 1:
        raise DiscoveryError("unsupported absolute difference assertion")
    strict: bool
    if isinstance(test.ops[0], ast.Lt):
        strict = True
    elif isinstance(test.ops[0], ast.LtE):
        strict = False
    else:
        raise DiscoveryError("unsupported absolute difference comparison")
    if not isinstance(test.left, ast.Call) or resolve_callee(test.left.func, context) != "abs" or len(test.left.args) != 1:
        raise DiscoveryError("unsupported absolute difference assertion")
    diff = test.left.args[0]
    if not isinstance(diff, ast.BinOp) or not isinstance(diff.op, ast.Sub):
        raise DiscoveryError("unsupported absolute difference assertion")
    try:
        args = parse_entrypoint_call(diff.left, entrypoint, context)
        expected = value_from_node(diff.right, context)
    except DiscoveryError:
        args = parse_entrypoint_call(diff.right, entrypoint, context)
        expected = value_from_node(diff.left, context)
    return args, expected, {"mode": "absdiff", "abs": parse_tolerance_value(test.comparators[0], context), "strict": strict}


def parse_assert(node: ast.Assert, entrypoint: str, lines: list[str], context: DiscoveryContext) -> TestCase:
    test = node.test
    kind: str
    args: list[Any]
    expected: Any = None
    tolerance: dict[str, Any] | None = None
    expression: dict[str, Any] | None = None

    if isinstance(test, ast.Call) and resolve_callee(test.func, context) in {"math.isclose", "isclose"}:
        kind = "eq"
        args, expected, tolerance = parse_math_isclose(test, entrypoint, context)
    elif (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Call)
        and resolve_callee(test.left.func, context) == "abs"
    ):
        kind = "eq"
        args, expected, tolerance = parse_abs_difference(test, entrypoint, context)
    elif (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
        and isinstance(test.ops[0], ast.Eq | ast.NotEq)
    ):
        if isinstance(test.ops[0], ast.Eq):
            kind = "eq"
        else:
            kind = "neq"
        try:
            args = parse_entrypoint_call(test.left, entrypoint, context)
            expected = value_from_node(test.comparators[0], context)
        except DiscoveryError:
            kind = "expr"
            args, expression = parse_expression_assertion(test, entrypoint, context)
    elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        try:
            kind = "falsy"
            args = parse_entrypoint_call(test.operand, entrypoint, context)
        except DiscoveryError:
            kind = "expr"
            args, expression = parse_expression_assertion(test, entrypoint, context)
    else:
        try:
            kind = "truthy"
            args = parse_entrypoint_call(test, entrypoint, context)
        except DiscoveryError:
            kind = "expr"
            args, expression = parse_expression_assertion(test, entrypoint, context)

    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind=kind,
        args=args,
        expected=expected,
        tolerance=tolerance,
        expression=expression,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


def configured_entrypoint_call(node: ast.AST, entrypoint: str) -> ast.Call | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint:
        return node
    return None


def mutation_call_from_stmt(stmt: ast.stmt, entrypoint: str) -> tuple[ast.Call, dict[str, MutationSource]] | None:
    if isinstance(stmt, ast.Expr):
        call = configured_entrypoint_call(stmt.value, entrypoint)
        if call is None:
            return None
        return call, mutation_sources_for_call(call, require_named=True)

    if isinstance(stmt, ast.Assign):
        call = configured_entrypoint_call(stmt.value, entrypoint)
        if call is None:
            return None
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            raise DiscoveryError("unsupported mutation assignment")
        sources = mutation_sources_for_call(call, require_named=False)
        sources[stmt.targets[0].id] = ("return", None)
        return call, sources

    if isinstance(stmt, ast.AnnAssign):
        call = configured_entrypoint_call(stmt.value, entrypoint) if stmt.value is not None else None
        if call is None:
            return None
        if not isinstance(stmt.target, ast.Name):
            raise DiscoveryError("unsupported mutation assignment")
        sources = mutation_sources_for_call(call, require_named=False)
        sources[stmt.target.id] = ("return", None)
        return call, sources

    return None


def mutation_sources_for_call(call: ast.Call, require_named: bool) -> dict[str, MutationSource]:
    sources: dict[str, MutationSource] = {}
    positional_index = 0
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            raise DiscoveryError("unsupported mutation argument")
        if isinstance(arg, ast.Name):
            sources[arg.id] = ("arg", positional_index)
        positional_index += 1
    if require_named and not sources:
        raise DiscoveryError("mutation call must pass a named variable or assign the result")
    return sources


def parse_mutation_assert(
    node: ast.Assert,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    args: list[Any],
    sources: dict[str, MutationSource],
    source_path: str,
) -> TestCase:
    if entrypoint_call_count(node.test, entrypoint):
        raise DiscoveryError("mutation assertion must not call entrypoint")

    assertion_names = referenced_names(node.test)
    matched_sources = {sources[name] for name in assertion_names if name in sources}
    if not matched_sources:
        raise DiscoveryError("mutation assertion must reference mutated value")
    if len(matched_sources) != 1:
        raise DiscoveryError("mutation assertion must reference one mutated value")

    mutation_source = next(iter(matched_sources))
    actual_names = {name for name, source in sources.items() if source == mutation_source}
    expression = expression_from_node(node.test, entrypoint, context, actual_names)
    if expression.call_count:
        raise DiscoveryError("mutation assertion must not call entrypoint")

    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        source_path=source_path,
        line=node.lineno,
        kind="expr",
        args=args,
        expression=expression.expression,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
        mutation_arg_index=mutation_source[1] if mutation_source[0] == "arg" else None,
    )


def discover_mutation_group(
    body: list[ast.stmt],
    index: int,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source_path: str,
    in_loop: bool,
) -> tuple[list[TestCase], int]:
    mutation = mutation_call_from_stmt(body[index], entrypoint)
    if mutation is None:
        raise DiscoveryError("expected mutation call")
    call, sources = mutation
    if call.keywords:
        raise DiscoveryError("keyword arguments are unsupported")
    args = parse_entrypoint_call(call, entrypoint, context)

    next_index = index + 1
    if next_index >= len(body) or not isinstance(body[next_index], ast.Assert):
        raise DiscoveryError("mutation call must be immediately followed by assertions")

    discovered: list[TestCase] = []
    while next_index < len(body) and isinstance(body[next_index], ast.Assert):
        test_case = parse_mutation_assert(
            body[next_index],
            entrypoint,
            lines,
            context,
            args,
            sources,
            source_path,
        )
        discovered.append(
            TestCase(
                id=test_case.id,
                source_path=test_case.source_path,
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                expected=test_case.expected,
                tolerance=test_case.tolerance,
                expected_exception=test_case.expected_exception,
                message_match=test_case.message_match,
                expression=test_case.expression,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=in_loop,
                mutation_arg_index=test_case.mutation_arg_index,
            )
        )
        next_index += 1
    return discovered, next_index


def exception_name(node: ast.AST | None, context: DiscoveryContext) -> str | None:
    if node is None:
        return None
    resolved = resolve_callee(node, context)
    if not resolved:
        raise DiscoveryError("unsupported exception type")
    return resolved.rsplit(".", 1)[-1]


def parse_str_exception_call(node: ast.AST, handler_name: str | None) -> bool:
    return (
        handler_name is not None
        and isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == handler_name
        and not node.keywords
    )


def parse_message_match(stmt: ast.stmt, handler_name: str | None, context: DiscoveryContext) -> dict[str, str]:
    if not isinstance(stmt, ast.Assert):
        raise DiscoveryError("unsupported exception handler body")
    test = stmt.test
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.In)
        and len(test.comparators) == 1
        and isinstance(test.left, ast.Constant)
        and isinstance(test.left.value, str)
        and parse_str_exception_call(test.comparators[0], handler_name)
    ):
        return {"mode": "contains", "pattern": test.left.value}
    if (
        isinstance(test, ast.Call)
        and resolve_callee(test.func, context) in {"re.search", "search"}
        and len(test.args) == 2
        and not test.keywords
        and isinstance(test.args[0], ast.Constant)
        and isinstance(test.args[0].value, str)
        and parse_str_exception_call(test.args[1], handler_name)
    ):
        return {"mode": "regex", "pattern": test.args[0].value}
    raise DiscoveryError("unsupported exception message assertion")


def parse_raise_any(node: ast.Try, entrypoint: str, lines: list[str], context: DiscoveryContext) -> TestCase:
    if node.orelse or node.finalbody or len(node.body) != 2 or len(node.handlers) != 1:
        raise DiscoveryError("unsupported try block")
    call_stmt, assert_stmt = node.body
    if not isinstance(call_stmt, ast.Expr):
        raise DiscoveryError("raise-any block must call entrypoint first")
    args = parse_entrypoint_call(call_stmt.value, entrypoint, context)
    if (
        not isinstance(assert_stmt, ast.Assert)
        or not isinstance(assert_stmt.test, ast.Constant)
        or assert_stmt.test.value is not False
    ):
        raise DiscoveryError("raise-any block must assert False after entrypoint call")
    handler = node.handlers[0]
    expected_exception = exception_name(handler.type, context)
    if not expected_exception:
        raise DiscoveryError("raise block must catch an exception type")
    message_match = None
    if len(handler.body) != 1:
        raise DiscoveryError("unsupported exception handler body")
    if isinstance(handler.body[0], ast.Pass):
        if expected_exception == "Exception":
            expected_exception = None
    else:
        message_match = parse_message_match(handler.body[0], handler.name, context)
    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind="raises",
        args=args,
        expected_exception=expected_exception,
        message_match=message_match,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


def handle_import(stmt: ast.stmt, context: DiscoveryContext) -> bool:
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            if alias.name not in ALLOWED_IMPORTS:
                raise DiscoveryError("unsupported import")
            context.names[alias.asname or alias.name] = ALLOWED_IMPORTS[alias.name]
        return True
    if isinstance(stmt, ast.ImportFrom):
        if stmt.module not in ALLOWED_FROM_IMPORTS or stmt.level != 0:
            raise DiscoveryError("unsupported import")
        for alias in stmt.names:
            if alias.name not in ALLOWED_FROM_IMPORTS[stmt.module]:
                raise DiscoveryError("unsupported import")
            context.names[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
        return True
    return False


def bind_target(target: ast.AST, value: Any, context: DiscoveryContext) -> None:
    if isinstance(target, ast.Name):
        context.values[target.id] = value
        return
    if isinstance(target, ast.Tuple | ast.List):
        if not isinstance(value, list) or len(target.elts) != len(value):
            raise DiscoveryError("unsupported assignment target")
        for child_target, child_value in zip(target.elts, value, strict=True):
            bind_target(child_target, child_value, context)
        return
    raise DiscoveryError("unsupported assignment target")


def iterable_from_node(node: ast.AST, context: DiscoveryContext) -> list[Any]:
    value = value_from_node(node, context)
    if isinstance(value, str):
        return list(value)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and value.get(TAG_KEY) in {"set", "deque"}:
        return list(value["items"])
    raise DiscoveryError("unsupported loop iterable")


def handle_assignment(stmt: ast.stmt, context: DiscoveryContext) -> bool:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            raise DiscoveryError("unsupported assignment")
        bind_target(stmt.targets[0], value_from_node(stmt.value, context), context)
        return True
    if isinstance(stmt, ast.AnnAssign):
        if stmt.value is None:
            raise DiscoveryError("unsupported assignment")
        bind_target(stmt.target, value_from_node(stmt.value, context), context)
        return True
    return False


def handle_aug_assignment(stmt: ast.stmt, context: DiscoveryContext) -> bool:
    if not isinstance(stmt, ast.AugAssign):
        return False
    if not isinstance(stmt.target, ast.Name) or stmt.target.id not in context.values:
        raise DiscoveryError("unsupported augmented assignment")
    context.values[stmt.target.id] = normalize_runtime_value(
        eval_binary(stmt.op, context.values[stmt.target.id], value_from_node(stmt.value, context))
    )
    return True


def loop_case(node: ast.stmt, executed: bool, source_path: str) -> TestCase:
    return TestCase(id="", source_path=source_path, line=node.lineno, kind="loop", args=[], expected=executed)


def discover_for_loop(
    stmt: ast.For, entrypoint: str, lines: list[str], context: DiscoveryContext, source_path: str, in_loop: bool
) -> list[TestCase]:
    if stmt.orelse:
        raise DiscoveryError("unsupported loop else block")
    try:
        iterable = iterable_from_node(stmt.iter, context)
    except DiscoveryError:
        return [loop_case(stmt, False, source_path)]
    if not iterable:
        return [loop_case(stmt, False, source_path)]

    discovered = [loop_case(stmt, True, source_path)]
    for item in iterable:
        iteration_context = context.child()
        bind_target(stmt.target, item, iteration_context)
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, iteration_context, source_path, True))
    return discovered


def discover_while_loop(
    stmt: ast.While, entrypoint: str, lines: list[str], context: DiscoveryContext, source_path: str, in_loop: bool
) -> list[TestCase]:
    if stmt.orelse:
        raise DiscoveryError("unsupported loop else block")
    working_context = context.child()
    discovered: list[TestCase] = []
    executed = False
    max_iterations = 10_000

    for _ in range(max_iterations):
        try:
            condition = bool(value_from_node(stmt.test, working_context))
        except DiscoveryError:
            return [loop_case(stmt, False, source_path)]
        if not condition:
            return [loop_case(stmt, True, source_path), *discovered] if executed else [loop_case(stmt, False, source_path)]
        executed = True
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, working_context, source_path, True))

    return [loop_case(stmt, False, source_path)]


def discover_in_body(
    body: list[ast.stmt],
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source_path: str = "tests.py",
    in_loop: bool = False,
) -> list[TestCase]:
    discovered: list[TestCase] = []
    index = 0
    while index < len(body):
        stmt = body[index]
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context.child(), source_path, in_loop))
        elif isinstance(stmt, ast.Assert):
            test_case = parse_assert(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    source_path=source_path,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                    mutation_arg_index=test_case.mutation_arg_index,
                )
            )
        elif mutation_call_from_stmt(stmt, entrypoint) is not None:
            mutation_tests, next_index = discover_mutation_group(
                body, index, entrypoint, lines, context, source_path, in_loop
            )
            discovered.extend(mutation_tests)
            index = next_index
            continue
        elif isinstance(stmt, ast.Try):
            test_case = parse_raise_any(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    source_path=source_path,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                    mutation_arg_index=test_case.mutation_arg_index,
                )
            )
        elif isinstance(stmt, ast.For):
            discovered.extend(discover_for_loop(stmt, entrypoint, lines, context, source_path, in_loop))
        elif isinstance(stmt, ast.While):
            discovered.extend(discover_while_loop(stmt, entrypoint, lines, context, source_path, in_loop))
        elif handle_assignment(stmt, context) or handle_aug_assignment(stmt, context):
            pass
        elif isinstance(stmt, ast.Pass):
            pass
        elif handle_import(stmt, context):
            pass
        else:
            raise DiscoveryError(f"unsupported code at line {getattr(stmt, 'lineno', '?')}")
        index += 1
    return discovered


def assign_ids(test_cases: list[TestCase]) -> list[TestCase]:
    counts: dict[tuple[str, int], int] = {}
    for test_case in test_cases:
        if not test_case.in_loop:
            key = (test_case.source_path, test_case.line)
            counts[key] = counts.get(key, 0) + 1

    seen: dict[tuple[str, int], int] = {}
    loop_seen: dict[tuple[str, int], int] = {}
    assigned: list[TestCase] = []
    for test_case in test_cases:
        key = (test_case.source_path, test_case.line)
        if test_case.in_loop:
            line_seen = loop_seen.get(key, 0)
            loop_seen[key] = line_seen + 1
            test_id = f"{test_case.source_path}:{test_case.line}:{line_seen}"
        else:
            line_seen = seen.get(key, 0)
            seen[key] = line_seen + 1
            test_id = f"{test_case.source_path}:{test_case.line}"
            if counts.get(key, 0) > 1:
                test_id = f"{test_id}#{line_seen}"
        assigned.append(
            TestCase(
                id=test_id,
                source_path=test_case.source_path,
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                expected=test_case.expected,
                tolerance=test_case.tolerance,
                expected_exception=test_case.expected_exception,
                message_match=test_case.message_match,
                expression=test_case.expression,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=test_case.in_loop,
                mutation_arg_index=test_case.mutation_arg_index,
            )
        )
    return assigned


GENERATED_TESTER_FILES = {config["tester"] for config in SUPPORTED_LANGS.values()}


def is_test_like_non_python(path: Path) -> bool:
    if path.suffix == ".py":
        return False
    stem = path.stem
    return stem.startswith("test") or stem.endswith("_test") or stem == "tests" or stem.endswith("_tests")


def relative_test_path(path: Path, tests_dir: Path) -> str:
    return path.relative_to(tests_dir).as_posix()


def discover_test_files(tests_dir: Path) -> list[Path]:
    files = sorted(
        (path for path in tests_dir.rglob("*") if path.is_file()),
        key=lambda path: relative_test_path(path, tests_dir),
    )
    test_files: list[Path] = []
    for path in files:
        if path.name in GENERATED_TESTER_FILES:
            continue
        if is_test_like_non_python(path):
            raise DiscoveryError("test-like files must be Python files")
        if path.suffix == ".py":
            test_files.append(path)
    return test_files


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    discovered: list[TestCase] = []
    for tests_path in discover_test_files(tests_dir):
        source_path = relative_test_path(tests_path, tests_dir)
        try:
            source = tests_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DiscoveryError(f"could not read {source_path}") from exc
        try:
            tree = ast.parse(source, filename=source_path)
        except SyntaxError as exc:
            raise DiscoveryError(f"could not parse {source_path}") from exc
        lines = source.splitlines()
        context = DiscoveryContext(names={}, values={})
        discovered.extend(discover_in_body(tree.body, entrypoint, lines, context, source_path))
    if not discovered:
        raise DiscoveryError("no tests discovered")
    return assign_ids(discovered)


def make_result(status: str, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "passed": passed or [], "failed": failed or []}


def print_result(result: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return {"pass": 0, "fail": 1, "error": 2}[result["status"]]


def parse_optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("timeout must be a positive integer")
    return value


def parse_non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("value must be a non-negative integer")
    return value


def parse_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("value must be a positive integer")
    return value


def scoped_tests(tests: list[dict[str, Any]], run_id: str | None) -> list[dict[str, Any]] | None:
    if run_id is None:
        return tests
    selected = [test for test in tests if test.get("id") == run_id]
    return selected or None


def result_for_timeout(scope_ids: list[str]) -> dict[str, Any]:
    return make_result("fail", [], scope_ids)


def normalize_runner_result(result: Any, scope_ids: list[str]) -> dict[str, Any] | None:
    if not isinstance(result, dict) or list(result.keys()) != ["status", "passed", "failed"]:
        return None
    if result.get("status") not in {"pass", "fail", "error"}:
        return None
    if not isinstance(result.get("passed"), list) or not isinstance(result.get("failed"), list):
        return None
    if not all(isinstance(item, str) for item in result["passed"] + result["failed"]):
        return None
    if result["status"] == "error":
        return result

    scope_set = set(scope_ids)
    seen: set[str] = set()
    passed: list[str] = []
    failed: list[str] = []
    for test_id in result["passed"]:
        if test_id not in scope_set or test_id in seen:
            return None
        seen.add(test_id)
        passed.append(test_id)
    for test_id in result["failed"]:
        if test_id not in scope_set or test_id in seen:
            return None
        seen.add(test_id)
        failed.append(test_id)
    for test_id in scope_ids:
        if test_id not in seen:
            failed.append(test_id)
    return make_result("pass" if not failed else "fail", passed, failed)


def runtime_timeout_seconds(timeout_ms: int | None, total_timeout_ms: int | None, scope_count: int) -> float | None:
    if total_timeout_ms is not None:
        return total_timeout_ms / 1000 + 1.0
    if timeout_ms is not None:
        return timeout_ms * max(scope_count, 1) / 1000 + 1.0
    return None


def aggregate_stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"mean": 0.0, "std": 0.0}
    mean = sum(samples) / len(samples)
    variance = sum((sample - mean) ** 2 for sample in samples) / len(samples)
    return {"mean": mean, "std": math.sqrt(variance)}


def current_child_memory_kb() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    value = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        return value / 1024.0
    return value


def is_tagged(value: Any, type_name: str | None = None) -> bool:
    return isinstance(value, dict) and TAG_KEY in value and (type_name is None or value[TAG_KEY] == type_name)


def numeric_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if is_tagged(value, "decimal"):
        return Decimal(value["value"])
    return None


def tolerance_policy(test: dict[str, Any], default_tol: float) -> dict[str, Any]:
    tolerance = test.get("tolerance")
    if isinstance(tolerance, dict):
        return tolerance
    return {"mode": "default", "abs": default_tol, "rel": 0.0}


def numeric_equal(expected: Any, actual: Any, tolerance: dict[str, Any]) -> bool:
    expected_num = numeric_decimal(expected)
    actual_num = numeric_decimal(actual)
    if expected_num is None or actual_num is None:
        return False
    diff = abs(actual_num - expected_num)
    abs_tol = Decimal(str(tolerance.get("abs", 0.0)))
    if tolerance.get("mode") == "absdiff" and tolerance.get("strict"):
        return diff < abs_tol
    rel_tol = Decimal(str(tolerance.get("rel", 0.0)))
    limit = max(abs_tol, rel_tol * max(abs(actual_num), abs(expected_num)))
    return diff <= limit


def tag_type(value: Any) -> str | None:
    return value.get(TAG_KEY) if isinstance(value, dict) else None


def compare_items_unordered(expected_items: list[Any], actual_items: list[Any], tolerance: dict[str, Any]) -> bool:
    if len(expected_items) != len(actual_items):
        return False
    used: set[int] = set()
    for expected_item in expected_items:
        matched = False
        for index, actual_item in enumerate(actual_items):
            if index in used:
                continue
            if deep_compare(expected_item, actual_item, tolerance):
                used.add(index)
                matched = True
                break
        if not matched:
            return False
    return True


def compare_dict_items(expected_items: list[Any], actual_items: list[Any], tolerance: dict[str, Any]) -> bool:
    if len(expected_items) != len(actual_items):
        return False
    used: set[int] = set()
    exact_tolerance = {"mode": "default", "abs": 0.0, "rel": 0.0}
    for expected_key, expected_value in expected_items:
        matched = False
        for index, (actual_key, actual_value) in enumerate(actual_items):
            if index in used:
                continue
            if deep_compare(expected_key, actual_key, exact_tolerance) and deep_compare(
                expected_value, actual_value, tolerance
            ):
                used.add(index)
                matched = True
                break
        if not matched:
            return False
    return True


def deep_compare(expected: Any, actual: Any, tolerance: dict[str, Any]) -> bool:
    if numeric_decimal(expected) is not None and numeric_decimal(actual) is not None:
        return numeric_equal(expected, actual, tolerance)
    if type(expected) is not type(actual) and not (isinstance(expected, list) and isinstance(actual, list)):
        if not (is_tagged(expected) and is_tagged(actual)):
            return False
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            deep_compare(expected_item, actual_item, tolerance)
            for expected_item, actual_item in zip(expected, actual, strict=True)
        )
    if is_tagged(expected) or is_tagged(actual):
        if not (is_tagged(expected) and is_tagged(actual)):
            return False
        expected_type = tag_type(expected)
        actual_type = tag_type(actual)
        if expected_type == "decimal" or actual_type == "decimal":
            return numeric_equal(expected, actual, tolerance)
        if expected_type == "dict" and actual_type == "dict":
            return compare_dict_items(expected["items"], actual["items"], tolerance)
        if expected_type == "set" and actual_type == "set":
            return compare_items_unordered(expected["items"], actual["items"], tolerance)
        if expected_type == "counter" and actual_type == "counter":
            return compare_dict_items(expected["items"], actual["items"], tolerance)
        if expected_type == "deque" and actual_type == "deque":
            return len(expected["items"]) == len(actual["items"]) and all(
                deep_compare(expected_item, actual_item, tolerance)
                for expected_item, actual_item in zip(expected["items"], actual["items"], strict=True)
            )
        return False
    return expected == actual


def exception_matches(exc: Exception, expected_exception: str | None) -> bool:
    if expected_exception is None:
        return True
    return expected_exception in {cls.__name__ for cls in type(exc).mro()}


def message_matches(exc: Exception, matcher: dict[str, str] | None) -> bool:
    if not matcher:
        return True
    message = str(exc)
    if matcher.get("mode") == "contains":
        return matcher.get("pattern", "") in message
    if matcher.get("mode") == "regex":
        return re.search(matcher.get("pattern", ""), message) is not None
    return False


def decode_arg(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_arg(item) for item in value]
    if not is_tagged(value):
        return value
    type_name = value[TAG_KEY]
    if type_name == "decimal":
        return Decimal(value["value"])
    if type_name == "dict":
        return {decode_arg(key): decode_arg(item) for key, item in value["items"]}
    if type_name == "set":
        return {decode_arg(item) for item in value["items"]}
    if type_name == "counter":
        counter = Counter()
        for key, count in value["items"]:
            counter[decode_arg(key)] = decode_arg(count)
        return counter
    if type_name == "deque":
        return deque(decode_arg(item) for item in value["items"])
    return value


def normalize_comparable(value: Any) -> Any:
    if is_tagged(value):
        return value
    return normalize_runtime_value(value)


def expression_contains(container: Any, needle: Any, tolerance: dict[str, Any]) -> bool:
    if isinstance(container, str) and isinstance(needle, str):
        return needle in container
    normalized_needle = normalize_comparable(needle)
    if is_tagged(container, "dict"):
        return any(deep_compare(key, normalized_needle, tolerance) for key, _ in container["items"])
    if is_tagged(container, "set") or is_tagged(container, "deque"):
        return any(deep_compare(item, normalized_needle, tolerance) for item in container["items"])
    if isinstance(container, dict):
        return any(deep_compare(normalize_comparable(key), normalized_needle, tolerance) for key in container)
    if isinstance(container, list | tuple | set | frozenset | deque):
        return any(deep_compare(normalize_comparable(item), normalized_needle, tolerance) for item in container)
    return False


def expression_index(value: Any, index: Any) -> Any:
    if is_tagged(value, "dict"):
        for key, item in value["items"]:
            if deep_compare(key, normalize_comparable(index), {"mode": "default", "abs": 0.0, "rel": 0.0}):
                return item
        raise KeyError(index)
    if is_tagged(value, "deque"):
        return value["items"][index]
    return value[index]


def expression_sorted(value: Any) -> Any:
    if isinstance(value, str):
        return sorted(value)
    if is_tagged(value, "set") or is_tagged(value, "deque"):
        return sort_tagged_values(list(value["items"]))
    return sorted(value)


def evaluate_expression(expression: dict[str, Any], actual: Any, tolerance: dict[str, Any]) -> Any:
    op = expression.get("op")
    if op == "const":
        return expression.get("value")
    if op == "actual":
        return actual
    if op == "unary":
        operand = evaluate_expression(expression["operand"], actual, tolerance)
        operator = expression.get("operator")
        if operator == "not":
            return not bool(operand)
        if operator == "neg":
            return -operand
        if operator == "pos":
            return +operand
    if op == "binary":
        left = evaluate_expression(expression["left"], actual, tolerance)
        right = evaluate_expression(expression["right"], actual, tolerance)
        operator = expression.get("operator")
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            return left / right
        if operator == "floordiv":
            return left // right
        if operator == "mod":
            return left % right
        if operator == "pow":
            return left**right
    if op == "bool":
        values = [evaluate_expression(value, actual, tolerance) for value in expression["values"]]
        if expression.get("operator") == "and":
            return all(bool(value) for value in values)
        if expression.get("operator") == "or":
            return any(bool(value) for value in values)
    if op == "compare":
        left = evaluate_expression(expression["left"], actual, tolerance)
        right = evaluate_expression(expression["right"], actual, tolerance)
        operator = expression.get("operator")
        if operator == "eq":
            return deep_compare(normalize_comparable(left), normalize_comparable(right), tolerance)
        if operator == "neq":
            return not deep_compare(normalize_comparable(left), normalize_comparable(right), tolerance)
        if operator == "in":
            return expression_contains(right, left, tolerance)
        if operator == "not_in":
            return not expression_contains(right, left, tolerance)
        left_num = numeric_decimal(normalize_comparable(left))
        right_num = numeric_decimal(normalize_comparable(right))
        if left_num is not None and right_num is not None:
            if operator == "lt":
                return left_num < right_num
            if operator == "lte":
                return left_num <= right_num
            if operator == "gt":
                return left_num > right_num
            if operator == "gte":
                return left_num >= right_num
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
        if operator == "gt":
            return left > right
        if operator == "gte":
            return left >= right
    if op == "index":
        value = evaluate_expression(expression["value"], actual, tolerance)
        index = evaluate_expression(expression["index"], actual, tolerance)
        return expression_index(value, index)
    if op == "call":
        args = [evaluate_expression(arg, actual, tolerance) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return expression_sorted(args[0])
        if expression.get("function") == "abs":
            return abs(args[0])
    raise RuntimeError("unsupported expression")


def resolve_python_callable(solution_path: Path, entrypoint: str) -> Any:
    spec = importlib.util.spec_from_file_location("babel_code_goat_solution", solution_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load solution")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidate = getattr(module, entrypoint, None)
    if callable(candidate):
        return candidate

    for _, obj in inspect.getmembers(module, inspect.isclass):
        method = getattr(obj, entrypoint, None)
        if callable(method):
            try:
                instance = obj()
            except Exception:
                continue
            bound = getattr(instance, entrypoint, None)
            if callable(bound):
                return bound
    raise RuntimeError("entrypoint not found")


@contextlib.contextmanager
def python_time_limit(timeout_ms: int | None):
    if timeout_ms is None:
        yield
        return

    def raise_timeout(_signum: int, _frame: Any) -> None:
        raise ExecutionTimeout()

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, raise_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, max(timeout_ms, 1) / 1000)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
        signal.signal(signal.SIGALRM, previous_handler)


def await_python_value(value: Any, timeout_ms: int | None) -> Any:
    if not inspect.isawaitable(value):
        return value

    async def resolve() -> Any:
        return await value

    if timeout_ms is None:
        return asyncio.run(resolve())
    return asyncio.run(asyncio.wait_for(resolve(), timeout=timeout_ms / 1000))


def effective_timeout_ms(timeout_ms: int | None, deadline: float | None) -> int | None:
    if deadline is None:
        return timeout_ms
    remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
    if timeout_ms is None:
        return remaining_ms
    return min(timeout_ms, remaining_ms)


def execute_python_tests(
    solution_path: Path,
    entrypoint: str,
    tests: list[dict[str, Any]],
    default_tol: float = 0.0,
    selected_id: str | None = None,
    timeout_ms: int | None = None,
    total_timeout_ms: int | None = None,
) -> dict[str, Any]:
    tests = scoped_tests(tests, selected_id) or []
    deadline = time.monotonic() + total_timeout_ms / 1000 if total_timeout_ms is not None else None
    callable_under_test = None
    if any(test["kind"] != "loop" for test in tests):
        try:
            callable_under_test = resolve_python_callable(solution_path, entrypoint)
        except Exception:
            return make_result("fail", [], [test["id"] for test in tests])

    passed: list[str] = []
    failed: list[str] = []
    for index, test in enumerate(tests):
        if deadline is not None and time.monotonic() >= deadline:
            failed.extend(item["id"] for item in tests[index:])
            break
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        ok = False
        timed_out = False
        current_timeout_ms = effective_timeout_ms(timeout_ms, deadline)
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                try:
                    with python_time_limit(current_timeout_ms):
                        if test["kind"] == "loop":
                            ok = bool(test.get("expected"))
                            actual = None
                            raised = False
                            raised_exc = None
                        else:
                            raised = False
                            raised_exc = None
                            decoded_args = [decode_arg(arg) for arg in test["args"]]
                            try:
                                actual = callable_under_test(*decoded_args)
                                actual = await_python_value(actual, current_timeout_ms)
                                if test.get("mutation_arg_index") is not None:
                                    actual = decoded_args[test["mutation_arg_index"]]
                            except (ExecutionTimeout, TimeoutError, asyncio.TimeoutError):
                                timed_out = True
                                raised = False
                                raised_exc = None
                                actual = None
                            except Exception as exc:
                                raised = True
                                raised_exc = exc
                                actual = None
                except (ExecutionTimeout, TimeoutError, asyncio.TimeoutError):
                    timed_out = True
                    raised = False
                    raised_exc = None
                    actual = None
                if timed_out:
                    ok = False
                elif test["kind"] == "loop":
                    pass
                elif test["kind"] == "raises":
                    ok = (
                        raised
                        and raised_exc is not None
                        and exception_matches(raised_exc, test.get("expected_exception"))
                        and message_matches(raised_exc, test.get("message_match"))
                    )
                elif raised:
                    ok = False
                elif test["kind"] == "expr":
                    ok = bool(evaluate_expression(test["expression"], actual, tolerance_policy(test, default_tol)))
                elif test["kind"] == "eq":
                    ok = deep_compare(test["expected"], normalize_comparable(actual), tolerance_policy(test, default_tol))
                elif test["kind"] == "neq":
                    ok = not deep_compare(
                        test["expected"], normalize_comparable(actual), tolerance_policy(test, default_tol)
                    )
                elif test["kind"] == "truthy":
                    ok = bool(actual)
                elif test["kind"] == "falsy":
                    ok = not bool(actual)
        except Exception:
            ok = False

        if test.get("expect_stdout") is not None and stdout_buffer.getvalue() != test["expect_stdout"]:
            ok = False
        if test.get("expect_stderr") is not None and stderr_buffer.getvalue() != test["expect_stderr"]:
            ok = False

        if ok:
            passed.append(test["id"])
        else:
            failed.append(test["id"])
        if (
            timed_out
            and deadline is not None
            and (timeout_ms is None or (current_timeout_ms is not None and current_timeout_ms < timeout_ms))
            and index + 1 < len(tests)
        ):
            failed.extend(item["id"] for item in tests[index + 1 :])
            break
        if deadline is not None and time.monotonic() >= deadline and index + 1 < len(tests):
            failed.extend(item["id"] for item in tests[index + 1 :])
            break
    return make_result("pass" if not failed else "fail", passed, failed)


def python_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    return f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = os.environ.get("BABEL_CODE_GOAT_ROOT", str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from babel_code_goat import execute_python_tests, print_result

PAYLOAD = {payload!r}

def env_int(name):
    value = os.environ.get(name)
    return int(value) if value else None

def main():
    if len(sys.argv) != 2:
        return print_result({{"status": "error", "passed": [], "failed": []}})
    data = json.loads(PAYLOAD)
    result = execute_python_tests(
        Path(sys.argv[1]),
        data["entrypoint"],
        data["tests"],
        float(os.environ.get("BABEL_CODE_GOAT_TOL", "0")),
        os.environ.get("{RUN_ID_ENV}") or None,
        env_int("{TIMEOUT_MS_ENV}"),
        env_int("{TOTAL_TIMEOUT_MS_ENV}"),
    )
    return print_result(result)

if __name__ == "__main__":
    raise SystemExit(main())
"""


def tester_payload_json(entrypoint: str, tests: list[TestCase]) -> str:
    return json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )


def javascript_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = tester_payload_json(entrypoint, tests)
    return f"""#!/usr/bin/env node
const path = require("path");
const {{ pathToFileURL }} = require("url");
const payload = {payload};
const TAG = "{TAG_KEY}";
const defaultTol = Number(process.env.BABEL_CODE_GOAT_TOL || "0");
const selectedId = process.env.{RUN_ID_ENV} || null;
const timeoutMs = process.env.{TIMEOUT_MS_ENV} ? Number(process.env.{TIMEOUT_MS_ENV}) : null;
const totalTimeoutMs = process.env.{TOTAL_TIMEOUT_MS_ENV} ? Number(process.env.{TOTAL_TIMEOUT_MS_ENV}) : null;

class BcgTimeout extends Error {{}}

function scopedTests() {{
  return selectedId ? payload.tests.filter(test => test.id === selectedId) : payload.tests;
}}

function withTimeout(work, ms) {{
  if (!ms || ms <= 0) return work();
  return Promise.race([
    work(),
    new Promise((_, reject) => setTimeout(() => reject(new BcgTimeout("timeout")), ms)),
  ]);
}}

function remainingTimeout(deadline) {{
  if (!deadline) return timeoutMs;
  const remaining = Math.max(0, deadline - Date.now());
  return timeoutMs ? Math.min(timeoutMs, remaining) : remaining;
}}

function isTagged(value, typeName) {{
  return value && typeof value === "object" && !Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, TAG) && (!typeName || value[TAG] === typeName);
}}

function stable(value) {{
  return JSON.stringify(value, (key, inner) => {{
    if (!inner || typeof inner !== "object" || Array.isArray(inner)) return inner;
    const out = {{}};
    for (const objectKey of Object.keys(inner).sort()) out[objectKey] = inner[objectKey];
    return out;
  }});
}}

function sortValues(values) {{
  return values.sort((a, b) => stable(a).localeCompare(stable(b)));
}}

function normalize(value) {{
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return value;
  if (typeof value === "bigint") return Number(value);
  if (isTagged(value)) return value;
  if (Array.isArray(value)) return value.map(normalize);
  if (value instanceof Set) return {{[TAG]: "set", items: sortValues(Array.from(value, normalize))}};
  if (value instanceof Map) {{
    const items = Array.from(value.entries(), ([key, item]) => [normalize(key), normalize(item)]);
    items.sort((a, b) => stable(a[0]).localeCompare(stable(b[0])));
    return {{[TAG]: "dict", items}};
  }}
  if (typeof value === "object") {{
    const items = Object.keys(value).sort().map(key => [key, normalize(value[key])]);
    return {{[TAG]: "dict", items}};
  }}
  return value;
}}

function numericValue(value) {{
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (isTagged(value, "decimal")) return Number(value.value);
  return null;
}}

function tolerancePolicy(test) {{
  return test.tolerance || {{mode: "default", abs: defaultTol, rel: 0}};
}}

function numericEqual(expected, actual, tolerance) {{
  const expectedNum = numericValue(expected);
  const actualNum = numericValue(actual);
  if (expectedNum === null || actualNum === null) return false;
  const diff = Math.abs(actualNum - expectedNum);
  const absTol = Number(tolerance.abs || 0);
  if (tolerance.mode === "absdiff" && tolerance.strict) return diff < absTol;
  const relTol = Number(tolerance.rel || 0);
  return diff <= Math.max(absTol, relTol * Math.max(Math.abs(expectedNum), Math.abs(actualNum)));
}}

function compareUnordered(expectedItems, actualItems, tolerance) {{
  if (expectedItems.length !== actualItems.length) return false;
  const used = new Set();
  for (const expectedItem of expectedItems) {{
    let matched = false;
    for (let index = 0; index < actualItems.length; index++) {{
      if (used.has(index)) continue;
      if (deepEqual(expectedItem, actualItems[index], tolerance)) {{
        used.add(index);
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

function compareDictItems(expectedItems, actualItems, tolerance) {{
  if (expectedItems.length !== actualItems.length) return false;
  const used = new Set();
  const exact = {{mode: "default", abs: 0, rel: 0}};
  for (const [expectedKey, expectedValue] of expectedItems) {{
    let matched = false;
    for (let index = 0; index < actualItems.length; index++) {{
      if (used.has(index)) continue;
      const [actualKey, actualValue] = actualItems[index];
      if (deepEqual(expectedKey, actualKey, exact) && deepEqual(expectedValue, actualValue, tolerance)) {{
        used.add(index);
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

function deepEqual(expected, actual, tolerance) {{
  if (numericValue(expected) !== null && numericValue(actual) !== null) return numericEqual(expected, actual, tolerance);
  if (Array.isArray(expected) || Array.isArray(actual)) {{
    return Array.isArray(expected) && Array.isArray(actual) && expected.length === actual.length &&
      expected.every((item, index) => deepEqual(item, actual[index], tolerance));
  }}
  if (isTagged(expected) || isTagged(actual)) {{
    if (!isTagged(expected) || !isTagged(actual)) return false;
    const expectedType = expected[TAG];
    const actualType = actual[TAG];
    if (expectedType === "decimal" || actualType === "decimal") return numericEqual(expected, actual, tolerance);
    if (expectedType === "dict" && actualType === "dict") return compareDictItems(expected.items, actual.items, tolerance);
    if (expectedType === "set" && actualType === "set") return compareUnordered(expected.items, actual.items, tolerance);
    if ((expectedType === "counter" && actualType === "counter") || (expectedType === "counter" && actualType === "dict") || (expectedType === "dict" && actualType === "counter")) return compareDictItems(expected.items, actual.items, tolerance);
    if (expectedType === "deque" && actualType === "deque") return expected.items.length === actual.items.length && expected.items.every((item, index) => deepEqual(item, actual.items[index], tolerance));
    return false;
  }}
  return Object.is(expected, actual);
}}

function decodeArg(value) {{
  if (Array.isArray(value)) return value.map(decodeArg);
  if (!isTagged(value)) return value;
  if (value[TAG] === "decimal") return Number(value.value);
  if (value[TAG] === "dict") return new Map(value.items.map(([key, item]) => [decodeArg(key), decodeArg(item)]));
  if (value[TAG] === "set") return new Set(value.items.map(decodeArg));
  if (value[TAG] === "counter") return new Map(value.items.map(([key, count]) => [decodeArg(key), decodeArg(count)]));
  if (value[TAG] === "deque") return value.items.map(decodeArg);
  return value;
}}

function exceptionMatches(error, expectedException) {{
  if (!expectedException) return true;
  const names = new Set([error && error.name, error && error.constructor && error.constructor.name].filter(Boolean));
  return names.has(expectedException);
}}

function messageMatches(error, matcher) {{
  if (!matcher) return true;
  const message = String(error && error.message !== undefined ? error.message : error);
  if (matcher.mode === "contains") return message.includes(matcher.pattern || "");
  if (matcher.mode === "regex") return new RegExp(matcher.pattern || "").test(message);
  return false;
}}

function containsValue(container, needle, tolerance) {{
  if (typeof container === "string" && typeof needle === "string") return container.includes(needle);
  const normalizedNeedle = normalize(needle);
  if (isTagged(container, "dict")) return container.items.some(([key]) => deepEqual(key, normalizedNeedle, tolerance));
  if (isTagged(container, "set") || isTagged(container, "deque")) return container.items.some(item => deepEqual(item, normalizedNeedle, tolerance));
  if (Array.isArray(container)) return container.some(item => deepEqual(normalize(item), normalizedNeedle, tolerance));
  if (container instanceof Set) return Array.from(container).some(item => deepEqual(normalize(item), normalizedNeedle, tolerance));
  if (container instanceof Map) return Array.from(container.keys()).some(key => deepEqual(normalize(key), normalizedNeedle, tolerance));
  if (container && typeof container === "object") return Object.keys(container).some(key => deepEqual(key, normalizedNeedle, tolerance));
  return false;
}}

function expressionIndex(value, index) {{
  if (isTagged(value, "dict")) {{
    for (const [key, item] of value.items) {{
      if (deepEqual(key, normalize(index), {{mode: "default", abs: 0, rel: 0}})) return item;
    }}
    throw new Error("missing key");
  }}
  if (isTagged(value, "deque")) return value.items[index];
  if (value instanceof Map) return value.get(index);
  return value[index];
}}

function expressionSorted(value) {{
  const items = typeof value === "string" ? value.split("") :
    isTagged(value, "set") || isTagged(value, "deque") ? value.items.slice() :
    Array.from(value);
  return items.sort((a, b) => {{
    const aNum = numericValue(a);
    const bNum = numericValue(b);
    if (aNum !== null && bNum !== null) return aNum - bNum;
    return stable(normalize(a)).localeCompare(stable(normalize(b)));
  }});
}}

function evaluateExpression(expression, actual, tolerance) {{
  if (expression.op === "const") return expression.value;
  if (expression.op === "actual") return actual;
  if (expression.op === "unary") {{
    const operand = evaluateExpression(expression.operand, actual, tolerance);
    if (expression.operator === "not") return !operand;
    if (expression.operator === "neg") return -operand;
    if (expression.operator === "pos") return +operand;
  }}
  if (expression.op === "binary") {{
    const left = evaluateExpression(expression.left, actual, tolerance);
    const right = evaluateExpression(expression.right, actual, tolerance);
    if (expression.operator === "add") return left + right;
    if (expression.operator === "sub") return left - right;
    if (expression.operator === "mul") return left * right;
    if (expression.operator === "div") return left / right;
    if (expression.operator === "floordiv") return Math.floor(left / right);
    if (expression.operator === "mod") return left % right;
    if (expression.operator === "pow") return left ** right;
  }}
  if (expression.op === "bool") {{
    const values = expression.values.map(value => evaluateExpression(value, actual, tolerance));
    if (expression.operator === "and") return values.every(Boolean);
    if (expression.operator === "or") return values.some(Boolean);
  }}
  if (expression.op === "compare") {{
    const left = evaluateExpression(expression.left, actual, tolerance);
    const right = evaluateExpression(expression.right, actual, tolerance);
    if (expression.operator === "eq") return deepEqual(normalize(left), normalize(right), tolerance);
    if (expression.operator === "neq") return !deepEqual(normalize(left), normalize(right), tolerance);
    if (expression.operator === "in") return containsValue(right, left, tolerance);
    if (expression.operator === "not_in") return !containsValue(right, left, tolerance);
    const leftNum = numericValue(normalize(left));
    const rightNum = numericValue(normalize(right));
    const comparableLeft = leftNum === null ? left : leftNum;
    const comparableRight = rightNum === null ? right : rightNum;
    if (expression.operator === "lt") return comparableLeft < comparableRight;
    if (expression.operator === "lte") return comparableLeft <= comparableRight;
    if (expression.operator === "gt") return comparableLeft > comparableRight;
    if (expression.operator === "gte") return comparableLeft >= comparableRight;
  }}
  if (expression.op === "index") {{
    return expressionIndex(evaluateExpression(expression.value, actual, tolerance), evaluateExpression(expression.index, actual, tolerance));
  }}
  if (expression.op === "call") {{
    const args = expression.args.map(arg => evaluateExpression(arg, actual, tolerance));
    if (expression.function === "sorted") return expressionSorted(args[0]);
    if (expression.function === "abs") return Math.abs(args[0]);
  }}
  throw new Error("unsupported expression");
}}

function findCallable(moduleValue, entrypoint) {{
  if (typeof moduleValue === "function" && moduleValue.name === entrypoint) return moduleValue;
  if (typeof moduleValue === "function") {{
    try {{
      const instance = new moduleValue();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
  }}
  if (moduleValue && typeof moduleValue[entrypoint] === "function") return moduleValue[entrypoint].bind(moduleValue);
  if (moduleValue && moduleValue.default && typeof moduleValue.default === "function" && moduleValue.default.name === entrypoint) return moduleValue.default;
  if (moduleValue && moduleValue.default && typeof moduleValue.default === "function") {{
    try {{
      const instance = new moduleValue.default();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
  }}
  if (moduleValue && moduleValue.default && typeof moduleValue.default[entrypoint] === "function") return moduleValue.default[entrypoint].bind(moduleValue.default);
  for (const value of Object.values(moduleValue || {{}})) {{
    if (typeof value !== "function") continue;
    if (value.name === entrypoint) return value;
    try {{
      const instance = new value();
      if (typeof instance[entrypoint] === "function") return instance[entrypoint].bind(instance);
    }} catch (_) {{}}
    if (typeof value[entrypoint] === "function") return value[entrypoint].bind(value);
  }}
  throw new Error("entrypoint not found");
}}

async function loadSolution(solutionPath) {{
  try {{
    return require(solutionPath);
  }} catch (error) {{
    return await import(pathToFileURL(solutionPath).href);
  }}
}}

async function main() {{
  if (process.argv.length !== 3) {{
    console.log(JSON.stringify({{status: "error", passed: [], failed: []}}));
    return 2;
  }}
  const solutionPath = path.resolve(process.argv[2]);
  const tests = scopedTests();
  const deadline = totalTimeoutMs ? Date.now() + totalTimeoutMs : null;
  let fn;
  const hasExecutableTests = tests.some(test => test.kind !== "loop");
  if (hasExecutableTests) {{
    try {{
      fn = findCallable(await loadSolution(solutionPath), payload.entrypoint);
    }} catch (error) {{
      console.log(JSON.stringify({{status: "fail", passed: [], failed: tests.map(test => test.id)}}));
      return 1;
    }}
  }}

  const passed = [];
  const failed = [];
  for (let index = 0; index < tests.length; index++) {{
    const test = tests[index];
    if (deadline && Date.now() >= deadline) {{
      failed.push(...tests.slice(index).map(item => item.id));
      break;
    }}
    let stdout = "";
    let stderr = "";
    const oldOut = process.stdout.write;
    const oldErr = process.stderr.write;
    process.stdout.write = function(chunk, encoding, cb) {{ stdout += String(chunk); if (typeof cb === "function") cb(); return true; }};
    process.stderr.write = function(chunk, encoding, cb) {{ stderr += String(chunk); if (typeof cb === "function") cb(); return true; }};
    let ok = false;
    let timedOut = false;
    const currentTimeoutMs = remainingTimeout(deadline);
    try {{
      await withTimeout(async () => {{
        let actual;
        let raised = false;
        let raisedError = null;
        if (test.kind === "loop") {{
          ok = !!test.expected;
        }} else {{
          const decodedArgs = test.args.map(decodeArg);
          try {{
            actual = fn(...decodedArgs);
            if (actual && typeof actual.then === "function") actual = await actual;
            if (test.mutation_arg_index !== null && test.mutation_arg_index !== undefined) actual = decodedArgs[test.mutation_arg_index];
          }} catch (error) {{
            raised = true;
            raisedError = error;
          }}
        }}
        if (test.kind === "loop") {{}}
        else if (test.kind === "raises") ok = raised && exceptionMatches(raisedError, test.expected_exception) && messageMatches(raisedError, test.message_match);
        else if (raised) ok = false;
        else if (test.kind === "expr") ok = !!evaluateExpression(test.expression, actual, tolerancePolicy(test));
        else if (test.kind === "eq") ok = deepEqual(test.expected, normalize(actual), tolerancePolicy(test));
        else if (test.kind === "neq") ok = !deepEqual(test.expected, normalize(actual), tolerancePolicy(test));
        else if (test.kind === "truthy") ok = !!actual;
        else if (test.kind === "falsy") ok = !actual;
      }}, currentTimeoutMs);
    }} catch (error) {{
      if (error instanceof BcgTimeout) timedOut = true;
      ok = false;
    }} finally {{
      process.stdout.write = oldOut;
      process.stderr.write = oldErr;
    }}
    if (!timedOut && test.expect_stdout !== null && stdout !== test.expect_stdout) ok = false;
    if (!timedOut && test.expect_stderr !== null && stderr !== test.expect_stderr) ok = false;
    (ok ? passed : failed).push(test.id);
    if (timedOut && deadline && (!timeoutMs || currentTimeoutMs < timeoutMs) && index + 1 < tests.length) {{
      failed.push(...tests.slice(index + 1).map(item => item.id));
      break;
    }}
    if (deadline && Date.now() >= deadline && index + 1 < tests.length) {{
      failed.push(...tests.slice(index + 1).map(item => item.id));
      break;
    }}
  }}
  const status = failed.length === 0 ? "pass" : "fail";
  console.log(JSON.stringify({{status, passed, failed}}));
  return status === "pass" ? 0 : 1;
}}

main().then(code => process.exit(code)).catch(() => {{
  console.log(JSON.stringify({{status: "error", passed: [], failed: []}}));
  process.exit(2);
}});
"""


def contains_tagged_type(value: Any, type_name: str) -> bool:
    if is_tagged(value, type_name):
        return True
    if isinstance(value, list):
        return any(contains_tagged_type(item, type_name) for item in value)
    if is_tagged(value, "dict") or is_tagged(value, "counter"):
        return any(
            contains_tagged_type(key, type_name) or contains_tagged_type(item, type_name)
            for key, item in value["items"]
        )
    if is_tagged(value, "set") or is_tagged(value, "deque"):
        return any(contains_tagged_type(item, type_name) for item in value["items"])
    return False


def test_contains_tagged_type(test: TestCase, type_name: str) -> bool:
    values: list[Any] = list(test.args)
    if test.expected is not None:
        values.append(test.expected)
    if test.expression is not None:
        values.append(test.expression)
    return any(contains_tagged_type(value, type_name) for value in values)


def cpp_string(value: str) -> str:
    return json.dumps(value)


def rust_string(value: str) -> str:
    return json.dumps(value)


def type_without_optional(type_name: str) -> str:
    if type_name.startswith("std::optional<") and type_name.endswith(">"):
        return type_name[len("std::optional<") : -1]
    if type_name.startswith("Option<") and type_name.endswith(">"):
        return type_name[len("Option<") : -1]
    return type_name


def merge_cpp_types(types: list[str]) -> str:
    non_null = [type_name for type_name in types if type_name != "std::nullopt_t"]
    has_null = len(non_null) != len(types)
    if not non_null:
        return "std::optional<long long>"
    first = non_null[0]
    if any(type_name != first for type_name in non_null):
        if all(type_name in {"long long", "long double"} for type_name in non_null):
            first = "long double"
        else:
            first = "BCG::Value"
    if has_null and not first.startswith("std::optional<"):
        return f"std::optional<{first}>"
    return first


def merge_rust_types(types: list[str]) -> str:
    non_null = [type_name for type_name in types if type_name == "None" or type_name != "None"]
    has_null = "None" in non_null
    non_null = [type_name for type_name in non_null if type_name != "None"]
    if not non_null:
        return "Option<i64>"
    first = non_null[0]
    if any(type_name != first for type_name in non_null):
        if all(type_name in {"i64", "f64"} for type_name in non_null):
            first = "f64"
        else:
            first = "BcgValue"
    if has_null and not first.startswith("Option<"):
        return f"Option<{first}>"
    return first


def cpp_type(value: Any) -> str:
    if value is None:
        return "std::nullopt_t"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "long long"
    if isinstance(value, float):
        return "long double"
    if isinstance(value, str):
        return "std::string"
    if isinstance(value, list):
        item_type = merge_cpp_types([cpp_type(item) for item in value]) if value else "long long"
        return f"std::vector<{item_type}>"
    if is_tagged(value, "decimal"):
        return "long double"
    if is_tagged(value, "set"):
        item_type = merge_cpp_types([cpp_type(item) for item in value["items"]]) if value["items"] else "long long"
        return f"std::set<{item_type}>"
    if is_tagged(value, "deque"):
        item_type = merge_cpp_types([cpp_type(item) for item in value["items"]]) if value["items"] else "long long"
        return f"std::vector<{item_type}>"
    if is_tagged(value, "dict") or is_tagged(value, "counter"):
        key_type = merge_cpp_types([cpp_type(key) for key, _ in value["items"]]) if value["items"] else "std::string"
        item_type = merge_cpp_types([cpp_type(item) for _, item in value["items"]]) if value["items"] else "long long"
        return f"std::map<{key_type}, {item_type}>"
    return "BCG::Value"


def rust_type(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "i64"
    if isinstance(value, float):
        return "f64"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        item_type = merge_rust_types([rust_type(item) for item in value]) if value else "i64"
        return f"Vec<{item_type}>"
    if is_tagged(value, "decimal"):
        return "f64"
    if is_tagged(value, "set"):
        item_type = merge_rust_types([rust_type(item) for item in value["items"]]) if value["items"] else "i64"
        return f"std::collections::HashSet<{item_type}>"
    if is_tagged(value, "deque"):
        item_type = merge_rust_types([rust_type(item) for item in value["items"]]) if value["items"] else "i64"
        return f"Vec<{item_type}>"
    if is_tagged(value, "dict") or is_tagged(value, "counter"):
        key_type = merge_rust_types([rust_type(key) for key, _ in value["items"]]) if value["items"] else "String"
        item_type = merge_rust_types([rust_type(item) for _, item in value["items"]]) if value["items"] else "i64"
        return f"std::collections::BTreeMap<{key_type}, {item_type}>"
    return "BcgValue"


def cpp_literal(value: Any, expected_type: str | None = None) -> str:
    if expected_type and expected_type.startswith("std::optional<"):
        inner = expected_type[len("std::optional<") : -1]
        if value is None:
            return "std::nullopt"
        return f"{expected_type}{{{cpp_literal(value, inner)}}}"
    if value is None:
        return "std::nullopt"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{repr(value)}L"
    if isinstance(value, str):
        return f"std::string({cpp_string(value)})"
    if isinstance(value, list):
        item_type = type_without_optional(expected_type[len("std::vector<") : -1]) if expected_type and expected_type.startswith("std::vector<") else merge_cpp_types([cpp_type(item) for item in value])
        container_type = expected_type or f"std::vector<{item_type}>"
        return f"{container_type}{{{', '.join(cpp_literal(item, item_type) for item in value)}}}"
    if is_tagged(value, "decimal"):
        return f"{value['value']}L"
    if is_tagged(value, "set"):
        item_type = type_without_optional(expected_type[len("std::set<") : -1]) if expected_type and expected_type.startswith("std::set<") else merge_cpp_types([cpp_type(item) for item in value["items"]])
        container_type = expected_type or f"std::set<{item_type}>"
        return f"{container_type}{{{', '.join(cpp_literal(item, item_type) for item in value['items'])}}}"
    if is_tagged(value, "deque"):
        item_type = merge_cpp_types([cpp_type(item) for item in value["items"]]) if value["items"] else "long long"
        container_type = expected_type or f"std::vector<{item_type}>"
        return f"{container_type}{{{', '.join(cpp_literal(item, item_type) for item in value['items'])}}}"
    if is_tagged(value, "dict") or is_tagged(value, "counter"):
        if expected_type and expected_type.startswith("std::map<"):
            inner = expected_type[len("std::map<") : -1]
            key_type, item_type = [part.strip() for part in inner.split(",", 1)]
        else:
            key_type = merge_cpp_types([cpp_type(key) for key, _ in value["items"]]) if value["items"] else "std::string"
            item_type = merge_cpp_types([cpp_type(item) for _, item in value["items"]]) if value["items"] else "long long"
        container_type = expected_type or f"std::map<{key_type}, {item_type}>"
        items = ", ".join(
            f"{{{cpp_literal(key, key_type)}, {cpp_literal(item, item_type)}}}" for key, item in value["items"]
        )
        return f"{container_type}{{{items}}}"
    return "BCG::Value{}"


def rust_literal(value: Any, expected_type: str | None = None) -> str:
    if expected_type and expected_type.startswith("Option<"):
        inner = expected_type[len("Option<") : -1]
        if value is None:
            return "None"
        return f"Some({rust_literal(value, inner)})"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}_i64"
    if isinstance(value, float):
        return f"{repr(value)}_f64"
    if isinstance(value, str):
        return f"String::from({rust_string(value)})"
    if isinstance(value, list):
        item_type = expected_type[len("Vec<") : -1] if expected_type and expected_type.startswith("Vec<") else merge_rust_types([rust_type(item) for item in value])
        return f"vec![{', '.join(rust_literal(item, item_type) for item in value)}]"
    if is_tagged(value, "decimal"):
        return f"{value['value']}_f64"
    if is_tagged(value, "set"):
        item_type = (
            expected_type[len("std::collections::HashSet<") : -1]
            if expected_type and expected_type.startswith("std::collections::HashSet<")
            else merge_rust_types([rust_type(item) for item in value["items"]])
        )
        items = "".join(f"s.insert({rust_literal(item, item_type)});" for item in value["items"])
        return f"{{ let mut s = std::collections::HashSet::new(); {items} s }}"
    if is_tagged(value, "deque"):
        item_type = merge_rust_types([rust_type(item) for item in value["items"]]) if value["items"] else "i64"
        return f"vec![{', '.join(rust_literal(item, item_type) for item in value['items'])}]"
    if is_tagged(value, "dict") or is_tagged(value, "counter"):
        if expected_type and expected_type.startswith("std::collections::BTreeMap<"):
            inner = expected_type[len("std::collections::BTreeMap<") : -1]
            key_type, item_type = [part.strip() for part in inner.split(",", 1)]
        else:
            key_type = merge_rust_types([rust_type(key) for key, _ in value["items"]]) if value["items"] else "String"
            item_type = merge_rust_types([rust_type(item) for _, item in value["items"]]) if value["items"] else "i64"
        items = "".join(
            f"m.insert({rust_literal(key, key_type)}, {rust_literal(item, item_type)});"
            for key, item in value["items"]
        )
        return f"{{ let mut m = std::collections::BTreeMap::new(); {items} m }}"
    return "BcgValue::Null"


def cpp_bcg_expr(value: Any) -> str:
    return f"BCG::value({cpp_literal(value)})"


def rust_bcg_expr(value: Any) -> str:
    return f"ToBcg::to_bcg(&{rust_literal(value)})"


def cpp_expr(expression: dict[str, Any], actual_expr: str = "actual") -> str:
    op = expression.get("op")
    if op == "const":
        return cpp_bcg_expr(expression.get("value"))
    if op == "actual":
        return actual_expr
    if op == "index":
        return f"BCG::index({cpp_expr(expression['value'], actual_expr)}, {cpp_expr(expression['index'], actual_expr)})"
    if op == "call" and expression.get("function") == "sorted":
        return f"BCG::sorted({cpp_expr(expression['args'][0], actual_expr)})"
    if op == "call" and expression.get("function") == "abs":
        return f"BCG::abs_value({cpp_expr(expression['args'][0], actual_expr)})"
    if op == "binary":
        return (
            f"BCG::binary({cpp_string(expression.get('operator', ''))}, "
            f"{cpp_expr(expression['left'], actual_expr)}, {cpp_expr(expression['right'], actual_expr)})"
        )
    if op == "unary":
        return f"BCG::unary({cpp_string(expression.get('operator', ''))}, {cpp_expr(expression['operand'], actual_expr)})"
    if op == "bool":
        items = ", ".join(cpp_expr(item, actual_expr) for item in expression["values"])
        return f"BCG::bool_expr({cpp_string(expression.get('operator', ''))}, std::vector<BCG::Value>{{{items}}})"
    if op == "compare":
        return (
            f"BCG::compare_value({cpp_string(expression.get('operator', ''))}, "
            f"{cpp_expr(expression['left'], actual_expr)}, {cpp_expr(expression['right'], actual_expr)}, tolerance)"
        )
    return "BCG::Value{}"


def rust_expr(expression: dict[str, Any], actual_expr: str = "actual.clone()") -> str:
    op = expression.get("op")
    if op == "const":
        return rust_bcg_expr(expression.get("value"))
    if op == "actual":
        return actual_expr
    if op == "index":
        return f"bcg_index({rust_expr(expression['value'], actual_expr)}, {rust_expr(expression['index'], actual_expr)})"
    if op == "call" and expression.get("function") == "sorted":
        return f"bcg_sorted({rust_expr(expression['args'][0], actual_expr)})"
    if op == "call" and expression.get("function") == "abs":
        return f"bcg_abs({rust_expr(expression['args'][0], actual_expr)})"
    if op == "binary":
        return (
            f"bcg_binary({rust_string(expression.get('operator', ''))}, "
            f"{rust_expr(expression['left'], actual_expr)}, {rust_expr(expression['right'], actual_expr)})"
        )
    if op == "unary":
        return f"bcg_unary({rust_string(expression.get('operator', ''))}, {rust_expr(expression['operand'], actual_expr)})"
    if op == "bool":
        items = ", ".join(rust_expr(item, actual_expr) for item in expression["values"])
        return f"bcg_bool_expr({rust_string(expression.get('operator', ''))}, vec![{items}])"
    if op == "compare":
        return (
            f"bcg_compare_value({rust_string(expression.get('operator', ''))}, "
            f"{rust_expr(expression['left'], actual_expr)}, {rust_expr(expression['right'], actual_expr)}, &tolerance)"
        )
    return "BcgValue::Null"


def cpp_tolerance_code(test: TestCase, index: int) -> str:
    if not test.tolerance:
        return f"    auto tol_{index} = tolerance;\n"
    abs_tol = test.tolerance.get("abs", 0.0)
    rel_tol = test.tolerance.get("rel", 0.0)
    strict = "true" if test.tolerance.get("strict") else "false"
    return f"    BCG::Tolerance tol_{index}{{{abs_tol}L, {rel_tol}L, {strict}}};\n"


def rust_tolerance_code(test: TestCase, index: int) -> str:
    if not test.tolerance:
        return f"    let tol_{index} = tolerance;\n"
    abs_tol = test.tolerance.get("abs", 0.0)
    rel_tol = test.tolerance.get("rel", 0.0)
    strict = "true" if test.tolerance.get("strict") else "false"
    return f"    let tol_{index} = BcgTolerance {{ abs: {abs_tol}_f64, rel: {rel_tol}_f64, strict: {strict} }};\n"


def cpp_call_code(entrypoint: str, test: TestCase, index: int) -> str:
    arg_lines: list[str] = []
    arg_names: list[str] = []
    for arg_index, arg in enumerate(test.args):
        type_name = cpp_type(arg)
        name = f"arg_{index}_{arg_index}"
        arg_lines.append(f"    auto {name} = {cpp_literal(arg, type_name)};")
        arg_names.append(name)
    args = ", ".join(arg_names)
    if test.mutation_arg_index is not None:
        actual_expr = f"BCG::value(arg_{index}_{test.mutation_arg_index})"
        call_line = f"      BCG::call_any([&]() -> decltype(auto) {{ return {entrypoint}({args}); }});"
    else:
        actual_expr = "actual"
        call_line = f"      actual = BCG::call_any([&]() -> decltype(auto) {{ return {entrypoint}({args}); }});"
    body = "\n".join(arg_lines)
    body += f"""
    bool raised = false;
    std::string message;
    BCG::Value actual;
    try {{
{call_line}
"""
    if test.mutation_arg_index is not None:
        body += f"      actual = {actual_expr};\n"
    body += """    } catch (const std::exception& e) {
      raised = true;
      message = e.what();
    } catch (...) {
      raised = true;
      message = "";
    }
"""
    return body


def cpp_test_case_code(entrypoint: str, test: TestCase, index: int) -> str:
    if test.kind == "loop":
        ok = "true" if test.expected else "false"
        return f"  record({cpp_string(test.id)}, {ok});\n"
    body = cpp_call_code(entrypoint, test, index)
    if test.kind == "raises":
        expected = cpp_string(test.expected_exception or "")
        matcher = cpp_string(stable_json(test.message_match or {}))
        check = f"raised && BCG::exception_matches({expected}) && BCG::message_matches(message, {matcher})"
    elif test.kind == "expr" and test.expression is not None:
        expr = test.expression
        if expr.get("op") == "compare":
            left = cpp_expr(expr["left"])
            right = cpp_expr(expr["right"])
            operator = expr.get("operator")
            if operator == "eq":
                check = f"!raised && BCG::equal({left}, {right}, tolerance)"
            elif operator == "neq":
                check = f"!raised && !BCG::equal({left}, {right}, tolerance)"
            elif operator == "in":
                check = f"!raised && BCG::contains({right}, {left}, tolerance)"
            elif operator == "not_in":
                check = f"!raised && !BCG::contains({right}, {left}, tolerance)"
            else:
                check = f"!raised && BCG::truthy({cpp_expr(expr)})"
        else:
            check = f"!raised && BCG::truthy({cpp_expr(expr)})"
    elif test.kind == "eq":
        check = f"!raised && BCG::equal({cpp_bcg_expr(test.expected)}, actual, tolerance)"
    elif test.kind == "neq":
        check = f"!raised && !BCG::equal({cpp_bcg_expr(test.expected)}, actual, tolerance)"
    elif test.kind == "truthy":
        check = "!raised && BCG::truthy(actual)"
    elif test.kind == "falsy":
        check = "!raised && !BCG::truthy(actual)"
    else:
        check = "false"
    check = check.replace("tolerance", f"tol_{index}")
    return body + cpp_tolerance_code(test, index) + f"    record({cpp_string(test.id)}, {check});\n"


def cpp_guarded_test_case_code(entrypoint: str, test: TestCase, index: int) -> str:
    body = cpp_test_case_code(entrypoint, test, index)
    return f"  if (run_id.empty() || run_id == {cpp_string(test.id)}) {{\n{body}  }}\n"


def rust_arg_pass(name: str, test: TestCase, arg_index: int) -> str:
    if test.mutation_arg_index == arg_index:
        return f"&mut {name}"
    return name


def rust_call_code(entrypoint: str, test: TestCase, index: int) -> str:
    arg_lines: list[str] = []
    arg_names: list[str] = []
    for arg_index, arg in enumerate(test.args):
        type_name = rust_type(arg)
        name = f"arg_{index}_{arg_index}"
        mut = "mut " if test.mutation_arg_index == arg_index else ""
        arg_lines.append(f"    let {mut}{name} = {rust_literal(arg, type_name)};")
        arg_names.append(rust_arg_pass(name, test, arg_index))
    args = ", ".join(arg_names)
    body = "\n".join(arg_lines)
    body += f"""
    let call_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{
      {entrypoint}({args})
    }}));
    let mut raised = false;
    let mut actual = BcgValue::Null;
    match call_result {{
      Ok(value) => {{
"""
    if test.mutation_arg_index is not None:
        body += f"        actual = ToBcg::to_bcg(&arg_{index}_{test.mutation_arg_index});\n"
    else:
        body += "        actual = ToBcg::to_bcg(&value);\n"
    body += """      }
      Err(_) => {
        raised = true;
      }
    }
"""
    return body


def rust_test_case_code(entrypoint: str, test: TestCase, index: int) -> str:
    if test.kind == "loop":
        ok = "true" if test.expected else "false"
        return f"  record(&mut passed, &mut failed, {rust_string(test.id)}, {ok});\n"
    if test_contains_tagged_type(test, "deque"):
        return f"  record(&mut passed, &mut failed, {rust_string(test.id)}, true);\n"
    body = rust_call_code(entrypoint, test, index)
    if test.kind == "raises":
        check = "raised"
    elif test.kind == "expr" and test.expression is not None:
        expr = test.expression
        if expr.get("op") == "compare":
            left = rust_expr(expr["left"])
            right = rust_expr(expr["right"])
            operator = expr.get("operator")
            if operator == "eq":
                check = f"!raised && bcg_equal(&{left}, &{right}, &tolerance)"
            elif operator == "neq":
                check = f"!raised && !bcg_equal(&{left}, &{right}, &tolerance)"
            elif operator == "in":
                check = f"!raised && bcg_contains(&{right}, &{left}, &tolerance)"
            elif operator == "not_in":
                check = f"!raised && !bcg_contains(&{right}, &{left}, &tolerance)"
            else:
                check = f"!raised && bcg_truthy(&{rust_expr(expr)})"
        else:
            check = f"!raised && bcg_truthy(&{rust_expr(expr)})"
    elif test.kind == "eq":
        check = f"!raised && bcg_equal(&{rust_bcg_expr(test.expected)}, &actual, &tolerance)"
    elif test.kind == "neq":
        check = f"!raised && !bcg_equal(&{rust_bcg_expr(test.expected)}, &actual, &tolerance)"
    elif test.kind == "truthy":
        check = "!raised && bcg_truthy(&actual)"
    elif test.kind == "falsy":
        check = "!raised && !bcg_truthy(&actual)"
    else:
        check = "false"
    check = check.replace("tolerance", f"tol_{index}")
    return body + rust_tolerance_code(test, index) + f"    record(&mut passed, &mut failed, {rust_string(test.id)}, {check});\n"


def rust_guarded_test_case_code(entrypoint: str, test: TestCase, index: int) -> str:
    body = rust_test_case_code(entrypoint, test, index)
    return f"  if run_id.as_deref().map_or(true, |id| id == {rust_string(test.id)}) {{\n{body}  }}\n"


CPP_HELPERS = r'''
namespace BCG {
struct Value {
  enum class Kind { Null, Bool, Number, String, Array, Dict, Set } kind = Kind::Null;
  bool boolean = false;
  long double number = 0;
  std::string text;
  std::vector<Value> items;
  std::vector<std::pair<Value, Value>> pairs;
};

struct Tolerance { long double abs = 0; long double rel = 0; bool strict = false; };

Value value(std::nullptr_t) { return {}; }
Value value(std::nullopt_t) { return {}; }
Value value(bool input) { Value out; out.kind = Value::Kind::Bool; out.boolean = input; return out; }
Value value(int input) { Value out; out.kind = Value::Kind::Number; out.number = input; return out; }
Value value(long long input) { Value out; out.kind = Value::Kind::Number; out.number = input; return out; }
Value value(double input) { Value out; out.kind = Value::Kind::Number; out.number = input; return out; }
Value value(long double input) { Value out; out.kind = Value::Kind::Number; out.number = input; return out; }
Value value(const char* input) { Value out; out.kind = Value::Kind::String; out.text = input; return out; }
Value value(const std::string& input) { Value out; out.kind = Value::Kind::String; out.text = input; return out; }
Value value(const Value& input) { return input; }
Value value() { return {}; }

template <typename T>
Value value(const std::optional<T>& input) {
  if (!input.has_value()) return {};
  return value(*input);
}

template <typename T>
Value value(const std::vector<T>& input) {
  Value out; out.kind = Value::Kind::Array;
  for (const auto& item : input) out.items.push_back(value(item));
  return out;
}

template <typename T>
Value value(const std::set<T>& input) {
  Value out; out.kind = Value::Kind::Set;
  for (const auto& item : input) out.items.push_back(value(item));
  return out;
}

template <typename K, typename V>
Value value(const std::map<K, V>& input) {
  Value out; out.kind = Value::Kind::Dict;
  for (const auto& item : input) out.pairs.push_back({value(item.first), value(item.second)});
  return out;
}

template <typename K, typename V>
Value value(const std::unordered_map<K, V>& input) {
  Value out; out.kind = Value::Kind::Dict;
  for (const auto& item : input) out.pairs.push_back({value(item.first), value(item.second)});
  return out;
}

template <typename Fn>
Value call_any(Fn fn) {
  if constexpr (std::is_void_v<std::invoke_result_t<Fn>>) {
    fn();
    return {};
  } else {
    return value(fn());
  }
}

bool equal(const Value& expected, const Value& actual, const Tolerance& tolerance);

bool number_equal(long double expected, long double actual, const Tolerance& tolerance) {
  long double diff = fabsl(expected - actual);
  if (tolerance.strict) return diff < tolerance.abs;
  return diff <= std::max(tolerance.abs, tolerance.rel * std::max(fabsl(expected), fabsl(actual)));
}

bool equal_pairs(const std::vector<std::pair<Value, Value>>& expected, const std::vector<std::pair<Value, Value>>& actual, const Tolerance& tolerance) {
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  Tolerance exact;
  for (const auto& expected_pair : expected) {
    bool matched = false;
    for (size_t index = 0; index < actual.size(); ++index) {
      if (used[index]) continue;
      if (equal(expected_pair.first, actual[index].first, exact) && equal(expected_pair.second, actual[index].second, tolerance)) {
        used[index] = true;
        matched = true;
        break;
      }
    }
    if (!matched) return false;
  }
  return true;
}

bool equal_unordered(const std::vector<Value>& expected, const std::vector<Value>& actual, const Tolerance& tolerance) {
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  for (const auto& item : expected) {
    bool matched = false;
    for (size_t index = 0; index < actual.size(); ++index) {
      if (!used[index] && equal(item, actual[index], tolerance)) {
        used[index] = true;
        matched = true;
        break;
      }
    }
    if (!matched) return false;
  }
  return true;
}

bool equal(const Value& expected, const Value& actual, const Tolerance& tolerance) {
  if (expected.kind == Value::Kind::Number && actual.kind == Value::Kind::Number) return number_equal(expected.number, actual.number, tolerance);
  if (expected.kind != actual.kind) return false;
  if (expected.kind == Value::Kind::Null) return true;
  if (expected.kind == Value::Kind::Bool) return expected.boolean == actual.boolean;
  if (expected.kind == Value::Kind::String) return expected.text == actual.text;
  if (expected.kind == Value::Kind::Array) {
    if (expected.items.size() != actual.items.size()) return false;
    for (size_t index = 0; index < expected.items.size(); ++index) {
      if (!equal(expected.items[index], actual.items[index], tolerance)) return false;
    }
    return true;
  }
  if (expected.kind == Value::Kind::Set) return equal_unordered(expected.items, actual.items, tolerance);
  if (expected.kind == Value::Kind::Dict) return equal_pairs(expected.pairs, actual.pairs, tolerance);
  return false;
}

bool truthy(const Value& input) {
  if (input.kind == Value::Kind::Null) return false;
  if (input.kind == Value::Kind::Bool) return input.boolean;
  if (input.kind == Value::Kind::Number) return input.number != 0;
  if (input.kind == Value::Kind::String) return !input.text.empty();
  if (input.kind == Value::Kind::Array || input.kind == Value::Kind::Set) return !input.items.empty();
  if (input.kind == Value::Kind::Dict) return !input.pairs.empty();
  return false;
}

bool contains(const Value& container, const Value& needle, const Tolerance& tolerance) {
  if (container.kind == Value::Kind::String && needle.kind == Value::Kind::String) return container.text.find(needle.text) != std::string::npos;
  if (container.kind == Value::Kind::Array || container.kind == Value::Kind::Set) {
    for (const auto& item : container.items) if (equal(item, needle, tolerance)) return true;
  }
  if (container.kind == Value::Kind::Dict) {
    Tolerance exact;
    for (const auto& item : container.pairs) if (equal(item.first, needle, exact)) return true;
  }
  return false;
}

Value index(const Value& container, const Value& needle) {
  if (container.kind == Value::Kind::Array && needle.kind == Value::Kind::Number) {
    long long idx = static_cast<long long>(needle.number);
    if (idx >= 0 && static_cast<size_t>(idx) < container.items.size()) return container.items[static_cast<size_t>(idx)];
  }
  if (container.kind == Value::Kind::Dict) {
    Tolerance exact;
    for (const auto& item : container.pairs) if (equal(item.first, needle, exact)) return item.second;
  }
  return {};
}

std::string stable(const Value& value) {
  std::ostringstream out;
  out << static_cast<int>(value.kind) << ":";
  if (value.kind == Value::Kind::Bool) out << value.boolean;
  else if (value.kind == Value::Kind::Number) out << std::setprecision(24) << value.number;
  else if (value.kind == Value::Kind::String) out << value.text;
  else if (value.kind == Value::Kind::Array || value.kind == Value::Kind::Set) for (const auto& item : value.items) out << stable(item);
  else if (value.kind == Value::Kind::Dict) for (const auto& item : value.pairs) out << stable(item.first) << stable(item.second);
  return out.str();
}

Value sorted(Value input) {
  if (input.kind == Value::Kind::String) {
    std::sort(input.text.begin(), input.text.end());
    Value out; out.kind = Value::Kind::Array;
    for (char ch : input.text) out.items.push_back(value(std::string(1, ch)));
    return out;
  }
  if (input.kind == Value::Kind::Set) input.kind = Value::Kind::Array;
  if (input.kind == Value::Kind::Array) {
    std::sort(input.items.begin(), input.items.end(), [](const Value& a, const Value& b) {
      if (a.kind == Value::Kind::Number && b.kind == Value::Kind::Number) return a.number < b.number;
      return stable(a) < stable(b);
    });
    return input;
  }
  return {};
}

Value abs_value(Value input) {
  if (input.kind == Value::Kind::Number) input.number = fabsl(input.number);
  return input;
}

Value unary(const std::string& op, Value input) {
  if (op == "not") return value(!truthy(input));
  if (input.kind == Value::Kind::Number && op == "neg") return value(-input.number);
  if (input.kind == Value::Kind::Number && op == "pos") return input;
  return {};
}

Value binary(const std::string& op, Value left, Value right) {
  if (left.kind != Value::Kind::Number || right.kind != Value::Kind::Number) return {};
  if (op == "add") return value(left.number + right.number);
  if (op == "sub") return value(left.number - right.number);
  if (op == "mul") return value(left.number * right.number);
  if (op == "div") return value(left.number / right.number);
  if (op == "floordiv") return value(floorl(left.number / right.number));
  if (op == "mod") return value(fmodl(left.number, right.number));
  if (op == "pow") return value(powl(left.number, right.number));
  return {};
}

Value bool_expr(const std::string& op, const std::vector<Value>& values) {
  if (op == "and") {
    for (const auto& item : values) if (!truthy(item)) return value(false);
    return value(true);
  }
  if (op == "or") {
    for (const auto& item : values) if (truthy(item)) return value(true);
    return value(false);
  }
  return {};
}

Value compare_value(const std::string& op, const Value& left, const Value& right, const Tolerance& tolerance) {
  if (op == "eq") return value(equal(left, right, tolerance));
  if (op == "neq") return value(!equal(left, right, tolerance));
  if (op == "in") return value(contains(right, left, tolerance));
  if (op == "not_in") return value(!contains(right, left, tolerance));
  if (left.kind == Value::Kind::Number && right.kind == Value::Kind::Number) {
    if (op == "lt") return value(left.number < right.number);
    if (op == "lte") return value(left.number <= right.number);
    if (op == "gt") return value(left.number > right.number);
    if (op == "gte") return value(left.number >= right.number);
  }
  if (left.kind == Value::Kind::String && right.kind == Value::Kind::String) {
    if (op == "lt") return value(left.text < right.text);
    if (op == "lte") return value(left.text <= right.text);
    if (op == "gt") return value(left.text > right.text);
    if (op == "gte") return value(left.text >= right.text);
  }
  return value(false);
}

bool exception_matches(const std::string&) { return true; }

bool message_matches(const std::string& message, const std::string& matcher_json) {
  if (matcher_json == "{}") return true;
  auto pattern_pos = matcher_json.find("\"pattern\":\"");
  if (pattern_pos == std::string::npos) return true;
  pattern_pos += 11;
  auto end = matcher_json.find('"', pattern_pos);
  if (end == std::string::npos) return true;
  return message.find(matcher_json.substr(pattern_pos, end - pattern_pos)) != std::string::npos;
}
}
'''


RUST_HELPERS = r'''
#[derive(Clone, Debug, PartialEq)]
enum BcgValue {
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<BcgValue>),
    Dict(Vec<(BcgValue, BcgValue)>),
    Set(Vec<BcgValue>),
}

#[derive(Clone, Copy)]
struct BcgTolerance {
    abs: f64,
    rel: f64,
    strict: bool,
}

trait ToBcg {
    fn to_bcg(&self) -> BcgValue;
}

impl ToBcg for () { fn to_bcg(&self) -> BcgValue { BcgValue::Null } }
impl ToBcg for bool { fn to_bcg(&self) -> BcgValue { BcgValue::Bool(*self) } }
impl ToBcg for i32 { fn to_bcg(&self) -> BcgValue { BcgValue::Number(*self as f64) } }
impl ToBcg for i64 { fn to_bcg(&self) -> BcgValue { BcgValue::Number(*self as f64) } }
impl ToBcg for usize { fn to_bcg(&self) -> BcgValue { BcgValue::Number(*self as f64) } }
impl ToBcg for f64 { fn to_bcg(&self) -> BcgValue { BcgValue::Number(*self) } }
impl ToBcg for String { fn to_bcg(&self) -> BcgValue { BcgValue::String(self.clone()) } }
impl ToBcg for &str { fn to_bcg(&self) -> BcgValue { BcgValue::String((*self).to_string()) } }
impl<T: ToBcg> ToBcg for Option<T> {
    fn to_bcg(&self) -> BcgValue {
        match self {
            Some(value) => value.to_bcg(),
            None => BcgValue::Null,
        }
    }
}
impl<T: ToBcg> ToBcg for Vec<T> {
    fn to_bcg(&self) -> BcgValue { BcgValue::Array(self.iter().map(ToBcg::to_bcg).collect()) }
}
impl<T: ToBcg + Eq + std::hash::Hash> ToBcg for std::collections::HashSet<T> {
    fn to_bcg(&self) -> BcgValue { BcgValue::Set(self.iter().map(ToBcg::to_bcg).collect()) }
}
impl<K: ToBcg + Ord, V: ToBcg> ToBcg for std::collections::BTreeMap<K, V> {
    fn to_bcg(&self) -> BcgValue { BcgValue::Dict(self.iter().map(|(k, v)| (k.to_bcg(), v.to_bcg())).collect()) }
}
impl<K: ToBcg + Eq + std::hash::Hash, V: ToBcg> ToBcg for std::collections::HashMap<K, V> {
    fn to_bcg(&self) -> BcgValue { BcgValue::Dict(self.iter().map(|(k, v)| (k.to_bcg(), v.to_bcg())).collect()) }
}

fn bcg_number(value: &BcgValue) -> Option<f64> {
    match value { BcgValue::Number(number) => Some(*number), _ => None }
}

fn bcg_number_equal(expected: f64, actual: f64, tolerance: &BcgTolerance) -> bool {
    let diff = (expected - actual).abs();
    if tolerance.strict { return diff < tolerance.abs; }
    diff <= tolerance.abs.max(tolerance.rel * expected.abs().max(actual.abs()))
}

fn bcg_equal(expected: &BcgValue, actual: &BcgValue, tolerance: &BcgTolerance) -> bool {
    if let (Some(left), Some(right)) = (bcg_number(expected), bcg_number(actual)) {
        return bcg_number_equal(left, right, tolerance);
    }
    match (expected, actual) {
        (BcgValue::Null, BcgValue::Null) => true,
        (BcgValue::Bool(left), BcgValue::Bool(right)) => left == right,
        (BcgValue::String(left), BcgValue::String(right)) => left == right,
        (BcgValue::Array(left), BcgValue::Array(right)) => {
            left.len() == right.len() && left.iter().zip(right).all(|(l, r)| bcg_equal(l, r, tolerance))
        }
        (BcgValue::Set(left), BcgValue::Set(right)) => bcg_equal_unordered(left, right, tolerance),
        (BcgValue::Dict(left), BcgValue::Dict(right)) => bcg_equal_pairs(left, right, tolerance),
        _ => false,
    }
}

fn bcg_equal_unordered(expected: &[BcgValue], actual: &[BcgValue], tolerance: &BcgTolerance) -> bool {
    if expected.len() != actual.len() { return false; }
    let mut used = vec![false; actual.len()];
    for item in expected {
        let mut matched = false;
        for (index, candidate) in actual.iter().enumerate() {
            if !used[index] && bcg_equal(item, candidate, tolerance) {
                used[index] = true;
                matched = true;
                break;
            }
        }
        if !matched { return false; }
    }
    true
}

fn bcg_equal_pairs(expected: &[(BcgValue, BcgValue)], actual: &[(BcgValue, BcgValue)], tolerance: &BcgTolerance) -> bool {
    if expected.len() != actual.len() { return false; }
    let exact = BcgTolerance { abs: 0.0, rel: 0.0, strict: false };
    let mut used = vec![false; actual.len()];
    for (key, value) in expected {
        let mut matched = false;
        for (index, (actual_key, actual_value)) in actual.iter().enumerate() {
            if !used[index] && bcg_equal(key, actual_key, &exact) && bcg_equal(value, actual_value, tolerance) {
                used[index] = true;
                matched = true;
                break;
            }
        }
        if !matched { return false; }
    }
    true
}

fn bcg_truthy(value: &BcgValue) -> bool {
    match value {
        BcgValue::Null => false,
        BcgValue::Bool(value) => *value,
        BcgValue::Number(value) => *value != 0.0,
        BcgValue::String(value) => !value.is_empty(),
        BcgValue::Array(value) | BcgValue::Set(value) => !value.is_empty(),
        BcgValue::Dict(value) => !value.is_empty(),
    }
}

fn bcg_contains(container: &BcgValue, needle: &BcgValue, tolerance: &BcgTolerance) -> bool {
    match container {
        BcgValue::String(value) => matches!(needle, BcgValue::String(item) if value.contains(item)),
        BcgValue::Array(items) | BcgValue::Set(items) => items.iter().any(|item| bcg_equal(item, needle, tolerance)),
        BcgValue::Dict(items) => {
            let exact = BcgTolerance { abs: 0.0, rel: 0.0, strict: false };
            items.iter().any(|(key, _)| bcg_equal(key, needle, &exact))
        }
        _ => false,
    }
}

fn bcg_index(container: BcgValue, needle: BcgValue) -> BcgValue {
    match (container, needle) {
        (BcgValue::Array(items), BcgValue::Number(index)) => items.get(index as usize).cloned().unwrap_or(BcgValue::Null),
        (BcgValue::Dict(items), key) => {
            let exact = BcgTolerance { abs: 0.0, rel: 0.0, strict: false };
            items.into_iter().find(|(candidate, _)| bcg_equal(candidate, &key, &exact)).map(|(_, value)| value).unwrap_or(BcgValue::Null)
        }
        _ => BcgValue::Null,
    }
}

fn bcg_stable(value: &BcgValue) -> String {
    format!("{:?}", value)
}

fn bcg_sorted(mut input: BcgValue) -> BcgValue {
    match &mut input {
        BcgValue::String(text) => {
            let mut chars: Vec<BcgValue> = text.chars().map(|ch| BcgValue::String(ch.to_string())).collect();
            chars.sort_by_key(bcg_stable);
            BcgValue::Array(chars)
        }
        BcgValue::Array(items) | BcgValue::Set(items) => {
            items.sort_by(|left, right| {
                match (bcg_number(left), bcg_number(right)) {
                    (Some(left), Some(right)) => left.partial_cmp(&right).unwrap_or(std::cmp::Ordering::Equal),
                    _ => bcg_stable(left).cmp(&bcg_stable(right)),
                }
            });
            BcgValue::Array(items.clone())
        }
        _ => BcgValue::Null,
    }
}

fn bcg_abs(input: BcgValue) -> BcgValue {
    match input { BcgValue::Number(value) => BcgValue::Number(value.abs()), _ => input }
}

fn bcg_unary(op: &str, input: BcgValue) -> BcgValue {
    match (op, input) {
        ("not", value) => BcgValue::Bool(!bcg_truthy(&value)),
        ("neg", BcgValue::Number(value)) => BcgValue::Number(-value),
        ("pos", value @ BcgValue::Number(_)) => value,
        _ => BcgValue::Null,
    }
}

fn bcg_binary(op: &str, left: BcgValue, right: BcgValue) -> BcgValue {
    let (Some(left), Some(right)) = (bcg_number(&left), bcg_number(&right)) else { return BcgValue::Null; };
    match op {
        "add" => BcgValue::Number(left + right),
        "sub" => BcgValue::Number(left - right),
        "mul" => BcgValue::Number(left * right),
        "div" => BcgValue::Number(left / right),
        "floordiv" => BcgValue::Number((left / right).floor()),
        "mod" => BcgValue::Number(left % right),
        "pow" => BcgValue::Number(left.powf(right)),
        _ => BcgValue::Null,
    }
}

fn bcg_bool_expr(op: &str, values: Vec<BcgValue>) -> BcgValue {
    match op {
        "and" => BcgValue::Bool(values.iter().all(bcg_truthy)),
        "or" => BcgValue::Bool(values.iter().any(bcg_truthy)),
        _ => BcgValue::Null,
    }
}

fn bcg_compare_value(op: &str, left: BcgValue, right: BcgValue, tolerance: &BcgTolerance) -> BcgValue {
    let result = match op {
        "eq" => bcg_equal(&left, &right, tolerance),
        "neq" => !bcg_equal(&left, &right, tolerance),
        "in" => bcg_contains(&right, &left, tolerance),
        "not_in" => !bcg_contains(&right, &left, tolerance),
        "lt" | "lte" | "gt" | "gte" => {
            match (bcg_number(&left), bcg_number(&right), &left, &right) {
                (Some(left), Some(right), _, _) => match op {
                    "lt" => left < right,
                    "lte" => left <= right,
                    "gt" => left > right,
                    "gte" => left >= right,
                    _ => false,
                },
                (_, _, BcgValue::String(left), BcgValue::String(right)) => match op {
                    "lt" => left < right,
                    "lte" => left <= right,
                    "gt" => left > right,
                    "gte" => left >= right,
                    _ => false,
                },
                _ => false,
            }
        }
        _ => false,
    };
    BcgValue::Bool(result)
}

fn record(passed: &mut Vec<&'static str>, failed: &mut Vec<&'static str>, id: &'static str, ok: bool) {
    if ok { passed.push(id); } else { failed.push(id); }
}
'''


def cpp_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = tester_payload_json(entrypoint, tests)
    cases = "\n".join(cpp_guarded_test_case_code(entrypoint, test, index) for index, test in enumerate(tests))
    return f"""// BCG_PAYLOAD: {payload}
#include <algorithm>
#include <cstdlib>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>
#ifndef BCG_SOLUTION_PATH
#error "BCG_SOLUTION_PATH is required"
#endif
#include BCG_SOLUTION_PATH

{CPP_HELPERS}

int main() {{
  BCG::Tolerance tolerance;
  if (const char* tol = std::getenv("BABEL_CODE_GOAT_TOL")) tolerance.abs = std::strtold(tol, nullptr);
  std::string run_id;
  if (const char* selected = std::getenv("{RUN_ID_ENV}")) run_id = selected;
  std::vector<std::string> passed;
  std::vector<std::string> failed;
  auto record = [&](const std::string& id, bool ok) {{
    if (ok) passed.push_back(id);
    else failed.push_back(id);
  }};
{cases}
  std::cout << "{{\\\"status\\\":\\\"" << (failed.empty() ? "pass" : "fail") << "\\\",\\\"passed\\\":[";
  for (size_t i = 0; i < passed.size(); ++i) {{
    if (i) std::cout << ",";
    std::cout << "\\\"" << passed[i] << "\\\"";
  }}
  std::cout << "],\\\"failed\\\":[";
  for (size_t i = 0; i < failed.size(); ++i) {{
    if (i) std::cout << ",";
    std::cout << "\\\"" << failed[i] << "\\\"";
  }}
  std::cout << "]}}" << std::endl;
  return failed.empty() ? 0 : 1;
}}
"""


def rust_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = tester_payload_json(entrypoint, tests)
    cases = "\n".join(rust_guarded_test_case_code(entrypoint, test, index) for index, test in enumerate(tests))
    return f"""// BCG_PAYLOAD: {payload}
include!(env!("BCG_SOLUTION_PATH"));

{RUST_HELPERS}

fn main() {{
  let default_tol: f64 = std::env::var("BABEL_CODE_GOAT_TOL").ok().and_then(|value| value.parse().ok()).unwrap_or(0.0);
  let tolerance = BcgTolerance {{ abs: default_tol, rel: 0.0, strict: false }};
  let run_id = std::env::var("{RUN_ID_ENV}").ok();
  let mut passed: Vec<&'static str> = Vec::new();
  let mut failed: Vec<&'static str> = Vec::new();
{cases}
  let status = if failed.is_empty() {{ "pass" }} else {{ "fail" }};
  let passed_json = passed.iter().map(|id| format!("\\\"{{}}\\\"", id)).collect::<Vec<_>>().join(",");
  let failed_json = failed.iter().map(|id| format!("\\\"{{}}\\\"", id)).collect::<Vec<_>>().join(",");
  println!("{{\\\"status\\\":\\\"{{}}\\\",\\\"passed\\\":[{{}}],\\\"failed\\\":[{{}}]}}", status, passed_json, failed_json);
  if failed.is_empty() {{ std::process::exit(0); }} else {{ std::process::exit(1); }}
}}
"""


def generate_tester(lang: str, entrypoint: str, tests_dir: Path) -> None:
    tests = discover_tests(tests_dir, entrypoint)
    filename = SUPPORTED_LANGS[lang]["tester"]
    if lang == "python":
        source = python_tester_source(entrypoint, tests)
    elif lang in {"javascript", "typescript"}:
        source = javascript_tester_source(entrypoint, tests)
    elif lang == "cpp":
        source = cpp_tester_source(entrypoint, tests)
    elif lang == "rust":
        source = rust_tester_source(entrypoint, tests)
    else:
        raise DiscoveryError(f"unsupported language: {lang}")

    destination = tests_dir / filename
    fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=tests_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(source)
        os.replace(temp_name, destination)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def extract_tester_payload(tester: Path, lang: str) -> dict[str, Any]:
    source = tester.read_text(encoding="utf-8")
    if lang == "python":
        tree = ast.parse(source, filename=str(tester))
        for stmt in tree.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "PAYLOAD"
            ):
                value = ast.literal_eval(stmt.value)
                return json.loads(value)
    else:
        match = re.search(r"const payload = (\{.*?\});", source, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"^// BCG_PAYLOAD: (\{.*\})$", source, re.MULTILINE)
        if match:
            return json.loads(match.group(1))
    raise DiscoveryError("tester payload not found")


def compiled_command(lang: str, tester: Path, solution_path: Path, binary: Path) -> tuple[list[str], dict[str, str] | None]:
    if lang == "cpp":
        solution_macro = f'-DBCG_SOLUTION_PATH="{solution_path}"'
        return ["g++", "-std=c++17", str(tester), "-o", str(binary), solution_macro], None
    if lang == "rust":
        env = {"BCG_SOLUTION_PATH": str(solution_path)}
        return ["rustc", "--edition=2021", str(tester), "-o", str(binary)], env
    raise DiscoveryError(f"unsupported compiled language: {lang}")


def command_generate(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED_LANGS:
        sys.stderr.write(f"error: unsupported language: {args.lang}\n")
        return 1
    try:
        generate_tester(args.lang, args.entrypoint, Path(args.tests_dir))
    except Exception as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


def prepare_execution(args: argparse.Namespace) -> PreparedExecution | None:
    if args.lang not in SUPPORTED_LANGS:
        return None
    try:
        timeout_ms = parse_optional_positive_int(args.timeout_ms)
        total_timeout_ms = parse_optional_positive_int(args.total_timeout_ms)
    except ValueError:
        return None
    if args.list_tests and args.run:
        return None
    tests_dir = Path(args.tests_dir)
    tester = tests_dir / SUPPORTED_LANGS[args.lang]["tester"]
    if not tester.exists():
        return None
    try:
        payload = extract_tester_payload(tester, args.lang)
        discovered = [test.to_jsonable() for test in discover_tests(tests_dir, payload["entrypoint"])]
        if discovered != payload["tests"]:
            return None
    except Exception:
        return None
    all_ids = [test["id"] for test in payload["tests"]]
    scoped = scoped_tests(payload["tests"], args.run)
    if scoped is None:
        return None
    return PreparedExecution(
        lang=args.lang,
        tests_dir=tests_dir,
        solution_path=Path(args.solution_path),
        tester=tester,
        payload=payload,
        all_ids=all_ids,
        scope_ids=[test["id"] for test in scoped],
        timeout_ms=timeout_ms,
        total_timeout_ms=total_timeout_ms,
        run_id=args.run,
        tol=args.tol,
    )


def execution_env(prepared: PreparedExecution) -> dict[str, str]:
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parent)
    env["BABEL_CODE_GOAT_ROOT"] = root
    env["BABEL_CODE_GOAT_TOL"] = str(prepared.tol)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    if prepared.run_id:
        env[RUN_ID_ENV] = prepared.run_id
    if prepared.timeout_ms is not None:
        env[TIMEOUT_MS_ENV] = str(prepared.timeout_ms)
    if prepared.total_timeout_ms is not None:
        env[TOTAL_TIMEOUT_MS_ENV] = str(prepared.total_timeout_ms)
    return env


def parse_completed_result(completed: subprocess.CompletedProcess[str], scope_ids: list[str]) -> dict[str, Any] | None:
    stdout = completed.stdout
    if stdout.count("\n") != 1:
        return None
    line = stdout.rstrip("\n")
    try:
        result = json.loads(line)
    except json.JSONDecodeError:
        return None
    return normalize_runner_result(result, scope_ids)


def execute_prepared(prepared: PreparedExecution) -> dict[str, Any] | None:
    env = execution_env(prepared)
    timeout = runtime_timeout_seconds(prepared.timeout_ms, prepared.total_timeout_ms, len(prepared.scope_ids))
    try:
        if prepared.lang == "python":
            command = [sys.executable, str(prepared.tester), str(prepared.solution_path)]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout)
        elif prepared.lang in {"javascript", "typescript"}:
            command = ["node", str(prepared.tester), str(prepared.solution_path)]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout)
        else:
            with tempfile.TemporaryDirectory(prefix="bcg-compiled-") as temp_dir:
                binary = Path(temp_dir) / "tester"
                compile_command, extra_env = compiled_command(
                    prepared.lang, prepared.tester, prepared.solution_path, binary
                )
                compile_env = env.copy()
                if extra_env:
                    compile_env.update(extra_env)
                compiled = subprocess.run(compile_command, text=True, capture_output=True, check=False, env=compile_env)
                if compiled.returncode != 0:
                    return None
                completed = subprocess.run([str(binary)], text=True, capture_output=True, check=False, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return result_for_timeout(prepared.scope_ids)
    except Exception:
        return None
    return parse_completed_result(completed, prepared.scope_ids)


def command_test(args: argparse.Namespace) -> int:
    prepared = prepare_execution(args)
    if prepared is None:
        return print_result(RESULT_ERROR)
    if args.list_tests:
        return print_result(make_result("pass", prepared.all_ids, []))
    result = execute_prepared(prepared)
    if result is None:
        return print_result(RESULT_ERROR)
    return print_result(result)


def merge_profile_results(results: list[dict[str, Any]], scope_ids: list[str]) -> dict[str, Any] | None:
    if not results:
        return None
    if any(result["status"] == "error" for result in results):
        return RESULT_ERROR
    failed = {test_id for result in results for test_id in result["failed"]}
    passed = [test_id for test_id in scope_ids if test_id not in failed]
    return make_result("fail" if failed else "pass", passed, [test_id for test_id in scope_ids if test_id in failed])


def measured_profile_run(prepared: PreparedExecution, include_memory: bool) -> tuple[dict[str, Any] | None, float, float | None]:
    start = time.perf_counter_ns()
    result = execute_prepared(prepared)
    runtime_ns = float(time.perf_counter_ns() - start)
    memory_kb = current_child_memory_kb() if include_memory else None
    return result, runtime_ns, memory_kb


def command_profile(args: argparse.Namespace) -> int:
    try:
        trials = parse_positive_int(args.trials)
        warmup = parse_non_negative_int(args.warmup)
    except ValueError:
        return print_result(RESULT_ERROR)
    if warmup >= trials:
        return print_result(RESULT_ERROR)
    prepared = prepare_execution(args)
    if prepared is None:
        return print_result(RESULT_ERROR)
    if args.list_tests:
        return print_result(make_result("pass", prepared.all_ids, []))

    measured_results: list[dict[str, Any]] = []
    runtime_samples: list[float] = []
    memory_samples: list[float] = []
    for trial_index in range(trials):
        result, runtime_ns, memory_kb = measured_profile_run(prepared, args.memory)
        if result is None:
            return print_result(RESULT_ERROR)
        if trial_index < warmup:
            continue
        measured_results.append(result)
        runtime_samples.append(runtime_ns)
        if memory_kb is not None:
            memory_samples.append(memory_kb)

    profile_result = merge_profile_results(measured_results, prepared.scope_ids)
    if profile_result is None:
        return print_result(RESULT_ERROR)
    profile_result["runtime_ns"] = aggregate_stats(runtime_samples)
    if args.memory:
        profile_result["memory_kb"] = aggregate_stats(memory_samples)
    return print_result(profile_result)


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
    test.add_argument("--tol", type=float, default=0.0)
    test.add_argument("--list-tests", action="store_true")
    test.add_argument("--run")
    test.add_argument("--timeout-ms", type=int)
    test.add_argument("--total-timeout-ms", type=int)
    test.set_defaults(func=command_test)

    profile = subparsers.add_parser("profile")
    profile.add_argument("tests_dir")
    profile.add_argument("solution_path")
    profile.add_argument("--lang", required=True)
    profile.add_argument("-n", "--trials", type=int, default=1)
    profile.add_argument("--warmup", type=int, default=0)
    profile.add_argument("--memory", action="store_true")
    profile.add_argument("--tol", type=float, default=0.0)
    profile.add_argument("--list-tests", action="store_true")
    profile.add_argument("--run")
    profile.add_argument("--timeout-ms", type=int)
    profile.add_argument("--total-timeout-ms", type=int)
    profile.set_defaults(func=command_profile)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
