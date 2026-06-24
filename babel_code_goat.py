#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import asyncio
from collections import Counter, defaultdict, deque
import contextlib
from decimal import Decimal, InvalidOperation
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import shutil
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
    "cpp": {"tester": "tester.cpp", "runner": "compiled"},
    "rust": {"tester": "tester.rs", "runner": "compiled"},
}
RESULT_ERROR = {"status": "error", "passed": [], "failed": []}
EXPECT_RE = re.compile(r"^\s*#\s*expect_(stdout|stderr):\s*(.+?)\s*$")
TAG_KEY = "__bcg_type__"


class DiscoveryError(Exception):
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
    mutation: dict[str, Any] | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    in_loop: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "line": self.line,
            "kind": self.kind,
            "args": self.args,
            "source_path": self.source_path,
            "expected": self.expected,
            "tolerance": self.tolerance,
            "expected_exception": self.expected_exception,
            "message_match": self.message_match,
            "expression": self.expression,
            "mutation": self.mutation,
            "expect_stdout": self.expect_stdout,
            "expect_stderr": self.expect_stderr,
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


def expression_from_node(node: ast.AST, entrypoint: str, context: DiscoveryContext) -> ExpressionBuild:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint:
        return ExpressionBuild({"op": "actual"}, parse_entrypoint_call(node, entrypoint, context), 1)

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = expression_from_node(node.args[0], entrypoint, context)
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
        operand = expression_from_node(node.operand, entrypoint, context)
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
        left = expression_from_node(node.left, entrypoint, context)
        right = expression_from_node(node.right, entrypoint, context)
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
        values = [expression_from_node(value, entrypoint, context) for value in node.values]
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
        left = expression_from_node(node.left, entrypoint, context)
        right = expression_from_node(node.comparators[0], entrypoint, context)
        args, call_count = merge_expression_args([left, right])
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression},
            args,
            call_count,
        )

    if isinstance(node, ast.Subscript):
        if entrypoint_call_count(node, entrypoint) == 0:
            return const_expression(node, context)
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = expression_from_node(node.value, entrypoint, context)
        index = expression_from_node(node.slice, entrypoint, context)
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


def parse_assert(
    node: ast.Assert, entrypoint: str, lines: list[str], context: DiscoveryContext, source_path: str
) -> TestCase:
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
        source_path=source_path,
        expected=expected,
        tolerance=tolerance,
        expression=expression,
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


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


def parse_raise_any(
    node: ast.Try, entrypoint: str, lines: list[str], context: DiscoveryContext, source_path: str
) -> TestCase:
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
        source_path=source_path,
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
    return TestCase(id="", line=node.lineno, kind="loop", args=[], source_path=source_path, expected=executed)


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


def direct_arg_bindings(call: ast.Call) -> dict[str, int]:
    bindings: dict[str, int] = {}
    arg_index = 0
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            continue
        if isinstance(arg, ast.Name):
            bindings[arg.id] = arg_index
        arg_index += 1
    return bindings


def mutation_start(stmt: ast.stmt, entrypoint: str, context: DiscoveryContext) -> dict[str, Any] | None:
    call: ast.Call
    assign_name = None
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
    elif isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name) or not isinstance(stmt.value, ast.Call):
            return None
        call = stmt.value
        assign_name = stmt.targets[0].id
    elif isinstance(stmt, ast.AnnAssign):
        if not isinstance(stmt.target, ast.Name) or not isinstance(stmt.value, ast.Call):
            return None
        call = stmt.value
        assign_name = stmt.target.id
    else:
        return None

    if not isinstance(call.func, ast.Name) or call.func.id != entrypoint:
        return None
    return {
        "args": parse_entrypoint_call(call, entrypoint, context),
        "assign": assign_name,
        "arg_bindings": direct_arg_bindings(call),
    }


def referenced_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def merge_runtime_names(parts: list[ExpressionBuild]) -> set[str]:
    names: set[str] = set()
    for part in parts:
        names.update(part.expression.get("names", []))
    return names


def mutation_const_or_name(node: ast.AST, context: DiscoveryContext, runtime_names: set[str]) -> ExpressionBuild:
    if isinstance(node, ast.Name) and node.id in runtime_names:
        return ExpressionBuild({"op": "name", "name": node.id, "names": [node.id]}, None, 0)
    return const_expression(node, context)


def mutation_expression_from_node(
    node: ast.AST, entrypoint: str, context: DiscoveryContext, runtime_names: set[str]
) -> ExpressionBuild:
    if entrypoint_call_count(node, entrypoint):
        raise DiscoveryError("mutation assertion must not call entrypoint")

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs", "len"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = mutation_expression_from_node(node.args[0], entrypoint, context, runtime_names)
            expression = {"op": "call", "function": callee, "args": [operand.expression]}
            expression["names"] = sorted(operand.expression.get("names", []))
            return ExpressionBuild(expression, None, 0)
        raise DiscoveryError("unsupported helper call")

    if isinstance(node, ast.Name):
        return mutation_const_or_name(node, context, runtime_names)

    if isinstance(node, ast.Constant):
        return const_expression(node, context)

    if isinstance(node, ast.List | ast.Tuple):
        items = [mutation_expression_from_node(item, entrypoint, context, runtime_names) for item in node.elts]
        names = sorted(merge_runtime_names(items))
        return ExpressionBuild({"op": "list", "items": [item.expression for item in items], "names": names}, None, 0)

    if isinstance(node, ast.Set):
        items = [mutation_expression_from_node(item, entrypoint, context, runtime_names) for item in node.elts]
        names = sorted(merge_runtime_names(items))
        return ExpressionBuild({"op": "set", "items": [item.expression for item in items], "names": names}, None, 0)

    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise DiscoveryError("dictionary unpacking is unsupported")
        keys = [mutation_expression_from_node(key, entrypoint, context, runtime_names) for key in node.keys]
        values = [mutation_expression_from_node(value, entrypoint, context, runtime_names) for value in node.values]
        names = sorted(merge_runtime_names([*keys, *values]))
        return ExpressionBuild(
            {
                "op": "dict",
                "items": [
                    [key.expression, value.expression]
                    for key, value in zip(keys, values, strict=True)
                ],
                "names": names,
            },
            None,
            0,
        )

    if isinstance(node, ast.UnaryOp):
        unary_ops = {
            ast.Not: "not",
            ast.USub: "neg",
            ast.UAdd: "pos",
        }
        operator = next((name for op_type, name in unary_ops.items() if isinstance(node.op, op_type)), None)
        if operator is None:
            raise DiscoveryError("unsupported unary expression")
        operand = mutation_expression_from_node(node.operand, entrypoint, context, runtime_names)
        expression = {"op": "unary", "operator": operator, "operand": operand.expression}
        expression["names"] = sorted(operand.expression.get("names", []))
        return ExpressionBuild(expression, None, 0)

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
        left = mutation_expression_from_node(node.left, entrypoint, context, runtime_names)
        right = mutation_expression_from_node(node.right, entrypoint, context, runtime_names)
        names = sorted(merge_runtime_names([left, right]))
        return ExpressionBuild(
            {"op": "binary", "operator": operator, "left": left.expression, "right": right.expression, "names": names},
            None,
            0,
        )

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            operator = "and"
        elif isinstance(node.op, ast.Or):
            operator = "or"
        else:
            raise DiscoveryError("unsupported boolean expression")
        values = [mutation_expression_from_node(value, entrypoint, context, runtime_names) for value in node.values]
        names = sorted(merge_runtime_names(values))
        return ExpressionBuild(
            {"op": "bool", "operator": operator, "values": [value.expression for value in values], "names": names},
            None,
            0,
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
        left = mutation_expression_from_node(node.left, entrypoint, context, runtime_names)
        right = mutation_expression_from_node(node.comparators[0], entrypoint, context, runtime_names)
        names = sorted(merge_runtime_names([left, right]))
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression, "names": names},
            None,
            0,
        )

    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = mutation_expression_from_node(node.value, entrypoint, context, runtime_names)
        index = mutation_expression_from_node(node.slice, entrypoint, context, runtime_names)
        names = sorted(merge_runtime_names([value, index]))
        return ExpressionBuild(
            {"op": "index", "value": value.expression, "index": index.expression, "names": names},
            None,
            0,
        )

    raise DiscoveryError("unsupported primitive expression")


def strip_expression_metadata(expression: dict[str, Any]) -> dict[str, Any]:
    stripped: dict[str, Any] = {}
    for key, value in expression.items():
        if key == "names":
            continue
        if isinstance(value, dict):
            stripped[key] = strip_expression_metadata(value)
        elif isinstance(value, list):
            stripped[key] = [
                strip_expression_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            stripped[key] = value
    return stripped


def parse_mutation_assert(
    node: ast.Assert,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source_path: str,
    setup: dict[str, Any],
) -> TestCase:
    runtime_names = set(setup["arg_bindings"])
    if setup["assign"] is not None:
        runtime_names.add(setup["assign"])
    expression = mutation_expression_from_node(node.test, entrypoint, context, runtime_names).expression
    names = set(expression.get("names", []))
    if not names.intersection(runtime_names):
        raise DiscoveryError("mutation assertion must reference mutation variable")
    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind="mutation",
        args=setup["args"],
        source_path=source_path,
        mutation={
            "assign": setup["assign"],
            "arg_bindings": setup["arg_bindings"],
            "assertion": strip_expression_metadata(expression),
        },
        expect_stdout=expect_stdout,
        expect_stderr=expect_stderr,
    )


def discover_in_body(
    body: list[ast.stmt],
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source_path: str,
    in_loop: bool = False,
) -> list[TestCase]:
    discovered: list[TestCase] = []
    index = 0
    while index < len(body):
        stmt = body[index]
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context.child(), source_path, in_loop))
            index += 1
        elif isinstance(stmt, ast.Assert):
            test_case = parse_assert(stmt, entrypoint, lines, context, source_path)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    source_path=test_case.source_path,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    mutation=test_case.mutation,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
            index += 1
        elif isinstance(stmt, ast.Try):
            test_case = parse_raise_any(stmt, entrypoint, lines, context, source_path)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    source_path=test_case.source_path,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    mutation=test_case.mutation,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
            index += 1
        elif isinstance(stmt, ast.For):
            discovered.extend(discover_for_loop(stmt, entrypoint, lines, context, source_path, in_loop))
            index += 1
        elif isinstance(stmt, ast.While):
            discovered.extend(discover_while_loop(stmt, entrypoint, lines, context, source_path, in_loop))
            index += 1
        elif (setup := mutation_start(stmt, entrypoint, context)) is not None:
            assertion_index = index + 1
            if assertion_index >= len(body) or not isinstance(body[assertion_index], ast.Assert):
                raise DiscoveryError("mutation call must be immediately followed by assertion")
            while assertion_index < len(body) and isinstance(body[assertion_index], ast.Assert):
                test_case = parse_mutation_assert(
                    body[assertion_index], entrypoint, lines, context, source_path, setup
                )
                discovered.append(
                    TestCase(
                        id=test_case.id,
                        line=test_case.line,
                        kind=test_case.kind,
                        args=test_case.args,
                        source_path=test_case.source_path,
                        mutation=test_case.mutation,
                        expect_stdout=test_case.expect_stdout,
                        expect_stderr=test_case.expect_stderr,
                        in_loop=in_loop,
                    )
                )
                assertion_index += 1
            index = assertion_index
        elif handle_assignment(stmt, context) or handle_aug_assignment(stmt, context):
            index += 1
            continue
        elif isinstance(stmt, ast.Pass):
            index += 1
            continue
        elif handle_import(stmt, context):
            index += 1
            continue
        else:
            raise DiscoveryError(f"unsupported code at line {getattr(stmt, 'lineno', '?')}")
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
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                source_path=test_case.source_path,
                expected=test_case.expected,
                tolerance=test_case.tolerance,
                expected_exception=test_case.expected_exception,
                message_match=test_case.message_match,
                expression=test_case.expression,
                mutation=test_case.mutation,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=test_case.in_loop,
            )
        )
    return assigned


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    tests_dir = Path(tests_dir)
    discovered: list[TestCase] = []
    generated_tester_files = {settings["tester"] for settings in SUPPORTED_LANGS.values()}
    files = sorted(
        (candidate for candidate in tests_dir.rglob("*") if candidate.is_file()),
        key=lambda item: item.relative_to(tests_dir).as_posix(),
    )
    for path in files:
        if path.name in generated_tester_files:
            continue
        relative_path = path.relative_to(tests_dir).as_posix()
        if path.suffix != ".py":
            stem = path.stem
            if stem.startswith("test") or stem.endswith("_test") or stem == "tests" or stem.endswith("_tests"):
                raise DiscoveryError("test-like non-Python file")
            continue
        discovered.extend(discover_tests_in_file(path, relative_path, entrypoint))
    if not discovered:
        raise DiscoveryError("no tests discovered")
    return assign_ids(discovered)


def discover_tests_in_file(tests_path: Path, source_path: str, entrypoint: str) -> list[TestCase]:
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
    return discover_in_body(tree.body, entrypoint, lines, context, source_path)


def make_result(status: str, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "passed": passed or [], "failed": failed or []}


def test_case_from_jsonable(value: dict[str, Any]) -> TestCase:
    return TestCase(
        id=value["id"],
        line=value["line"],
        kind=value["kind"],
        args=value["args"],
        source_path=value.get("source_path", "tests.py"),
        expected=value.get("expected"),
        tolerance=value.get("tolerance"),
        expected_exception=value.get("expected_exception"),
        message_match=value.get("message_match"),
        expression=value.get("expression"),
        mutation=value.get("mutation"),
        expect_stdout=value.get("expect_stdout"),
        expect_stderr=value.get("expect_stderr"),
    )


def print_result(result: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return {"pass": 0, "fail": 1, "error": 2}[result["status"]]


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


def evaluate_expression(
    expression: dict[str, Any], actual: Any, tolerance: dict[str, Any], env: dict[str, Any] | None = None
) -> Any:
    env = env or {}
    op = expression.get("op")
    if op == "const":
        return expression.get("value")
    if op == "actual":
        return actual
    if op == "name":
        return env[expression["name"]]
    if op == "list":
        return [evaluate_expression(item, actual, tolerance, env) for item in expression["items"]]
    if op == "set":
        return tagged(
            "set",
            items=sort_tagged_values(
                [normalize_comparable(evaluate_expression(item, actual, tolerance, env)) for item in expression["items"]]
            ),
        )
    if op == "dict":
        items = [
            [
                normalize_comparable(evaluate_expression(key, actual, tolerance, env)),
                normalize_comparable(evaluate_expression(value, actual, tolerance, env)),
            ]
            for key, value in expression["items"]
        ]
        items.sort(key=lambda pair: stable_json(pair[0]))
        return tagged("dict", items=items)
    if op == "unary":
        operand = evaluate_expression(expression["operand"], actual, tolerance, env)
        operator = expression.get("operator")
        if operator == "not":
            return not bool(operand)
        if operator == "neg":
            return -operand
        if operator == "pos":
            return +operand
    if op == "binary":
        left = evaluate_expression(expression["left"], actual, tolerance, env)
        right = evaluate_expression(expression["right"], actual, tolerance, env)
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
        values = [evaluate_expression(value, actual, tolerance, env) for value in expression["values"]]
        if expression.get("operator") == "and":
            return all(bool(value) for value in values)
        if expression.get("operator") == "or":
            return any(bool(value) for value in values)
    if op == "compare":
        left = evaluate_expression(expression["left"], actual, tolerance, env)
        right = evaluate_expression(expression["right"], actual, tolerance, env)
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
        value = evaluate_expression(expression["value"], actual, tolerance, env)
        index = evaluate_expression(expression["index"], actual, tolerance, env)
        return expression_index(value, index)
    if op == "call":
        args = [evaluate_expression(arg, actual, tolerance, env) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return expression_sorted(args[0])
        if expression.get("function") == "abs":
            return abs(args[0])
        if expression.get("function") == "len":
            return len(args[0])
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


def await_if_needed(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    return asyncio.run(value)


def execute_python_tests(
    solution_path: Path, entrypoint: str, tests: list[dict[str, Any]], default_tol: float = 0.0
) -> dict[str, Any]:
    callable_under_test = None
    if any(test["kind"] != "loop" for test in tests):
        try:
            callable_under_test = resolve_python_callable(solution_path, entrypoint)
        except Exception:
            return make_result("fail", [], [test["id"] for test in tests])

    passed: list[str] = []
    failed: list[str] = []
    for test in tests:
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        ok = False
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                if test["kind"] == "loop":
                    ok = bool(test.get("expected"))
                    actual = None
                    raised = False
                    raised_exc = None
                elif test["kind"] == "mutation":
                    raised = False
                    raised_exc = None
                    actual = None
                    decoded_args = [decode_arg(arg) for arg in test["args"]]
                    env = {
                        name: decoded_args[index]
                        for name, index in test["mutation"]["arg_bindings"].items()
                    }
                    try:
                        actual = await_if_needed(callable_under_test(*decoded_args))
                        if test["mutation"].get("assign") is not None:
                            env[test["mutation"]["assign"]] = actual
                    except Exception as exc:
                        raised = True
                        raised_exc = exc
                    if not raised:
                        ok = bool(
                            evaluate_expression(
                                test["mutation"]["assertion"], None, tolerance_policy(test, default_tol), env
                            )
                        )
                else:
                    raised = False
                    raised_exc = None
                    try:
                        actual = await_if_needed(callable_under_test(*[decode_arg(arg) for arg in test["args"]]))
                    except Exception as exc:
                        raised = True
                        raised_exc = exc
                        actual = None
                if test["kind"] == "loop":
                    pass
                elif test["kind"] == "mutation":
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

def main():
    if len(sys.argv) != 2:
        return print_result({{"status": "error", "passed": [], "failed": []}})
    data = json.loads(PAYLOAD)
    result = execute_python_tests(Path(sys.argv[1]), data["entrypoint"], data["tests"], float(os.environ.get("BABEL_CODE_GOAT_TOL", "0")))
    return print_result(result)

if __name__ == "__main__":
    raise SystemExit(main())
"""


def javascript_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    return f"""#!/usr/bin/env node
const path = require("path");
const {{ pathToFileURL }} = require("url");
const payload = {payload};
const TAG = "{TAG_KEY}";
const defaultTol = Number(process.env.BABEL_CODE_GOAT_TOL || "0");

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

function evaluateExpression(expression, actual, tolerance, env = {{}}) {{
  if (expression.op === "const") return expression.value;
  if (expression.op === "actual") return actual;
  if (expression.op === "name") return env[expression.name];
  if (expression.op === "list") return expression.items.map(item => evaluateExpression(item, actual, tolerance, env));
  if (expression.op === "set") return {{[TAG]: "set", items: sortValues(expression.items.map(item => normalize(evaluateExpression(item, actual, tolerance, env))))}};
  if (expression.op === "dict") {{
    const items = expression.items.map(([key, value]) => [
      normalize(evaluateExpression(key, actual, tolerance, env)),
      normalize(evaluateExpression(value, actual, tolerance, env)),
    ]);
    items.sort((a, b) => stable(a[0]).localeCompare(stable(b[0])));
    return {{[TAG]: "dict", items}};
  }}
  if (expression.op === "unary") {{
    const operand = evaluateExpression(expression.operand, actual, tolerance, env);
    if (expression.operator === "not") return !operand;
    if (expression.operator === "neg") return -operand;
    if (expression.operator === "pos") return +operand;
  }}
  if (expression.op === "binary") {{
    const left = evaluateExpression(expression.left, actual, tolerance, env);
    const right = evaluateExpression(expression.right, actual, tolerance, env);
    if (expression.operator === "add") return left + right;
    if (expression.operator === "sub") return left - right;
    if (expression.operator === "mul") return left * right;
    if (expression.operator === "div") return left / right;
    if (expression.operator === "floordiv") return Math.floor(left / right);
    if (expression.operator === "mod") return left % right;
    if (expression.operator === "pow") return left ** right;
  }}
  if (expression.op === "bool") {{
    const values = expression.values.map(value => evaluateExpression(value, actual, tolerance, env));
    if (expression.operator === "and") return values.every(Boolean);
    if (expression.operator === "or") return values.some(Boolean);
  }}
  if (expression.op === "compare") {{
    const left = evaluateExpression(expression.left, actual, tolerance, env);
    const right = evaluateExpression(expression.right, actual, tolerance, env);
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
    return expressionIndex(evaluateExpression(expression.value, actual, tolerance, env), evaluateExpression(expression.index, actual, tolerance, env));
  }}
  if (expression.op === "call") {{
    const args = expression.args.map(arg => evaluateExpression(arg, actual, tolerance, env));
    if (expression.function === "sorted") return expressionSorted(args[0]);
    if (expression.function === "abs") return Math.abs(args[0]);
    if (expression.function === "len") return args[0].length;
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
  let fn;
  const hasExecutableTests = payload.tests.some(test => test.kind !== "loop");
  if (hasExecutableTests) {{
    try {{
      fn = findCallable(await loadSolution(solutionPath), payload.entrypoint);
    }} catch (error) {{
      console.log(JSON.stringify({{status: "fail", passed: [], failed: payload.tests.map(test => test.id)}}));
      return 1;
    }}
  }}

  const passed = [];
  const failed = [];
  for (const test of payload.tests) {{
    let stdout = "";
    let stderr = "";
    const oldOut = process.stdout.write;
    const oldErr = process.stderr.write;
    process.stdout.write = function(chunk, encoding, cb) {{ stdout += String(chunk); if (typeof cb === "function") cb(); return true; }};
    process.stderr.write = function(chunk, encoding, cb) {{ stderr += String(chunk); if (typeof cb === "function") cb(); return true; }};
    let ok = false;
    try {{
      let actual;
      let raised = false;
      let raisedError = null;
      if (test.kind === "loop") {{
        ok = !!test.expected;
      }} else if (test.kind === "mutation") {{
        try {{
          const decodedArgs = test.args.map(decodeArg);
          const env = {{}};
          for (const [name, index] of Object.entries(test.mutation.arg_bindings)) env[name] = decodedArgs[index];
          actual = fn(...decodedArgs);
          if (actual && typeof actual.then === "function") actual = await actual;
          if (test.mutation.assign !== null) env[test.mutation.assign] = actual;
          ok = !!evaluateExpression(test.mutation.assertion, null, tolerancePolicy(test), env);
        }} catch (error) {{
          raised = true;
          raisedError = error;
        }}
      }} else {{
        try {{
          actual = fn(...test.args.map(decodeArg));
          if (actual && typeof actual.then === "function") actual = await actual;
        }} catch (error) {{
          raised = true;
          raisedError = error;
        }}
      }}
      if (test.kind === "loop") {{}}
      else if (test.kind === "mutation") {{}}
      else if (test.kind === "raises") ok = raised && exceptionMatches(raisedError, test.expected_exception) && messageMatches(raisedError, test.message_match);
      else if (raised) ok = false;
      else if (test.kind === "expr") ok = !!evaluateExpression(test.expression, actual, tolerancePolicy(test));
      else if (test.kind === "eq") ok = deepEqual(test.expected, normalize(actual), tolerancePolicy(test));
      else if (test.kind === "neq") ok = !deepEqual(test.expected, normalize(actual), tolerancePolicy(test));
      else if (test.kind === "truthy") ok = !!actual;
      else if (test.kind === "falsy") ok = !actual;
    }} catch (error) {{
      ok = false;
    }} finally {{
      process.stdout.write = oldOut;
      process.stderr.write = oldErr;
    }}
    if (test.expect_stdout !== null && stdout !== test.expect_stdout) ok = false;
    if (test.expect_stderr !== null && stderr !== test.expect_stderr) ok = false;
    (ok ? passed : failed).push(test.id);
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


@dataclass(frozen=True)
class NativeType:
    kind: str
    args: tuple["NativeType", ...] = ()
    optional: bool = False


UNKNOWN_TYPE = NativeType("unknown")
VALUE_TYPE = NativeType("value")
INT_TYPE = NativeType("int")
FLOAT_TYPE = NativeType("float")
BOOL_TYPE = NativeType("bool")
STRING_TYPE = NativeType("string")


def without_optional(native_type: NativeType) -> NativeType:
    if not native_type.optional:
        return native_type
    return NativeType(native_type.kind, native_type.args)


def optional_type(native_type: NativeType) -> NativeType:
    native_type = without_optional(native_type)
    if native_type.kind == "unknown":
        native_type = INT_TYPE
    return NativeType(native_type.kind, native_type.args, True)


def native_type_from_value(value: Any) -> NativeType:
    if value is None:
        return NativeType("unknown", optional=True)
    if isinstance(value, bool):
        return BOOL_TYPE
    if isinstance(value, int):
        return INT_TYPE
    if isinstance(value, float):
        return FLOAT_TYPE
    if isinstance(value, str):
        return STRING_TYPE
    if isinstance(value, list):
        item_type = merge_native_types([native_type_from_value(item) for item in value])
        return NativeType("vector", (item_type if item_type.kind != "unknown" else INT_TYPE,))
    if is_tagged(value, "decimal"):
        return FLOAT_TYPE
    if is_tagged(value, "dict"):
        key_type = merge_native_types([native_type_from_value(key) for key, _ in value["items"]])
        value_type = merge_native_types([native_type_from_value(item) for _, item in value["items"]])
        return NativeType(
            "map",
            (
                key_type if key_type.kind != "unknown" else STRING_TYPE,
                value_type if value_type.kind != "unknown" else INT_TYPE,
            ),
        )
    if is_tagged(value, "set"):
        item_type = merge_native_types([native_type_from_value(item) for item in value["items"]])
        return NativeType("set", (item_type if item_type.kind != "unknown" else INT_TYPE,))
    if is_tagged(value, "counter"):
        key_type = merge_native_types([native_type_from_value(key) for key, _ in value["items"]])
        return NativeType("map", (key_type if key_type.kind != "unknown" else STRING_TYPE, INT_TYPE))
    if is_tagged(value, "deque"):
        item_type = merge_native_types([native_type_from_value(item) for item in value["items"]])
        return NativeType("deque", (item_type if item_type.kind != "unknown" else INT_TYPE,))
    return VALUE_TYPE


def merge_two_native_types(left: NativeType, right: NativeType) -> NativeType:
    left_optional = left.optional
    right_optional = right.optional
    left = without_optional(left)
    right = without_optional(right)
    optional = left_optional or right_optional
    if left.kind == "unknown":
        merged = right
    elif right.kind == "unknown":
        merged = left
    elif left == right:
        merged = left
    elif {left.kind, right.kind} <= {"int", "float"}:
        merged = FLOAT_TYPE
    elif left.kind == right.kind and len(left.args) == len(right.args):
        merged = NativeType(left.kind, tuple(merge_two_native_types(a, b) for a, b in zip(left.args, right.args, strict=True)))
    else:
        merged = VALUE_TYPE
    return optional_type(merged) if optional else merged


def merge_native_types(types: list[NativeType]) -> NativeType:
    merged = UNKNOWN_TYPE
    for native_type in types:
        merged = merge_two_native_types(merged, native_type)
    return merged


def test_arg_types(tests: list[TestCase]) -> list[NativeType]:
    max_args = max((len(test.args) for test in tests if test.kind != "loop"), default=0)
    arg_types: list[NativeType] = []
    for index in range(max_args):
        values = [test.args[index] for test in tests if test.kind != "loop" and index < len(test.args)]
        arg_types.append(merge_native_types([native_type_from_value(value) for value in values]))
    return arg_types


def c_string(value: str) -> str:
    return json.dumps(value)


def cpp_type(native_type: NativeType) -> str:
    if native_type.optional:
        return f"std::optional<{cpp_type(without_optional(native_type))}>"
    if native_type.kind == "bool":
        return "bool"
    if native_type.kind == "int":
        return "long long"
    if native_type.kind == "float":
        return "long double"
    if native_type.kind == "string":
        return "std::string"
    if native_type.kind == "vector":
        return f"std::vector<{cpp_type(native_type.args[0])}>"
    if native_type.kind == "map":
        return f"std::map<{cpp_type(native_type.args[0])}, {cpp_type(native_type.args[1])}>"
    if native_type.kind == "set":
        return f"std::set<{cpp_type(native_type.args[0])}>"
    if native_type.kind == "deque":
        return f"std::deque<{cpp_type(native_type.args[0])}>"
    return "bcg::Value"


def rust_type(native_type: NativeType) -> str:
    if native_type.optional:
        return f"Option<{rust_type(without_optional(native_type))}>"
    if native_type.kind == "bool":
        return "bool"
    if native_type.kind == "int":
        return "i64"
    if native_type.kind == "float":
        return "f64"
    if native_type.kind == "string":
        return "String"
    if native_type.kind == "vector":
        return f"Vec<{rust_type(native_type.args[0])}>"
    if native_type.kind == "map":
        return f"std::collections::HashMap<{rust_type(native_type.args[0])}, {rust_type(native_type.args[1])}>"
    if native_type.kind == "set":
        return f"std::collections::HashSet<{rust_type(native_type.args[0])}>"
    if native_type.kind == "deque":
        return f"Vec<{rust_type(native_type.args[0])}>"
    return "Value"


def cpp_native_literal(value: Any, native_type: NativeType) -> str:
    if native_type.optional:
        inner = without_optional(native_type)
        if value is None:
            return "std::nullopt"
        return f"std::optional<{cpp_type(inner)}>{{{cpp_native_literal(value, inner)}}}"
    if value is None:
        return "{}"
    if native_type.kind == "bool":
        return "true" if value else "false"
    if native_type.kind == "int":
        return str(int(value))
    if native_type.kind == "float":
        if is_tagged(value, "decimal"):
            value = value["value"]
        return f"{value}L"
    if native_type.kind == "string":
        return f"std::string({c_string(str(value))})"
    if native_type.kind == "vector":
        return f"{cpp_type(native_type)}{{{', '.join(cpp_native_literal(item, native_type.args[0]) for item in value)}}}"
    if native_type.kind == "map":
        items = value["items"] if is_tagged(value, "dict") or is_tagged(value, "counter") else []
        return f"{cpp_type(native_type)}{{{', '.join('{' + cpp_native_literal(key, native_type.args[0]) + ', ' + cpp_native_literal(item, native_type.args[1]) + '}' for key, item in items)}}}"
    if native_type.kind == "set":
        items = value["items"] if is_tagged(value, "set") else []
        return f"{cpp_type(native_type)}{{{', '.join(cpp_native_literal(item, native_type.args[0]) for item in items)}}}"
    if native_type.kind == "deque":
        items = value["items"] if is_tagged(value, "deque") else []
        return f"{cpp_type(native_type)}{{{', '.join(cpp_native_literal(item, native_type.args[0]) for item in items)}}}"
    return cpp_value_literal(value)


def cpp_value_literal(value: Any) -> str:
    if value is None:
        return "bcg::Value::null()"
    if isinstance(value, bool):
        return f"bcg::Value::boolean({'true' if value else 'false'})"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"bcg::Value::number({value}L)"
    if isinstance(value, str):
        return f"bcg::Value::string({c_string(value)})"
    if isinstance(value, list):
        return f"bcg::Value::array(std::vector<bcg::Value>{{{', '.join(cpp_value_literal(item) for item in value)}}})"
    if is_tagged(value, "decimal"):
        return f"bcg::Value::number({value['value']}L)"
    if is_tagged(value, "dict"):
        return "bcg::Value::dict(std::vector<std::pair<bcg::Value, bcg::Value>>{" + ", ".join(
            "{" + cpp_value_literal(key) + ", " + cpp_value_literal(item) + "}" for key, item in value["items"]
        ) + "})"
    if is_tagged(value, "counter"):
        return "bcg::Value::counter(std::vector<std::pair<bcg::Value, bcg::Value>>{" + ", ".join(
            "{" + cpp_value_literal(key) + ", " + cpp_value_literal(item) + "}" for key, item in value["items"]
        ) + "})"
    if is_tagged(value, "set"):
        return f"bcg::Value::set(std::vector<bcg::Value>{{{', '.join(cpp_value_literal(item) for item in value['items'])}}})"
    if is_tagged(value, "deque"):
        return f"bcg::Value::deque(std::vector<bcg::Value>{{{', '.join(cpp_value_literal(item) for item in value['items'])}}})"
    return "bcg::Value::null()"


def rust_string(value: str) -> str:
    return json.dumps(value)


def rust_native_literal(value: Any, native_type: NativeType) -> str:
    if native_type.optional:
        inner = without_optional(native_type)
        if value is None:
            return "None"
        return f"Some({rust_native_literal(value, inner)})"
    if value is None:
        return "Default::default()"
    if native_type.kind == "bool":
        return "true" if value else "false"
    if native_type.kind == "int":
        return f"{int(value)}i64"
    if native_type.kind == "float":
        if is_tagged(value, "decimal"):
            value = value["value"]
        return f"{value}f64"
    if native_type.kind == "string":
        return f"String::from({rust_string(str(value))})"
    if native_type.kind == "vector":
        return f"vec![{', '.join(rust_native_literal(item, native_type.args[0]) for item in value)}]"
    if native_type.kind == "map":
        items = value["items"] if is_tagged(value, "dict") or is_tagged(value, "counter") else []
        entries = ", ".join(
            f"({rust_native_literal(key, native_type.args[0])}, {rust_native_literal(item, native_type.args[1])})"
            for key, item in items
        )
        return f"std::collections::HashMap::from([{entries}])"
    if native_type.kind == "set":
        items = value["items"] if is_tagged(value, "set") else []
        return f"std::collections::HashSet::from([{', '.join(rust_native_literal(item, native_type.args[0]) for item in items)}])"
    if native_type.kind == "deque":
        items = value["items"] if is_tagged(value, "deque") else []
        return f"vec![{', '.join(rust_native_literal(item, native_type.args[0]) for item in items)}]"
    return rust_value_literal(value)


def rust_value_literal(value: Any) -> str:
    if value is None:
        return "Value::Null"
    if isinstance(value, bool):
        return f"Value::Bool({'true' if value else 'false'})"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"Value::Number({value}f64)"
    if isinstance(value, str):
        return f"Value::String(String::from({rust_string(value)}))"
    if isinstance(value, list):
        return f"Value::Array(vec![{', '.join(rust_value_literal(item) for item in value)}])"
    if is_tagged(value, "decimal"):
        return f"Value::Number({value['value']}f64)"
    if is_tagged(value, "dict"):
        return "Value::Dict(vec![" + ", ".join(
            f"({rust_value_literal(key)}, {rust_value_literal(item)})" for key, item in value["items"]
        ) + "])"
    if is_tagged(value, "counter"):
        return "Value::Counter(vec![" + ", ".join(
            f"({rust_value_literal(key)}, {rust_value_literal(item)})" for key, item in value["items"]
        ) + "])"
    if is_tagged(value, "set"):
        return f"Value::Set(vec![{', '.join(rust_value_literal(item) for item in value['items'])}])"
    if is_tagged(value, "deque"):
        return f"Value::Deque(vec![{', '.join(rust_value_literal(item) for item in value['items'])}])"
    return "Value::Null"


def cpp_runtime_source() -> str:
    return r"""
#ifndef BCG_SOLUTION_INCLUDE
#error "BCG_SOLUTION_INCLUDE is required"
#endif
#include BCG_SOLUTION_INCLUDE
#include <algorithm>
#include <cstdlib>
#include <cmath>
#include <deque>
#include <exception>
#include <future>
#include <functional>
#include <iostream>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace bcg {
struct Value {
  enum Kind { Null, Bool, Number, String, Array, Dict, Set, Counter, Deque } kind = Null;
  bool b = false;
  long double n = 0;
  std::string s;
  std::vector<Value> items;
  std::vector<std::pair<Value, Value>> pairs;
  static Value null() { return {}; }
  static Value boolean(bool v) { Value out; out.kind = Bool; out.b = v; return out; }
  static Value number(long double v) { Value out; out.kind = Number; out.n = v; return out; }
  static Value string(std::string v) { Value out; out.kind = String; out.s = std::move(v); return out; }
  static Value array(std::vector<Value> v) { Value out; out.kind = Array; out.items = std::move(v); return out; }
  static Value dict(std::vector<std::pair<Value, Value>> v) { Value out; out.kind = Dict; out.pairs = std::move(v); return out; }
  static Value set(std::vector<Value> v) { Value out; out.kind = Set; out.items = std::move(v); return out; }
  static Value counter(std::vector<std::pair<Value, Value>> v) { Value out; out.kind = Counter; out.pairs = std::move(v); return out; }
  static Value deque(std::vector<Value> v) { Value out; out.kind = Deque; out.items = std::move(v); return out; }
};

std::string escape_json(const std::string& text) {
  std::string out;
  for (char ch : text) {
    if (ch == '"' || ch == '\\') { out += '\\'; out += ch; }
    else if (ch == '\n') out += "\\n";
    else if (ch == '\r') out += "\\r";
    else if (ch == '\t') out += "\\t";
    else out += ch;
  }
  return out;
}

std::string stable(const Value& value) {
  std::ostringstream out;
  out << static_cast<int>(value.kind) << ":";
  if (value.kind == Value::Null) out << "null";
  else if (value.kind == Value::Bool) out << (value.b ? "true" : "false");
  else if (value.kind == Value::Number) out << static_cast<double>(value.n);
  else if (value.kind == Value::String) out << value.s;
  else if (value.kind == Value::Array || value.kind == Value::Set || value.kind == Value::Deque) {
    out << "[";
    for (const auto& item : value.items) out << stable(item) << ",";
    out << "]";
  } else {
    out << "{";
    for (const auto& pair : value.pairs) out << stable(pair.first) << ":" << stable(pair.second) << ",";
    out << "}";
  }
  return out.str();
}

void sort_items(std::vector<Value>& values) {
  std::sort(values.begin(), values.end(), [](const Value& a, const Value& b) { return stable(a) < stable(b); });
}
void sort_pairs(std::vector<std::pair<Value, Value>>& values) {
  std::sort(values.begin(), values.end(), [](const auto& a, const auto& b) { return stable(a.first) < stable(b.first); });
}

Value normalize(const Value& value) { return value; }
Value normalize(std::nullptr_t) { return Value::null(); }
Value normalize(bool value) { return Value::boolean(value); }
template <typename T, typename std::enable_if<std::is_integral<T>::value && !std::is_same<T, bool>::value, int>::type = 0>
Value normalize(T value) { return Value::number(static_cast<long double>(value)); }
template <typename T, typename std::enable_if<std::is_floating_point<T>::value, int>::type = 0>
Value normalize(T value) { return Value::number(static_cast<long double>(value)); }
Value normalize(const char* value) { return Value::string(std::string(value)); }
Value normalize(const std::string& value) { return Value::string(value); }
template <typename T> Value normalize(const std::optional<T>& value) { return value ? normalize(*value) : Value::null(); }
template <typename T> Value normalize(const std::vector<T>& value) {
  std::vector<Value> items; for (const auto& item : value) items.push_back(normalize(item)); return Value::array(items);
}
template <typename T> Value normalize(const std::deque<T>& value) {
  std::vector<Value> items; for (const auto& item : value) items.push_back(normalize(item)); return Value::deque(items);
}
template <typename T> Value normalize(const std::set<T>& value) {
  std::vector<Value> items; for (const auto& item : value) items.push_back(normalize(item)); sort_items(items); return Value::set(items);
}
template <typename T> Value normalize(const std::unordered_set<T>& value) {
  std::vector<Value> items; for (const auto& item : value) items.push_back(normalize(item)); sort_items(items); return Value::set(items);
}
template <typename K, typename V> Value normalize(const std::map<K, V>& value) {
  std::vector<std::pair<Value, Value>> pairs; for (const auto& item : value) pairs.push_back({normalize(item.first), normalize(item.second)}); sort_pairs(pairs); return Value::dict(pairs);
}
template <typename K, typename V> Value normalize(const std::unordered_map<K, V>& value) {
  std::vector<std::pair<Value, Value>> pairs; for (const auto& item : value) pairs.push_back({normalize(item.first), normalize(item.second)}); sort_pairs(pairs); return Value::dict(pairs);
}

template <typename T> struct is_future : std::false_type {};
template <typename T> struct is_future<std::future<T>> : std::true_type {};
template <typename T> struct is_future<std::shared_future<T>> : std::true_type {};
template <typename T> decltype(auto) await_value(T&& value) {
  if constexpr (is_future<std::decay_t<T>>::value) {
    return value.get();
  } else {
    return std::forward<T>(value);
  }
}
template <typename F> void invoke_discard(F&& fn) {
  if constexpr (std::is_void_v<decltype(fn())>) {
    fn();
  } else if constexpr (std::is_void_v<decltype(await_value(fn()))>) {
    await_value(fn());
  } else {
    (void)await_value(fn());
  }
}

bool numeric_equal(const Value& expected, const Value& actual, long double abs_tol, long double rel_tol, bool strict) {
  if (expected.kind != Value::Number || actual.kind != Value::Number) return false;
  long double diff = std::fabs(actual.n - expected.n);
  if (strict) return diff < abs_tol;
  long double limit = std::max(abs_tol, rel_tol * std::max(std::fabs(actual.n), std::fabs(expected.n)));
  return diff <= limit;
}
bool deep_equal(const Value& expected, const Value& actual, long double abs_tol, long double rel_tol = 0, bool strict = false);
bool unordered_equal(const std::vector<Value>& expected, const std::vector<Value>& actual, long double abs_tol, long double rel_tol, bool strict) {
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  for (const auto& e : expected) {
    bool matched = false;
    for (size_t i = 0; i < actual.size(); ++i) {
      if (!used[i] && deep_equal(e, actual[i], abs_tol, rel_tol, strict)) { used[i] = true; matched = true; break; }
    }
    if (!matched) return false;
  }
  return true;
}
bool dict_equal(const std::vector<std::pair<Value, Value>>& expected, const std::vector<std::pair<Value, Value>>& actual, long double abs_tol, long double rel_tol, bool strict) {
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  for (const auto& e : expected) {
    bool matched = false;
    for (size_t i = 0; i < actual.size(); ++i) {
      if (!used[i] && deep_equal(e.first, actual[i].first, 0, 0, false) && deep_equal(e.second, actual[i].second, abs_tol, rel_tol, strict)) {
        used[i] = true; matched = true; break;
      }
    }
    if (!matched) return false;
  }
  return true;
}
bool deep_equal(const Value& expected, const Value& actual, long double abs_tol, long double rel_tol, bool strict) {
  if (expected.kind == Value::Number && actual.kind == Value::Number) return numeric_equal(expected, actual, abs_tol, rel_tol, strict);
  if (expected.kind != actual.kind) {
    if (!((expected.kind == Value::Counter && actual.kind == Value::Dict) || (expected.kind == Value::Dict && actual.kind == Value::Counter))) return false;
  }
  if (expected.kind == Value::Null) return true;
  if (expected.kind == Value::Bool) return expected.b == actual.b;
  if (expected.kind == Value::String) return expected.s == actual.s;
  if (expected.kind == Value::Array) {
    if (expected.items.size() != actual.items.size()) return false;
    for (size_t i = 0; i < expected.items.size(); ++i) if (!deep_equal(expected.items[i], actual.items[i], abs_tol, rel_tol, strict)) return false;
    return true;
  }
  if (expected.kind == Value::Set) return unordered_equal(expected.items, actual.items, abs_tol, rel_tol, strict);
  if (expected.kind == Value::Deque) {
    if (expected.items.size() != actual.items.size()) return false;
    for (size_t i = 0; i < expected.items.size(); ++i) if (!deep_equal(expected.items[i], actual.items[i], abs_tol, rel_tol, strict)) return false;
    return true;
  }
  if (expected.kind == Value::Dict || expected.kind == Value::Counter) return dict_equal(expected.pairs, actual.pairs, abs_tol, rel_tol, strict);
  return false;
}

bool truthy(const Value& value) {
  if (value.kind == Value::Null) return false;
  if (value.kind == Value::Bool) return value.b;
  if (value.kind == Value::Number) return value.n != 0;
  if (value.kind == Value::String) return !value.s.empty();
  if (value.kind == Value::Array || value.kind == Value::Set || value.kind == Value::Deque) return !value.items.empty();
  return !value.pairs.empty();
}

Value index_value(const Value& value, const Value& index) {
  if ((value.kind == Value::Array || value.kind == Value::Deque) && index.kind == Value::Number) return value.items.at(static_cast<size_t>(index.n));
  if (value.kind == Value::String && index.kind == Value::Number) return Value::string(std::string(1, value.s.at(static_cast<size_t>(index.n))));
  if (value.kind == Value::Dict) for (const auto& pair : value.pairs) if (deep_equal(pair.first, index, 0)) return pair.second;
  throw std::runtime_error("bad index");
}

bool contains_value(const Value& container, const Value& needle, long double abs_tol) {
  if (container.kind == Value::String && needle.kind == Value::String) return container.s.find(needle.s) != std::string::npos;
  if (container.kind == Value::Dict) { for (const auto& pair : container.pairs) if (deep_equal(pair.first, needle, abs_tol)) return true; return false; }
  const auto& items = container.items;
  for (const auto& item : items) if (deep_equal(item, needle, abs_tol)) return true;
  return false;
}

Value sorted_value(Value value) {
  if (value.kind == Value::String) { std::vector<Value> items; for (char ch : value.s) items.push_back(Value::string(std::string(1, ch))); sort_items(items); return Value::array(items); }
  sort_items(value.items); return Value::array(value.items);
}

void print_result(const std::vector<std::string>& passed, const std::vector<std::string>& failed) {
  std::cout << "{\"status\":\"" << (failed.empty() ? "pass" : "fail") << "\",\"passed\":[";
  for (size_t i = 0; i < passed.size(); ++i) { if (i) std::cout << ","; std::cout << "\"" << escape_json(passed[i]) << "\""; }
  std::cout << "],\"failed\":[";
  for (size_t i = 0; i < failed.size(); ++i) { if (i) std::cout << ","; std::cout << "\"" << escape_json(failed[i]) << "\""; }
  std::cout << "]}\n";
}

struct Capture {
  std::ostringstream out;
  std::ostringstream err;
  std::streambuf* old_out;
  std::streambuf* old_err;
  Capture() : old_out(std::cout.rdbuf(out.rdbuf())), old_err(std::cerr.rdbuf(err.rdbuf())) {}
  ~Capture() { std::cout.rdbuf(old_out); std::cerr.rdbuf(old_err); }
};
}
"""


def cpp_call_block(test: TestCase, arg_types: list[NativeType]) -> str:
    args = []
    declarations = []
    for index, value in enumerate(test.args):
        native_type = arg_types[index]
        declarations.append(f"  auto arg{index} = {cpp_native_literal(value, native_type)};")
        args.append(f"arg{index}")
    call = f"{test.source_path}:{test.line}"
    tolerance = test.tolerance or {}
    abs_tol = tolerance.get("abs", "DEFAULT_TOL")
    rel_tol = tolerance.get("rel", 0.0)
    strict = "true" if tolerance.get("mode") == "absdiff" and tolerance.get("strict") else "false"
    expected = cpp_value_literal(test.expected)
    lines = [f"{{ // {call}", *declarations, "  bool ok = false;", "  bcg::Capture cap;", "  try {"]
    if test.kind == "mutation":
        lines.extend([
            f"    auto invoke = [&]() -> decltype(auto) {{ return {test_arg_entrypoint_name()}({', '.join(args)}); }};",
            "    bcg::invoke_discard(invoke);",
        ])
        assertion = test.mutation["assertion"] if test.mutation else {"op": "const", "value": False}
        lines.append(f"    ok = {cpp_expression_bool(assertion, test.mutation or {}, arg_types)};")
    else:
        lines.append(f"    auto invoke = [&]() -> decltype(auto) {{ return {test_arg_entrypoint_name()}({', '.join(args)}); }};")
        if test.kind == "raises":
            lines.append("    bcg::invoke_discard(invoke);")
            lines.append("    ok = false;")
        else:
            lines.append("    if constexpr (std::is_void_v<decltype(invoke())>) { invoke(); ok = false; } else {")
            lines.append("      auto actual_native = bcg::await_value(invoke());")
            lines.append("      auto actual = bcg::normalize(actual_native);")
            if test.kind == "eq":
                lines.append(f"      ok = bcg::deep_equal({expected}, actual, {abs_tol}, {rel_tol}, {strict});")
            elif test.kind == "neq":
                lines.append(f"      ok = !bcg::deep_equal({expected}, actual, {abs_tol}, {rel_tol}, {strict});")
            elif test.kind == "truthy":
                lines.append("      ok = bcg::truthy(actual);")
            elif test.kind == "falsy":
                lines.append("      ok = !bcg::truthy(actual);")
            elif test.kind == "expr":
                lines.append(f"      ok = {cpp_expression_bool(test.expression or {}, {}, arg_types, 'actual')};")
            else:
                lines.append("      ok = false;")
            lines.append("    }")
    lines.append("  } catch (const std::exception& e) {")
    if test.kind == "raises":
        matcher = test.message_match
        expected_exception = test.expected_exception
        type_ok = "true" if expected_exception in {None, "Exception", "RuntimeError", "ValueError"} else "true"
        if matcher and matcher.get("mode") == "contains":
            message_ok = f"std::string(e.what()).find({c_string(matcher.get('pattern', ''))}) != std::string::npos"
        elif matcher and matcher.get("mode") == "regex":
            message_ok = f"std::regex_search(std::string(e.what()), std::regex({c_string(matcher.get('pattern', ''))}))"
        else:
            message_ok = "true"
        lines.append(f"    ok = ({type_ok}) && ({message_ok});")
    else:
        lines.append("    ok = false;")
    lines.append("  }")
    if test.expect_stdout is not None:
        lines.append(f"  if (cap.out.str() != {c_string(test.expect_stdout)}) ok = false;")
    if test.expect_stderr is not None:
        lines.append(f"  if (cap.err.str() != {c_string(test.expect_stderr)}) ok = false;")
    lines.append(f"  (ok ? passed : failed).push_back({c_string(test.id)});")
    lines.append("}")
    return "\n".join(lines)


_CURRENT_ENTRYPOINT = "solve"


def test_arg_entrypoint_name() -> str:
    return _CURRENT_ENTRYPOINT


def cpp_expression_value(expression: dict[str, Any], mutation: dict[str, Any], arg_types: list[NativeType], actual_name: str = "actual") -> str:
    op = expression.get("op")
    if op == "const":
        return cpp_value_literal(expression.get("value"))
    if op == "actual":
        return actual_name
    if op == "name":
        name = expression["name"]
        if mutation.get("assign") == name:
            return "bcg::Value::null()"
        index = mutation.get("arg_bindings", {}).get(name)
        if index is not None:
            return f"bcg::normalize(arg{index})"
    if op == "index":
        return f"bcg::index_value({cpp_expression_value(expression['value'], mutation, arg_types, actual_name)}, {cpp_expression_value(expression['index'], mutation, arg_types, actual_name)})"
    if op == "call" and expression.get("function") == "sorted":
        return f"bcg::sorted_value({cpp_expression_value(expression['args'][0], mutation, arg_types, actual_name)})"
    if op == "call" and expression.get("function") == "abs":
        return cpp_expression_value(expression["args"][0], mutation, arg_types, actual_name)
    if op == "list":
        return "bcg::Value::array(std::vector<bcg::Value>{" + ", ".join(
            cpp_expression_value(item, mutation, arg_types, actual_name) for item in expression.get("items", [])
        ) + "})"
    if op == "set":
        return "bcg::Value::set(std::vector<bcg::Value>{" + ", ".join(
            cpp_expression_value(item, mutation, arg_types, actual_name) for item in expression.get("items", [])
        ) + "})"
    return "bcg::Value::null()"


def cpp_expression_bool(expression: dict[str, Any], mutation: dict[str, Any], arg_types: list[NativeType], actual_name: str = "actual") -> str:
    op = expression.get("op")
    if op == "compare":
        left = cpp_expression_value(expression["left"], mutation, arg_types, actual_name)
        right = cpp_expression_value(expression["right"], mutation, arg_types, actual_name)
        operator = expression.get("operator")
        if operator == "eq":
            return f"bcg::deep_equal({left}, {right}, DEFAULT_TOL)"
        if operator == "neq":
            return f"!bcg::deep_equal({left}, {right}, DEFAULT_TOL)"
        if operator == "in":
            return f"bcg::contains_value({right}, {left}, DEFAULT_TOL)"
        if operator == "not_in":
            return f"!bcg::contains_value({right}, {left}, DEFAULT_TOL)"
    if op == "actual":
        return f"bcg::truthy({actual_name})"
    return f"bcg::truthy({cpp_expression_value(expression, mutation, arg_types, actual_name)})"


def cpp_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    global _CURRENT_ENTRYPOINT
    _CURRENT_ENTRYPOINT = entrypoint
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    arg_types = test_arg_types(tests)
    body = []
    for test in tests:
        if test.kind == "loop":
            body.append(f'{{ bool ok = {"true" if test.expected else "false"}; (ok ? passed : failed).push_back({c_string(test.id)}); }}')
        else:
            body.append(cpp_call_block(test, arg_types))
    return (
        f"// BCG_PAYLOAD:{payload}\n"
        + cpp_runtime_source()
        + "\nint main() {\n"
        + "  const long double DEFAULT_TOL = std::strtold(std::getenv(\"BABEL_CODE_GOAT_TOL\") ? std::getenv(\"BABEL_CODE_GOAT_TOL\") : \"0\", nullptr);\n"
        + "  std::vector<std::string> passed;\n  std::vector<std::string> failed;\n"
        + "\n".join(body)
        + "\n  bcg::print_result(passed, failed);\n  return failed.empty() ? 0 : 1;\n}\n"
    )


def rust_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    arg_types = test_arg_types(tests)
    body = []
    for test in tests:
        if test.kind == "loop":
            body.append(f'run_case({"true" if test.expected else "false"}, {rust_string(test.id)}, &mut passed, &mut failed);')
            continue
        declarations = [
            f"let mut arg{index}: {rust_type(arg_types[index])} = {rust_native_literal(value, arg_types[index])};"
            for index, value in enumerate(test.args)
        ]
        args = ", ".join(f"arg{index}.clone()" for index in range(len(test.args)))
        expected = rust_value_literal(test.expected)
        tolerance = test.tolerance or {}
        abs_tol = tolerance.get("abs", "default_tol")
        rel_tol = tolerance.get("rel", 0.0)
        strict = "true" if tolerance.get("mode") == "absdiff" and tolerance.get("strict") else "false"
        lines = ["{", *declarations, "let mut ok = false;"]
        if test.kind == "raises":
            lines.append(f"let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{ resolve_value({entrypoint}({args})); }}));")
            if test.message_match and test.message_match.get("mode") == "contains":
                lines.append(f"ok = result.is_err() && panic_message_contains(result.err(), {rust_string(test.message_match.get('pattern', ''))});")
            else:
                lines.append("ok = result.is_err();")
        elif test.kind == "mutation":
            call_args = ", ".join(f"&mut arg{index}" if arg_types[index].kind in {"vector", "map", "set", "deque"} else f"arg{index}.clone()" for index in range(len(test.args)))
            lines.append(f"let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{ resolve_value({entrypoint}({call_args})); }}));")
            assertion = test.mutation["assertion"] if test.mutation else {"op": "const", "value": False}
            lines.append(f"ok = {rust_expression_bool(assertion, test.mutation or {}, arg_types)};")
        else:
            lines.append(f"let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| resolve_value({entrypoint}({args}))));")
            lines.append("if let Ok(actual_native) = result { let actual = actual_native.to_value();")
            if test.kind == "eq":
                lines.append(f"ok = deep_equal(&{expected}, &actual, {abs_tol}, {rel_tol}, {strict});")
            elif test.kind == "neq":
                lines.append(f"ok = !deep_equal(&{expected}, &actual, {abs_tol}, {rel_tol}, {strict});")
            elif test.kind == "truthy":
                lines.append("ok = truthy(&actual);")
            elif test.kind == "falsy":
                lines.append("ok = !truthy(&actual);")
            elif test.kind == "expr":
                lines.append(f"ok = {rust_expression_bool(test.expression or {}, {}, arg_types, 'actual.clone()')};")
            lines.append("}")
        lines.append(f"run_case(ok, {rust_string(test.id)}, &mut passed, &mut failed);")
        lines.append("}")
        body.append("\n".join(lines))
    return f"""// BCG_PAYLOAD:{payload}
include!(env!("BCG_SOLUTION_PATH"));

#[derive(Clone, Debug)]
enum Value {{
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<Value>),
    Dict(Vec<(Value, Value)>),
    Set(Vec<Value>),
    Counter(Vec<(Value, Value)>),
    Deque(Vec<Value>),
}}

trait ToValue {{ fn to_value(&self) -> Value; }}
impl ToValue for () {{ fn to_value(&self) -> Value {{ Value::Null }} }}
impl ToValue for bool {{ fn to_value(&self) -> Value {{ Value::Bool(*self) }} }}
impl ToValue for i64 {{ fn to_value(&self) -> Value {{ Value::Number(*self as f64) }} }}
impl ToValue for i32 {{ fn to_value(&self) -> Value {{ Value::Number(*self as f64) }} }}
impl ToValue for usize {{ fn to_value(&self) -> Value {{ Value::Number(*self as f64) }} }}
impl ToValue for f64 {{ fn to_value(&self) -> Value {{ Value::Number(*self) }} }}
impl ToValue for String {{ fn to_value(&self) -> Value {{ Value::String(self.clone()) }} }}
impl ToValue for &str {{ fn to_value(&self) -> Value {{ Value::String(self.to_string()) }} }}
impl<T: ToValue> ToValue for Option<T> {{ fn to_value(&self) -> Value {{ self.as_ref().map(|v| v.to_value()).unwrap_or(Value::Null) }} }}
impl<T: ToValue> ToValue for Vec<T> {{ fn to_value(&self) -> Value {{ Value::Array(self.iter().map(|v| v.to_value()).collect()) }} }}
impl<T: ToValue + Eq + std::hash::Hash> ToValue for std::collections::HashSet<T> {{ fn to_value(&self) -> Value {{ let mut items: Vec<Value> = self.iter().map(|v| v.to_value()).collect(); sort_values(&mut items); Value::Set(items) }} }}
impl<K: ToValue + Eq + std::hash::Hash, V: ToValue> ToValue for std::collections::HashMap<K, V> {{ fn to_value(&self) -> Value {{ let mut items: Vec<(Value, Value)> = self.iter().map(|(k, v)| (k.to_value(), v.to_value())).collect(); sort_pairs(&mut items); Value::Dict(items) }} }}

trait BcgOwnedStringGetMut<V> {{ fn get_mut(&mut self, key: String) -> Option<&mut V>; }}
impl<V> BcgOwnedStringGetMut<V> for std::collections::HashMap<String, V> {{
    fn get_mut(&mut self, key: String) -> Option<&mut V> {{
        std::collections::HashMap::get_mut(self, &key)
    }}
}}

fn noop_raw_waker() -> std::task::RawWaker {{
    fn clone(_: *const ()) -> std::task::RawWaker {{ noop_raw_waker() }}
    fn wake(_: *const ()) {{}}
    fn wake_by_ref(_: *const ()) {{}}
    fn drop(_: *const ()) {{}}
    std::task::RawWaker::new(std::ptr::null(), &std::task::RawWakerVTable::new(clone, wake, wake_by_ref, drop))
}}
fn block_on<F: std::future::Future>(future: F) -> F::Output {{
    let waker = unsafe {{ std::task::Waker::from_raw(noop_raw_waker()) }};
    let mut context = std::task::Context::from_waker(&waker);
    let mut future = Box::pin(future);
    loop {{
        match std::future::Future::poll(std::pin::Pin::as_mut(&mut future), &mut context) {{
            std::task::Poll::Ready(value) => return value,
            std::task::Poll::Pending => std::thread::yield_now(),
        }}
    }}
}}

trait BcgResolve {{ type Output; fn resolve(self) -> Self::Output; }}
fn resolve_value<T: BcgResolve>(value: T) -> T::Output {{ value.resolve() }}
impl BcgResolve for () {{ type Output = (); fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for bool {{ type Output = bool; fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for i64 {{ type Output = i64; fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for i32 {{ type Output = i32; fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for usize {{ type Output = usize; fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for f64 {{ type Output = f64; fn resolve(self) -> Self::Output {{ self }} }}
impl BcgResolve for String {{ type Output = String; fn resolve(self) -> Self::Output {{ self }} }}
impl<'a> BcgResolve for &'a str {{ type Output = &'a str; fn resolve(self) -> Self::Output {{ self }} }}
impl<T> BcgResolve for Option<T> {{ type Output = Option<T>; fn resolve(self) -> Self::Output {{ self }} }}
impl<T> BcgResolve for Vec<T> {{ type Output = Vec<T>; fn resolve(self) -> Self::Output {{ self }} }}
impl<T: Eq + std::hash::Hash> BcgResolve for std::collections::HashSet<T> {{ type Output = std::collections::HashSet<T>; fn resolve(self) -> Self::Output {{ self }} }}
impl<K: Eq + std::hash::Hash, V> BcgResolve for std::collections::HashMap<K, V> {{ type Output = std::collections::HashMap<K, V>; fn resolve(self) -> Self::Output {{ self }} }}
impl<F: std::future::Future> BcgResolve for F {{ type Output = F::Output; fn resolve(self) -> Self::Output {{ block_on(self) }} }}

fn stable(value: &Value) -> String {{ format!("{{:?}}", value) }}
fn sort_values(values: &mut Vec<Value>) {{ values.sort_by_key(stable); }}
fn sort_pairs(values: &mut Vec<(Value, Value)>) {{ values.sort_by_key(|(k, _)| stable(k)); }}
fn numeric_equal(expected: &Value, actual: &Value, abs_tol: f64, rel_tol: f64, strict: bool) -> bool {{
    match (expected, actual) {{
        (Value::Number(e), Value::Number(a)) => {{
            let diff = (a - e).abs();
            if strict {{ diff < abs_tol }} else {{ diff <= abs_tol.max(rel_tol * a.abs().max(e.abs())) }}
        }}
        _ => false,
    }}
}}
fn unordered_equal(expected: &[Value], actual: &[Value], abs_tol: f64, rel_tol: f64, strict: bool) -> bool {{
    if expected.len() != actual.len() {{ return false; }}
    let mut used = vec![false; actual.len()];
    for e in expected {{
        let mut matched = false;
        for (i, a) in actual.iter().enumerate() {{
            if !used[i] && deep_equal(e, a, abs_tol, rel_tol, strict) {{ used[i] = true; matched = true; break; }}
        }}
        if !matched {{ return false; }}
    }}
    true
}}
fn dict_equal(expected: &[(Value, Value)], actual: &[(Value, Value)], abs_tol: f64, rel_tol: f64, strict: bool) -> bool {{
    if expected.len() != actual.len() {{ return false; }}
    let mut used = vec![false; actual.len()];
    for (ek, ev) in expected {{
        let mut matched = false;
        for (i, (ak, av)) in actual.iter().enumerate() {{
            if !used[i] && deep_equal(ek, ak, 0.0, 0.0, false) && deep_equal(ev, av, abs_tol, rel_tol, strict) {{ used[i] = true; matched = true; break; }}
        }}
        if !matched {{ return false; }}
    }}
    true
}}
fn deep_equal(expected: &Value, actual: &Value, abs_tol: f64, rel_tol: f64, strict: bool) -> bool {{
    match (expected, actual) {{
        (Value::Number(_), Value::Number(_)) => numeric_equal(expected, actual, abs_tol, rel_tol, strict),
        (Value::Null, Value::Null) => true,
        (Value::Bool(e), Value::Bool(a)) => e == a,
        (Value::String(e), Value::String(a)) => e == a,
        (Value::Array(e), Value::Array(a)) | (Value::Deque(e), Value::Deque(a)) => e.len() == a.len() && e.iter().zip(a).all(|(x, y)| deep_equal(x, y, abs_tol, rel_tol, strict)),
        (Value::Set(e), Value::Set(a)) => unordered_equal(e, a, abs_tol, rel_tol, strict),
        (Value::Dict(e), Value::Dict(a)) | (Value::Counter(e), Value::Counter(a)) | (Value::Counter(e), Value::Dict(a)) | (Value::Dict(e), Value::Counter(a)) => dict_equal(e, a, abs_tol, rel_tol, strict),
        _ => false,
    }}
}}
fn truthy(value: &Value) -> bool {{
    match value {{
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => *v != 0.0,
        Value::String(v) => !v.is_empty(),
        Value::Array(v) | Value::Set(v) | Value::Deque(v) => !v.is_empty(),
        Value::Dict(v) | Value::Counter(v) => !v.is_empty(),
    }}
}}
fn contains_value(container: &Value, needle: &Value, abs_tol: f64) -> bool {{
    match container {{
        Value::String(s) => matches!(needle, Value::String(n) if s.contains(n)),
        Value::Array(items) | Value::Set(items) | Value::Deque(items) => items.iter().any(|item| deep_equal(item, needle, abs_tol, 0.0, false)),
        Value::Dict(items) | Value::Counter(items) => items.iter().any(|(key, _)| deep_equal(key, needle, abs_tol, 0.0, false)),
        _ => false,
    }}
}}
fn index_value(value: Value, index: Value) -> Value {{
    match (value, index) {{
        (Value::Array(items), Value::Number(i)) | (Value::Deque(items), Value::Number(i)) => items[i as usize].clone(),
        (Value::Dict(items), key) => items.into_iter().find(|(k, _)| deep_equal(k, &key, 0.0, 0.0, false)).map(|(_, v)| v).unwrap_or(Value::Null),
        _ => Value::Null,
    }}
}}
fn sorted_value(value: Value) -> Value {{
    match value {{
        Value::Array(mut items) | Value::Set(mut items) | Value::Deque(mut items) => {{ sort_values(&mut items); Value::Array(items) }}
        Value::String(s) => {{ let mut items: Vec<Value> = s.chars().map(|c| Value::String(c.to_string())).collect(); sort_values(&mut items); Value::Array(items) }}
        other => other,
    }}
}}
fn panic_message_contains(error: Option<Box<dyn std::any::Any + Send>>, needle: &str) -> bool {{
    if let Some(error) = error {{
        if let Some(text) = error.downcast_ref::<String>() {{ return text.contains(needle); }}
        if let Some(text) = error.downcast_ref::<&str>() {{ return text.contains(needle); }}
    }}
    false
}}
fn json_array(values: &[String]) -> String {{ values.iter().map(|v| format!("\\\"{{}}\\\"", v)).collect::<Vec<_>>().join(",") }}
fn run_case(ok: bool, id: &str, passed: &mut Vec<String>, failed: &mut Vec<String>) {{ if ok {{ passed.push(id.to_string()); }} else {{ failed.push(id.to_string()); }} }}

fn main() {{
    let default_tol: f64 = std::env::var("BABEL_CODE_GOAT_TOL").ok().and_then(|v| v.parse().ok()).unwrap_or(0.0);
    let mut passed = Vec::new();
    let mut failed = Vec::new();
{chr(10).join('    ' + line for block in body for line in block.splitlines())}
    let status = if failed.is_empty() {{ "pass" }} else {{ "fail" }};
    println!("{{\\\"status\\\":\\\"{{}}\\\",\\\"passed\\\":[{{}}],\\\"failed\\\":[{{}}]}}", status, json_array(&passed), json_array(&failed));
    std::process::exit(if failed.is_empty() {{ 0 }} else {{ 1 }});
}}
"""


def rust_expression_value(expression: dict[str, Any], mutation: dict[str, Any], arg_types: list[NativeType], actual_name: str = "actual.clone()") -> str:
    op = expression.get("op")
    if op == "const":
        return rust_value_literal(expression.get("value"))
    if op == "actual":
        return actual_name
    if op == "name":
        index = mutation.get("arg_bindings", {}).get(expression["name"])
        if index is not None:
            return f"arg{index}.to_value()"
    if op == "index":
        return f"index_value({rust_expression_value(expression['value'], mutation, arg_types, actual_name)}, {rust_expression_value(expression['index'], mutation, arg_types, actual_name)})"
    if op == "call" and expression.get("function") == "sorted":
        return f"sorted_value({rust_expression_value(expression['args'][0], mutation, arg_types, actual_name)})"
    if op == "list":
        return "Value::Array(vec![" + ", ".join(rust_expression_value(item, mutation, arg_types, actual_name) for item in expression.get("items", [])) + "])"
    if op == "set":
        return "Value::Set(vec![" + ", ".join(rust_expression_value(item, mutation, arg_types, actual_name) for item in expression.get("items", [])) + "])"
    return "Value::Null"


def rust_expression_bool(expression: dict[str, Any], mutation: dict[str, Any], arg_types: list[NativeType], actual_name: str = "actual.clone()") -> str:
    op = expression.get("op")
    if op == "compare":
        left = rust_expression_value(expression["left"], mutation, arg_types, actual_name)
        right = rust_expression_value(expression["right"], mutation, arg_types, actual_name)
        operator = expression.get("operator")
        if operator == "eq":
            return f"deep_equal(&{left}, &{right}, default_tol, 0.0, false)"
        if operator == "neq":
            return f"!deep_equal(&{left}, &{right}, default_tol, 0.0, false)"
        if operator == "in":
            return f"contains_value(&{right}, &{left}, default_tol)"
        if operator == "not_in":
            return f"!contains_value(&{right}, &{left}, default_tol)"
    return f"truthy(&{rust_expression_value(expression, mutation, arg_types, actual_name)})"


def tester_source(lang: str, entrypoint: str, tests: list[TestCase]) -> str:
    if lang == "python":
        return python_tester_source(entrypoint, tests)
    if lang in {"javascript", "typescript"}:
        return javascript_tester_source(entrypoint, tests)
    if lang == "cpp":
        return cpp_tester_source(entrypoint, tests)
    if lang == "rust":
        return rust_tester_source(entrypoint, tests)
    raise DiscoveryError("unsupported language")


def generate_tester(lang: str, entrypoint: str, tests_dir: Path) -> None:
    tests = discover_tests(tests_dir, entrypoint)
    filename = SUPPORTED_LANGS[lang]["tester"]
    source = tester_source(lang, entrypoint, tests)
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
    match = re.search(r"^// BCG_PAYLOAD:(\{.*\})$", source, re.MULTILINE)
    if match:
        return json.loads(match.group(1))
    raise DiscoveryError("tester payload not found")


def cpp_compiler() -> str | None:
    return shutil.which("g++") or shutil.which("clang++")


def run_cpp_tester(
    tester: Path, solution_path: Path, env: dict[str, str], timeout: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    compiler = cpp_compiler()
    if compiler is None:
        return None
    with tempfile.TemporaryDirectory(prefix="bcg-cpp-") as temp_dir:
        binary = Path(temp_dir) / "runner"
        include_value = json.dumps(str(solution_path.resolve()))
        compile_command = [
            compiler,
            "-std=c++17",
            f"-DBCG_SOLUTION_INCLUDE={include_value}",
            str(tester),
            "-o",
            str(binary),
        ]
        compiled = subprocess.run(compile_command, text=True, capture_output=True, check=False, env=env, timeout=timeout)
        if compiled.returncode != 0:
            return None
        return subprocess.run([str(binary)], text=True, capture_output=True, check=False, env=env, timeout=timeout)


def run_rust_tester(
    tester: Path, solution_path: Path, env: dict[str, str], timeout: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    rustc = shutil.which("rustc")
    if rustc is None:
        return None
    with tempfile.TemporaryDirectory(prefix="bcg-rust-") as temp_dir:
        binary = Path(temp_dir) / "runner"
        compile_env = env.copy()
        compile_env["BCG_SOLUTION_PATH"] = str(solution_path.resolve())
        compile_command = [rustc, "--edition=2021", str(tester), "-o", str(binary)]
        compiled = subprocess.run(
            compile_command, text=True, capture_output=True, check=False, env=compile_env, timeout=timeout
        )
        if compiled.returncode != 0:
            return None
        return subprocess.run([str(binary)], text=True, capture_output=True, check=False, env=env, timeout=timeout)


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


def run_tester_process(
    lang: str, tester: Path, solution_path: Path, env: dict[str, str], timeout: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    if lang == "python":
        return subprocess.run(
            [sys.executable, str(tester), str(solution_path)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=timeout,
        )
    if lang in {"javascript", "typescript"}:
        return subprocess.run(
            ["node", str(tester), str(solution_path)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=timeout,
        )
    if lang == "cpp":
        return run_cpp_tester(tester, solution_path, env, timeout)
    if lang == "rust":
        return run_rust_tester(tester, solution_path, env, timeout)
    return None


def parse_runner_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    stdout = completed.stdout
    if stdout.count("\n") != 1:
        return None
    line = stdout.rstrip("\n")
    try:
        result = json.loads(line)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(result, dict)
        or list(result.keys()) != ["status", "passed", "failed"]
        or result.get("status") not in {"pass", "fail", "error"}
        or not isinstance(result.get("passed"), list)
        or not isinstance(result.get("failed"), list)
    ):
        return None
    return result


def run_filtered_tests(
    lang: str,
    entrypoint: str,
    tests: list[dict[str, Any]],
    solution_path: Path,
    env: dict[str, str],
    timeout_ms: int | None,
    total_timeout_ms: int | None,
) -> dict[str, Any]:
    filename = SUPPORTED_LANGS[lang]["tester"]
    per_test_timeout = timeout_ms / 1000 if timeout_ms is not None else None
    deadline = time.monotonic() + (total_timeout_ms / 1000) if total_timeout_ms is not None else None
    passed: list[str] = []
    failed: list[str] = []

    with tempfile.TemporaryDirectory(prefix="bcg-filter-") as temp_dir:
        temp_tester = Path(temp_dir) / filename
        for index, test in enumerate(tests):
            if deadline is not None and time.monotonic() >= deadline:
                failed.extend(item["id"] for item in tests[index:])
                break

            timeout = per_test_timeout
            total_wins = False
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
                if timeout is None or remaining <= timeout:
                    timeout = remaining
                    total_wins = True

            case = test_case_from_jsonable(test)
            temp_tester.write_text(tester_source(lang, entrypoint, [case]), encoding="utf-8")
            try:
                completed = run_tester_process(lang, temp_tester, solution_path, env, timeout)
            except subprocess.TimeoutExpired:
                failed.append(test["id"])
                if total_wins:
                    failed.extend(item["id"] for item in tests[index + 1 :])
                    break
                continue
            except Exception:
                return RESULT_ERROR
            if completed is None:
                return RESULT_ERROR

            result = parse_runner_result(completed)
            if result is None or result["status"] == "error":
                return RESULT_ERROR
            reported = result["passed"] + result["failed"]
            if reported != [test["id"]]:
                return RESULT_ERROR
            if result["passed"]:
                passed.append(test["id"])
            else:
                failed.append(test["id"])

    return make_result("pass" if not failed else "fail", passed, failed)


def command_test(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED_LANGS:
        return print_result(RESULT_ERROR)
    if args.list_tests and args.run_id is not None:
        return print_result(RESULT_ERROR)
    if args.timeout_ms is not None and args.timeout_ms <= 0:
        return print_result(RESULT_ERROR)
    if args.total_timeout_ms is not None and args.total_timeout_ms <= 0:
        return print_result(RESULT_ERROR)
    tests_dir = Path(args.tests_dir)
    tester = tests_dir / SUPPORTED_LANGS[args.lang]["tester"]
    if not tester.exists():
        return print_result(RESULT_ERROR)
    try:
        payload = extract_tester_payload(tester, args.lang)
        discovered = [test.to_jsonable() for test in discover_tests(tests_dir, payload["entrypoint"])]
        if discovered != payload["tests"]:
            return print_result(RESULT_ERROR)
    except Exception:
        return print_result(RESULT_ERROR)
    discovered_ids = [test["id"] for test in discovered]
    if args.list_tests:
        return print_result(make_result("pass", discovered_ids, []))
    selected_tests = discovered
    if args.run_id is not None:
        selected_tests = [test for test in discovered if test["id"] == args.run_id]
        if not selected_tests:
            return print_result(RESULT_ERROR)
    try:
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent)
        env["BABEL_CODE_GOAT_ROOT"] = root
        env["BABEL_CODE_GOAT_TOL"] = str(args.tol)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        solution_path = Path(args.solution_path)
        if args.run_id is not None or args.timeout_ms is not None or args.total_timeout_ms is not None:
            result = run_filtered_tests(
                args.lang,
                payload["entrypoint"],
                selected_tests,
                solution_path,
                env,
                args.timeout_ms,
                args.total_timeout_ms,
            )
            return print_result(result)
        if args.lang in SUPPORTED_LANGS:
            completed = run_tester_process(args.lang, tester, solution_path, env)
        else:
            completed = None
    except Exception:
        return print_result(RESULT_ERROR)
    if completed is None:
        return print_result(RESULT_ERROR)

    result = parse_runner_result(completed)
    if result is None:
        return print_result(RESULT_ERROR)
    return print_result(result)


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
    test.add_argument("--run", dest="run_id")
    test.add_argument("--timeout-ms", type=int)
    test.add_argument("--total-timeout-ms", type=int)
    test.set_defaults(func=command_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
