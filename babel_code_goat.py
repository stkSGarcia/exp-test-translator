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
import resource
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
    source: str = "tests.py"
    expected: Any = None
    tolerance: dict[str, Any] | None = None
    expected_exception: str | None = None
    message_match: dict[str, str] | None = None
    expression: dict[str, Any] | None = None
    mutation_vars: dict[str, int] | None = None
    mutation_result: str | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    in_loop: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "line": self.line,
            "kind": self.kind,
            "args": self.args,
            "expected": self.expected,
            "tolerance": self.tolerance,
            "expected_exception": self.expected_exception,
            "message_match": self.message_match,
            "expression": self.expression,
            "mutation_vars": self.mutation_vars,
            "mutation_result": self.mutation_result,
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


def variable_expression(name: str) -> ExpressionBuild:
    return ExpressionBuild({"op": "var", "name": name}, None, 1)


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


def mutation_expression_from_node(node: ast.AST, entrypoint: str, context: DiscoveryContext, variables: set[str]) -> ExpressionBuild:
    if entrypoint_call_count(node, entrypoint):
        raise DiscoveryError("mutation assert must not call entrypoint")

    if isinstance(node, ast.Name):
        if node.id in variables:
            return variable_expression(node.id)
        return const_expression(node, context)

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = mutation_expression_from_node(node.args[0], entrypoint, context, variables)
            return ExpressionBuild(
                {"op": "call", "function": callee, "args": [operand.expression]},
                None,
                operand.call_count,
            )
        return const_expression(node, context)

    if isinstance(node, ast.Constant | ast.List | ast.Tuple | ast.Set | ast.Dict):
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
        operand = mutation_expression_from_node(node.operand, entrypoint, context, variables)
        return ExpressionBuild(
            {"op": "unary", "operator": operator, "operand": operand.expression},
            None,
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
        left = mutation_expression_from_node(node.left, entrypoint, context, variables)
        right = mutation_expression_from_node(node.right, entrypoint, context, variables)
        return ExpressionBuild(
            {"op": "binary", "operator": operator, "left": left.expression, "right": right.expression},
            None,
            left.call_count + right.call_count,
        )

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            operator = "and"
        elif isinstance(node.op, ast.Or):
            operator = "or"
        else:
            raise DiscoveryError("unsupported boolean expression")
        values = [mutation_expression_from_node(value, entrypoint, context, variables) for value in node.values]
        return ExpressionBuild(
            {"op": "bool", "operator": operator, "values": [value.expression for value in values]},
            None,
            sum(value.call_count for value in values),
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
        left = mutation_expression_from_node(node.left, entrypoint, context, variables)
        right = mutation_expression_from_node(node.comparators[0], entrypoint, context, variables)
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression},
            None,
            left.call_count + right.call_count,
        )

    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = mutation_expression_from_node(node.value, entrypoint, context, variables)
        index = mutation_expression_from_node(node.slice, entrypoint, context, variables)
        return ExpressionBuild(
            {"op": "index", "value": value.expression, "index": index.expression},
            None,
            value.call_count + index.call_count,
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


def mutation_call_from_stmt(stmt: ast.stmt, entrypoint: str) -> tuple[ast.Call, str | None] | None:
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        if isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == entrypoint:
            return stmt.value, None
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1:
            return None
        if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == entrypoint:
            if not isinstance(stmt.targets[0], ast.Name):
                raise DiscoveryError("mutation assignment target must be a name")
            return stmt.value, stmt.targets[0].id
    return None


def mutation_call_args(
    call: ast.Call, assigned_name: str | None, context: DiscoveryContext
) -> tuple[list[Any], dict[str, int], set[str]]:
    if call.keywords:
        raise DiscoveryError("keyword arguments are unsupported")
    args: list[Any] = []
    mutation_vars: dict[str, int] = {}
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            expanded = value_from_node(arg.value, context)
            if not isinstance(expanded, list):
                raise DiscoveryError("starred arguments require iterable literal")
            args.extend(expanded)
            continue
        index = len(args)
        args.append(value_from_node(arg, context))
        if isinstance(arg, ast.Name):
            mutation_vars[arg.id] = index
    allowed = set(mutation_vars)
    if assigned_name is not None:
        allowed.add(assigned_name)
    return args, mutation_vars, allowed


def parse_mutation_assert(
    node: ast.Assert,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    args: list[Any],
    mutation_vars: dict[str, int],
    mutation_result: str | None,
    allowed_vars: set[str],
) -> TestCase:
    parsed = mutation_expression_from_node(node.test, entrypoint, context, allowed_vars)
    if parsed.call_count < 1:
        raise DiscoveryError("mutation assert must reference a mutated variable")
    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind="mutation",
        args=args,
        expression=parsed.expression,
        mutation_vars=mutation_vars,
        mutation_result=mutation_result,
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


def loop_case(node: ast.stmt, executed: bool) -> TestCase:
    return TestCase(id="", line=node.lineno, kind="loop", args=[], expected=executed)


def discover_for_loop(
    stmt: ast.For, entrypoint: str, lines: list[str], context: DiscoveryContext, in_loop: bool
) -> list[TestCase]:
    if stmt.orelse:
        raise DiscoveryError("unsupported loop else block")
    try:
        iterable = iterable_from_node(stmt.iter, context)
    except DiscoveryError:
        return [loop_case(stmt, False)]
    if not iterable:
        return [loop_case(stmt, False)]

    discovered = [loop_case(stmt, True)]
    for item in iterable:
        iteration_context = context.child()
        bind_target(stmt.target, item, iteration_context)
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, iteration_context, True))
    return discovered


def discover_while_loop(
    stmt: ast.While, entrypoint: str, lines: list[str], context: DiscoveryContext, in_loop: bool
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
            return [loop_case(stmt, False)]
        if not condition:
            return [loop_case(stmt, True), *discovered] if executed else [loop_case(stmt, False)]
        executed = True
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, working_context, True))

    return [loop_case(stmt, False)]


def discover_in_body(
    body: list[ast.stmt], entrypoint: str, lines: list[str], context: DiscoveryContext, in_loop: bool = False
) -> list[TestCase]:
    discovered: list[TestCase] = []
    index = 0
    while index < len(body):
        stmt = body[index]
        mutation_call = mutation_call_from_stmt(stmt, entrypoint)
        if mutation_call is not None:
            call, assigned_name = mutation_call
            args, mutation_vars, allowed_vars = mutation_call_args(call, assigned_name, context)
            mutation_asserts: list[ast.Assert] = []
            index += 1
            while index < len(body) and isinstance(body[index], ast.Assert):
                mutation_asserts.append(body[index])
                index += 1
            if not mutation_asserts:
                raise DiscoveryError("mutation call must be immediately followed by an assert")
            for assert_stmt in mutation_asserts:
                test_case = parse_mutation_assert(
                    assert_stmt,
                    entrypoint,
                    lines,
                    context,
                    args,
                    mutation_vars,
                    assigned_name,
                    allowed_vars,
                )
                discovered.append(
                    TestCase(
                        id=test_case.id,
                        line=test_case.line,
                        kind=test_case.kind,
                        args=test_case.args,
                        source=test_case.source,
                        expected=test_case.expected,
                        tolerance=test_case.tolerance,
                        expected_exception=test_case.expected_exception,
                        message_match=test_case.message_match,
                        expression=test_case.expression,
                        mutation_vars=test_case.mutation_vars,
                        mutation_result=test_case.mutation_result,
                        expect_stdout=test_case.expect_stdout,
                        expect_stderr=test_case.expect_stderr,
                        in_loop=in_loop,
                    )
                )
            continue
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context.child(), in_loop))
        elif isinstance(stmt, ast.Assert):
            test_case = parse_assert(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    source=test_case.source,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    mutation_vars=test_case.mutation_vars,
                    mutation_result=test_case.mutation_result,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
        elif isinstance(stmt, ast.Try):
            test_case = parse_raise_any(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    source=test_case.source,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    mutation_vars=test_case.mutation_vars,
                    mutation_result=test_case.mutation_result,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
        elif isinstance(stmt, ast.For):
            discovered.extend(discover_for_loop(stmt, entrypoint, lines, context, in_loop))
        elif isinstance(stmt, ast.While):
            discovered.extend(discover_while_loop(stmt, entrypoint, lines, context, in_loop))
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
            key = (test_case.source, test_case.line)
            counts[key] = counts.get(key, 0) + 1

    seen: dict[tuple[str, int], int] = {}
    loop_seen: dict[tuple[str, int], int] = {}
    assigned: list[TestCase] = []
    for test_case in test_cases:
        key = (test_case.source, test_case.line)
        if test_case.in_loop:
            line_seen = loop_seen.get(key, 0)
            loop_seen[key] = line_seen + 1
            test_id = f"{test_case.source}:{test_case.line}:{line_seen}"
        else:
            line_seen = seen.get(key, 0)
            seen[key] = line_seen + 1
            test_id = f"{test_case.source}:{test_case.line}"
            if counts.get(key, 0) > 1:
                test_id = f"{test_id}#{line_seen}"
        assigned.append(
            TestCase(
                id=test_id,
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                source=test_case.source,
                expected=test_case.expected,
                tolerance=test_case.tolerance,
                expected_exception=test_case.expected_exception,
                message_match=test_case.message_match,
                expression=test_case.expression,
                mutation_vars=test_case.mutation_vars,
                mutation_result=test_case.mutation_result,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=test_case.in_loop,
            )
        )
    return assigned


TEST_LIKE_RE = re.compile(r"^(test.*|.*_test|tests|.*_tests)\.[^.]+$")
GENERATED_TESTERS = {settings["tester"] for settings in SUPPORTED_LANGS.values()}


def relative_test_path(path: Path, tests_dir: Path) -> str:
    return path.relative_to(tests_dir).as_posix()


def is_test_like_non_python(path: Path) -> bool:
    return path.suffix != ".py" and bool(TEST_LIKE_RE.match(path.name))


def discover_test_files(tests_dir: Path) -> list[Path]:
    if not tests_dir.exists():
        raise DiscoveryError("tests directory does not exist")
    paths = [path for path in tests_dir.rglob("*") if path.is_file() and path.name not in GENERATED_TESTERS]
    for path in paths:
        if is_test_like_non_python(path):
            raise DiscoveryError("test-like non-Python file")
    return sorted(
        [path for path in paths if path.suffix == ".py"],
        key=lambda path: relative_test_path(path, tests_dir),
    )


def discover_tests_in_file(tests_path: Path, tests_dir: Path, entrypoint: str) -> list[TestCase]:
    relative_path = relative_test_path(tests_path, tests_dir)
    try:
        source = tests_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryError(f"could not read {relative_path}") from exc
    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        raise DiscoveryError(f"could not parse {relative_path}") from exc
    lines = source.splitlines()
    context = DiscoveryContext(names={}, values={})
    discovered = discover_in_body(tree.body, entrypoint, lines, context)
    return [
        TestCase(
            id=test.id,
            line=test.line,
            kind=test.kind,
            args=test.args,
            source=relative_path,
            expected=test.expected,
            tolerance=test.tolerance,
            expected_exception=test.expected_exception,
            message_match=test.message_match,
            expression=test.expression,
            mutation_vars=test.mutation_vars,
            mutation_result=test.mutation_result,
            expect_stdout=test.expect_stdout,
            expect_stderr=test.expect_stderr,
            in_loop=test.in_loop,
        )
        for test in discovered
    ]


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    discovered: list[TestCase] = []
    for tests_path in discover_test_files(tests_dir):
        discovered.extend(discover_tests_in_file(tests_path, tests_dir, entrypoint))
    if not discovered:
        raise DiscoveryError("no tests discovered")
    return assign_ids(discovered)


def make_result(status: str, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "passed": passed or [], "failed": failed or []}


def print_result(result: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return {"pass": 0, "fail": 1, "error": 2}[result["status"]]


def complete_python_value(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
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


def evaluate_expression(
    expression: dict[str, Any], actual: Any, tolerance: dict[str, Any], variables: dict[str, Any] | None = None
) -> Any:
    variables = variables or {}
    op = expression.get("op")
    if op == "const":
        return expression.get("value")
    if op == "actual":
        return actual
    if op == "var":
        return variables[expression["name"]]
    if op == "unary":
        operand = evaluate_expression(expression["operand"], actual, tolerance, variables)
        operator = expression.get("operator")
        if operator == "not":
            return not bool(operand)
        if operator == "neg":
            return -operand
        if operator == "pos":
            return +operand
    if op == "binary":
        left = evaluate_expression(expression["left"], actual, tolerance, variables)
        right = evaluate_expression(expression["right"], actual, tolerance, variables)
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
        values = [evaluate_expression(value, actual, tolerance, variables) for value in expression["values"]]
        if expression.get("operator") == "and":
            return all(bool(value) for value in values)
        if expression.get("operator") == "or":
            return any(bool(value) for value in values)
    if op == "compare":
        left = evaluate_expression(expression["left"], actual, tolerance, variables)
        right = evaluate_expression(expression["right"], actual, tolerance, variables)
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
        value = evaluate_expression(expression["value"], actual, tolerance, variables)
        index = evaluate_expression(expression["index"], actual, tolerance, variables)
        return expression_index(value, index)
    if op == "call":
        args = [evaluate_expression(arg, actual, tolerance, variables) for arg in expression["args"]]
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
                    decoded_args = [decode_arg(arg) for arg in test["args"]]
                    variables = {
                        name: decoded_args[index]
                        for name, index in (test.get("mutation_vars") or {}).items()
                    }
                    raised = False
                    raised_exc = None
                    try:
                        actual = complete_python_value(callable_under_test(*decoded_args))
                        if test.get("mutation_result"):
                            variables[test["mutation_result"]] = actual
                    except Exception as exc:
                        raised = True
                        raised_exc = exc
                        actual = None
                else:
                    raised = False
                    raised_exc = None
                    try:
                        actual = complete_python_value(callable_under_test(*[decode_arg(arg) for arg in test["args"]]))
                    except Exception as exc:
                        raised = True
                        raised_exc = exc
                        actual = None
                if test["kind"] == "loop":
                    pass
                elif test["kind"] == "mutation":
                    ok = not raised and bool(
                        evaluate_expression(
                            test["expression"],
                            actual,
                            tolerance_policy(test, default_tol),
                            variables,
                        )
                    )
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

function evaluateExpression(expression, actual, tolerance, variables) {{
  variables = variables || {{}};
  if (expression.op === "const") return expression.value;
  if (expression.op === "actual") return actual;
  if (expression.op === "var") return variables[expression.name];
  if (expression.op === "unary") {{
    const operand = evaluateExpression(expression.operand, actual, tolerance, variables);
    if (expression.operator === "not") return !operand;
    if (expression.operator === "neg") return -operand;
    if (expression.operator === "pos") return +operand;
  }}
  if (expression.op === "binary") {{
    const left = evaluateExpression(expression.left, actual, tolerance, variables);
    const right = evaluateExpression(expression.right, actual, tolerance, variables);
    if (expression.operator === "add") return left + right;
    if (expression.operator === "sub") return left - right;
    if (expression.operator === "mul") return left * right;
    if (expression.operator === "div") return left / right;
    if (expression.operator === "floordiv") return Math.floor(left / right);
    if (expression.operator === "mod") return left % right;
    if (expression.operator === "pow") return left ** right;
  }}
  if (expression.op === "bool") {{
    const values = expression.values.map(value => evaluateExpression(value, actual, tolerance, variables));
    if (expression.operator === "and") return values.every(Boolean);
    if (expression.operator === "or") return values.some(Boolean);
  }}
  if (expression.op === "compare") {{
    const left = evaluateExpression(expression.left, actual, tolerance, variables);
    const right = evaluateExpression(expression.right, actual, tolerance, variables);
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
    return expressionIndex(evaluateExpression(expression.value, actual, tolerance, variables), evaluateExpression(expression.index, actual, tolerance, variables));
  }}
  if (expression.op === "call") {{
    const args = expression.args.map(arg => evaluateExpression(arg, actual, tolerance, variables));
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
      let variables = {{}};
      if (test.kind === "loop") {{
        ok = !!test.expected;
      }} else if (test.kind === "mutation") {{
        const decodedArgs = test.args.map(decodeArg);
        for (const [name, index] of Object.entries(test.mutation_vars || {{}})) variables[name] = decodedArgs[index];
        try {{
          actual = fn(...decodedArgs);
          if (actual && typeof actual.then === "function") actual = await actual;
          if (test.mutation_result) variables[test.mutation_result] = actual;
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
      else if (test.kind === "mutation") ok = !raised && !!evaluateExpression(test.expression, actual, tolerancePolicy(test), variables);
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


def native_payload(entrypoint: str, tests: list[TestCase]) -> str:
    return json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )


def merge_native_type(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left["kind"] == "unknown":
        return right
    if right["kind"] == "unknown":
        return left
    if left["kind"] == "optional" or right["kind"] == "optional":
        left_inner = left["item"] if left["kind"] == "optional" else left
        right_inner = right["item"] if right["kind"] == "optional" else right
        return {"kind": "optional", "item": merge_native_type(left_inner, right_inner)}
    if left["kind"] == right["kind"]:
        if left["kind"] in {"list", "set"}:
            return {"kind": left["kind"], "item": merge_native_type(left["item"], right["item"])}
        if left["kind"] == "map":
            return {
                "kind": "map",
                "key": merge_native_type(left["key"], right["key"]),
                "value": merge_native_type(left["value"], right["value"]),
            }
        return left
    if {left["kind"], right["kind"]} <= {"int", "float"}:
        return {"kind": "float"}
    return {"kind": "value"}


def infer_native_type(value: Any) -> dict[str, Any]:
    if value is None:
        return {"kind": "optional", "item": {"kind": "unknown"}}
    if isinstance(value, bool):
        return {"kind": "bool"}
    if isinstance(value, int):
        return {"kind": "int"}
    if isinstance(value, float):
        return {"kind": "float"}
    if isinstance(value, str):
        return {"kind": "string"}
    if isinstance(value, list):
        item_type = {"kind": "unknown"}
        for item in value:
            item_type = merge_native_type(item_type, infer_native_type(item))
        return {"kind": "list", "item": finalize_native_type(item_type)}
    if is_tagged(value, "decimal"):
        return {"kind": "float"}
    if is_tagged(value, "set") or is_tagged(value, "deque"):
        item_type = {"kind": "unknown"}
        for item in value["items"]:
            item_type = merge_native_type(item_type, infer_native_type(item))
        return {"kind": "set" if is_tagged(value, "set") else "list", "item": finalize_native_type(item_type)}
    if is_tagged(value, "counter"):
        key_type = {"kind": "unknown"}
        for key, _count in value["items"]:
            key_type = merge_native_type(key_type, infer_native_type(key))
        return {"kind": "map", "key": finalize_native_type(key_type), "value": {"kind": "int"}}
    if is_tagged(value, "dict"):
        key_type = {"kind": "unknown"}
        value_type = {"kind": "unknown"}
        for key, item in value["items"]:
            key_type = merge_native_type(key_type, infer_native_type(key))
            value_type = merge_native_type(value_type, infer_native_type(item))
        return {
            "kind": "map",
            "key": finalize_native_type(key_type),
            "value": finalize_native_type(value_type),
        }
    return {"kind": "value"}


def finalize_native_type(type_info: dict[str, Any]) -> dict[str, Any]:
    if type_info["kind"] == "unknown":
        return {"kind": "int"}
    if type_info["kind"] == "optional":
        return {"kind": "optional", "item": finalize_native_type(type_info["item"])}
    if type_info["kind"] in {"list", "set"}:
        return {"kind": type_info["kind"], "item": finalize_native_type(type_info["item"])}
    if type_info["kind"] == "map":
        return {
            "kind": "map",
            "key": finalize_native_type(type_info["key"]),
            "value": finalize_native_type(type_info["value"]),
        }
    return type_info


def cpp_type(type_info: dict[str, Any]) -> str:
    kind = type_info["kind"]
    if kind == "bool":
        return "bool"
    if kind == "int":
        return "int"
    if kind == "float":
        return "long double"
    if kind == "string":
        return "std::string"
    if kind == "list":
        return f"std::vector<{cpp_type(type_info['item'])}>"
    if kind == "set":
        return f"std::set<{cpp_type(type_info['item'])}>"
    if kind == "map":
        return f"std::map<{cpp_type(type_info['key'])}, {cpp_type(type_info['value'])}>"
    if kind == "optional":
        return f"std::optional<{cpp_type(type_info['item'])}>"
    return "BcgValue"


def render_cpp_value(value: Any, type_info: dict[str, Any] | None = None) -> str:
    type_info = finalize_native_type(type_info or infer_native_type(value))
    if type_info["kind"] == "optional":
        inner = type_info["item"]
        optional_type = cpp_type(type_info)
        if value is None:
            return f"{optional_type}{{std::nullopt}}"
        return f"{optional_type}{{{render_cpp_value(value, inner)}}}"
    if value is None:
        return "std::optional<int>{std::nullopt}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{repr(value)}L"
    if isinstance(value, str):
        return f"std::string{{{json.dumps(value)}}}"
    if isinstance(value, list):
        item_type = type_info["item"] if type_info["kind"] == "list" else finalize_native_type({"kind": "unknown"})
        return f"{cpp_type({'kind': 'list', 'item': item_type})}{{{', '.join(render_cpp_value(item, item_type) for item in value)}}}"
    if is_tagged(value, "decimal"):
        return f"{value['value']}L"
    if is_tagged(value, "set"):
        item_type = type_info["item"] if type_info["kind"] == "set" else finalize_native_type({"kind": "unknown"})
        return f"{cpp_type({'kind': 'set', 'item': item_type})}{{{', '.join(render_cpp_value(item, item_type) for item in value['items'])}}}"
    if is_tagged(value, "deque"):
        item_type = type_info["item"] if type_info["kind"] == "list" else finalize_native_type({"kind": "unknown"})
        return f"{cpp_type({'kind': 'list', 'item': item_type})}{{{', '.join(render_cpp_value(item, item_type) for item in value['items'])}}}"
    if is_tagged(value, "counter") or is_tagged(value, "dict"):
        if type_info["kind"] == "map":
            key_type = type_info["key"]
            value_type = type_info["value"]
        else:
            key_type = value_type = finalize_native_type({"kind": "unknown"})
        items = ", ".join(
            f"{{{render_cpp_value(key, key_type)}, {render_cpp_value(item, value_type)}}}"
            for key, item in value["items"]
        )
        return f"{cpp_type({'kind': 'map', 'key': key_type, 'value': value_type})}{{{items}}}"
    return "BcgValue{}"


def cpp_bcg_literal(value: Any) -> str:
    if value is None:
        return "BcgValue::null()"
    if isinstance(value, bool):
        return f"BcgValue::boolean({'true' if value else 'false'})"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"BcgValue::number({repr(value)}L)"
    if isinstance(value, str):
        return f"BcgValue::string({json.dumps(value)})"
    if isinstance(value, list):
        return f"BcgValue::list({{{', '.join(cpp_bcg_literal(item) for item in value)}}})"
    if is_tagged(value, "decimal"):
        return f"BcgValue::number({value['value']}L)"
    if is_tagged(value, "set"):
        return f"BcgValue::set({{{', '.join(cpp_bcg_literal(item) for item in value['items'])}}})"
    if is_tagged(value, "counter"):
        return f"BcgValue::counter({{{', '.join(f'{{{cpp_bcg_literal(key)}, {cpp_bcg_literal(count)}}}' for key, count in value['items'])}}})"
    if is_tagged(value, "deque"):
        return f"BcgValue::deque({{{', '.join(cpp_bcg_literal(item) for item in value['items'])}}})"
    if is_tagged(value, "dict"):
        return f"BcgValue::dict({{{', '.join(f'{{{cpp_bcg_literal(key)}, {cpp_bcg_literal(item)}}}' for key, item in value['items'])}}})"
    return "BcgValue::null()"


def cpp_expr_value(expression: dict[str, Any], actual: str = "actual_value", variables: str = "variables") -> str:
    op = expression.get("op")
    if op == "const":
        return cpp_bcg_literal(expression.get("value"))
    if op == "actual":
        return actual
    if op == "var":
        return f'{variables}.at({json.dumps(expression["name"])})'
    if op == "unary":
        return f'bcg_unary({json.dumps(expression["operator"])}, {cpp_expr_value(expression["operand"], actual, variables)})'
    if op == "binary":
        return (
            f'bcg_binary({json.dumps(expression["operator"])}, '
            f'{cpp_expr_value(expression["left"], actual, variables)}, '
            f'{cpp_expr_value(expression["right"], actual, variables)})'
        )
    if op == "bool":
        rendered = ", ".join(cpp_expr_value(value, actual, variables) for value in expression["values"])
        return f'bcg_bool({json.dumps(expression["operator"])}, {{{rendered}}})'
    if op == "compare":
        return (
            f'BcgValue::boolean(bcg_compare_expr({json.dumps(expression["operator"])}, '
            f'{cpp_expr_value(expression["left"], actual, variables)}, '
            f'{cpp_expr_value(expression["right"], actual, variables)}, tolerance))'
        )
    if op == "index":
        return (
            f'bcg_index({cpp_expr_value(expression["value"], actual, variables)}, '
            f'{cpp_expr_value(expression["index"], actual, variables)})'
        )
    if op == "call":
        args = ", ".join(cpp_expr_value(arg, actual, variables) for arg in expression["args"])
        return f'bcg_call({json.dumps(expression["function"])}, {{{args}}})'
    return "BcgValue::null()"


def cpp_message_check(matcher: dict[str, str] | None, message_expr: str) -> str:
    if not matcher:
        return "true"
    pattern = json.dumps(matcher.get("pattern", ""))
    if matcher.get("mode") == "contains":
        return f"{message_expr}.find({pattern}) != std::string::npos"
    if matcher.get("mode") == "regex":
        return f"std::regex_search({message_expr}, std::regex({pattern}))"
    return "false"


def cpp_test_block(entrypoint: str, test: dict[str, Any], index: int) -> str:
    test_id = json.dumps(test["id"])
    expect_stdout = test.get("expect_stdout")
    expect_stderr = test.get("expect_stderr")
    stdout_check = "true" if expect_stdout is None else f"stdout_capture.str() == {json.dumps(expect_stdout)}"
    stderr_check = "true" if expect_stderr is None else f"stderr_capture.str() == {json.dumps(expect_stderr)}"
    tolerance = json.dumps(tolerance_policy(test, 0.0), separators=(",", ":"))
    args = test.get("args") or []
    arg_decls = []
    arg_names = []
    for arg_index, arg in enumerate(args):
        type_info = finalize_native_type(infer_native_type(arg))
        name = f"arg_{index}_{arg_index}"
        arg_decls.append(f"    auto {name} = {render_cpp_value(arg, type_info)};")
        arg_names.append(name)
    call = f"{entrypoint}({', '.join(arg_names)})"
    body: list[str] = [
        "  {",
        f"    const std::string test_id = {test_id};",
        f"    BcgTolerance tolerance = bcg_tolerance_from_json({json.dumps(tolerance)});",
        "    std::ostringstream stdout_capture;",
        "    std::ostringstream stderr_capture;",
        "    auto* old_stdout = std::cout.rdbuf(stdout_capture.rdbuf());",
        "    auto* old_stderr = std::cerr.rdbuf(stderr_capture.rdbuf());",
        "    bool ok = false;",
        *arg_decls,
        "    try {",
    ]
    if test["kind"] == "loop":
        body.append(f"      ok = {'true' if test.get('expected') else 'false'};")
    elif test["kind"] == "raises":
        message_check = cpp_message_check(test.get("message_match"), "message")
        body.extend(
            [
                f"      try {{ bcg_await({call}); }}",
                "      catch (const std::exception& exc) {",
                "        std::string message = exc.what();",
                f"        ok = {message_check};",
                "      }",
                "      catch (...) { ok = false; }",
            ]
        )
    elif test["kind"] == "mutation":
        mutation_result = test.get("mutation_result")
        if mutation_result:
            body.append(f"      auto mutation_result = bcg_await({call});")
        else:
            body.append(f"      bcg_await({call});")
        body.append("      std::map<std::string, BcgValue> variables;")
        for name, arg_index in (test.get("mutation_vars") or {}).items():
            body.append(f"      variables[{json.dumps(name)}] = bcg_normalize(arg_{index}_{arg_index});")
        if mutation_result:
            body.append(f"      variables[{json.dumps(mutation_result)}] = bcg_normalize(mutation_result);")
        body.append(f"      ok = bcg_truthy({cpp_expr_value(test['expression'])});")
    else:
        body.append(f"      auto actual = bcg_await({call});")
        body.append("      BcgValue actual_value = bcg_normalize(actual);")
        if test["kind"] == "expr":
            body.append(f"      ok = bcg_truthy({cpp_expr_value(test['expression'])});")
        elif test["kind"] == "eq":
            body.append(f"      ok = bcg_deep_equal({cpp_bcg_literal(test.get('expected'))}, actual_value, tolerance);")
        elif test["kind"] == "neq":
            body.append(f"      ok = !bcg_deep_equal({cpp_bcg_literal(test.get('expected'))}, actual_value, tolerance);")
        elif test["kind"] == "truthy":
            body.append("      ok = bcg_truthy(actual_value);")
        elif test["kind"] == "falsy":
            body.append("      ok = !bcg_truthy(actual_value);")
    body.extend(
        [
            "    } catch (...) {",
            "      ok = false;",
            "    }",
            "    std::cout.rdbuf(old_stdout);",
            "    std::cerr.rdbuf(old_stderr);",
            f"    if (!({stdout_check}) || !({stderr_check})) ok = false;",
            "    (ok ? passed : failed).push_back(test_id);",
            "  }",
        ]
    )
    return "\n".join(body)


def cpp_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = native_payload(entrypoint, tests)
    test_dicts = [test.to_jsonable() for test in tests]
    blocks = "\n".join(cpp_test_block(entrypoint, test, index) for index, test in enumerate(test_dicts))
    return f"""// BCG_PAYLOAD: {payload}
#include <algorithm>
#include <cmath>
#include <deque>
#include <future>
#include <iomanip>
#include <iostream>
#include <map>
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

#ifndef BCG_SOLUTION_PATH
#error "BCG_SOLUTION_PATH is required"
#endif
#include BCG_SOLUTION_PATH

struct BcgTolerance {{
  std::string mode = "default";
  long double abs = 0.0L;
  long double rel = 0.0L;
  bool strict = false;
}};

struct BcgValue {{
  enum class Kind {{ Null, Bool, Number, String, List, Dict, Set, Counter, Deque }};
  Kind kind = Kind::Null;
  bool bool_value = false;
  long double number_value = 0.0L;
  std::string string_value;
  std::vector<BcgValue> items;
  std::vector<std::pair<BcgValue, BcgValue>> pairs;

  static BcgValue null() {{ return BcgValue{{}}; }}
  static BcgValue boolean(bool value) {{ BcgValue out; out.kind = Kind::Bool; out.bool_value = value; return out; }}
  static BcgValue number(long double value) {{ BcgValue out; out.kind = Kind::Number; out.number_value = value; return out; }}
  static BcgValue string(std::string value) {{ BcgValue out; out.kind = Kind::String; out.string_value = std::move(value); return out; }}
  static BcgValue list(std::initializer_list<BcgValue> values) {{ BcgValue out; out.kind = Kind::List; out.items = values; return out; }}
  static BcgValue set(std::initializer_list<BcgValue> values) {{ BcgValue out; out.kind = Kind::Set; out.items = values; return out; }}
  static BcgValue deque(std::initializer_list<BcgValue> values) {{ BcgValue out; out.kind = Kind::Deque; out.items = values; return out; }}
  static BcgValue dict(std::initializer_list<std::pair<BcgValue, BcgValue>> values) {{ BcgValue out; out.kind = Kind::Dict; out.pairs = values; return out; }}
  static BcgValue counter(std::initializer_list<std::pair<BcgValue, BcgValue>> values) {{ BcgValue out; out.kind = Kind::Counter; out.pairs = values; return out; }}
}};

std::string bcg_stable(const BcgValue& value);

bool operator<(const BcgValue& left, const BcgValue& right) {{
  return bcg_stable(left) < bcg_stable(right);
}}

BcgTolerance bcg_tolerance_from_json(const std::string& raw) {{
  BcgTolerance tolerance;
  if (raw.find("\\\"mode\\\":\\\"isclose\\\"") != std::string::npos) tolerance.mode = "isclose";
  if (raw.find("\\\"mode\\\":\\\"absdiff\\\"") != std::string::npos) tolerance.mode = "absdiff";
  tolerance.strict = raw.find("\\\"strict\\\":true") != std::string::npos;
  std::regex number_re("\\\"(abs|rel)\\\":(-?[0-9]+(?:\\\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)");
  for (auto it = std::sregex_iterator(raw.begin(), raw.end(), number_re); it != std::sregex_iterator(); ++it) {{
    long double value = std::stold((*it)[2].str());
    if ((*it)[1].str() == "abs") tolerance.abs = value;
    if ((*it)[1].str() == "rel") tolerance.rel = value;
  }}
  const char* env_tol = std::getenv("BABEL_CODE_GOAT_TOL");
  if (tolerance.mode == "default" && env_tol != nullptr) tolerance.abs = std::stold(env_tol);
  return tolerance;
}}

std::string bcg_stable(const BcgValue& value) {{
  std::ostringstream out;
  out << static_cast<int>(value.kind) << ":";
  if (value.kind == BcgValue::Kind::Bool) out << (value.bool_value ? "true" : "false");
  else if (value.kind == BcgValue::Kind::Number) out << std::setprecision(30) << value.number_value;
  else if (value.kind == BcgValue::Kind::String) out << value.string_value;
  else if (value.kind == BcgValue::Kind::List || value.kind == BcgValue::Kind::Set || value.kind == BcgValue::Kind::Deque) {{
    for (const auto& item : value.items) out << "[" << bcg_stable(item) << "]";
  }} else if (value.kind == BcgValue::Kind::Dict || value.kind == BcgValue::Kind::Counter) {{
    for (const auto& pair : value.pairs) out << "{{" << bcg_stable(pair.first) << ":" << bcg_stable(pair.second) << "}}";
  }}
  return out.str();
}}

BcgValue bcg_normalize(const BcgValue& value) {{ return value; }}
BcgValue bcg_normalize(std::nullptr_t) {{ return BcgValue::null(); }}
BcgValue bcg_normalize(bool value) {{ return BcgValue::boolean(value); }}
BcgValue bcg_normalize(const std::string& value) {{ return BcgValue::string(value); }}
BcgValue bcg_normalize(const char* value) {{ return BcgValue::string(value == nullptr ? "" : value); }}

template <typename T>
T bcg_await(T value) {{ return value; }}

template <typename T>
T bcg_await(std::future<T> value) {{ return value.get(); }}

template <typename T>
T bcg_await(std::shared_future<T> value) {{ return value.get(); }}

template <typename T, typename = std::enable_if_t<std::is_integral_v<T> && !std::is_same_v<T, bool>>>
BcgValue bcg_normalize(T value) {{ return BcgValue::number(static_cast<long double>(value)); }}

template <typename T, typename = std::enable_if_t<std::is_floating_point_v<T>>, typename = void>
BcgValue bcg_normalize(T value) {{ return BcgValue::number(static_cast<long double>(value)); }}

template <typename T>
BcgValue bcg_normalize(const std::optional<T>& value) {{
  if (!value.has_value()) return BcgValue::null();
  return bcg_normalize(*value);
}}

template <typename T>
BcgValue bcg_normalize(const std::vector<T>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::List;
  for (const auto& item : values) out.items.push_back(bcg_normalize(item));
  return out;
}}

template <typename T>
BcgValue bcg_normalize(const std::deque<T>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::Deque;
  for (const auto& item : values) out.items.push_back(bcg_normalize(item));
  return out;
}}

template <typename T>
BcgValue bcg_normalize(const std::set<T>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::Set;
  for (const auto& item : values) out.items.push_back(bcg_normalize(item));
  std::sort(out.items.begin(), out.items.end());
  return out;
}}

template <typename T>
BcgValue bcg_normalize(const std::unordered_set<T>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::Set;
  for (const auto& item : values) out.items.push_back(bcg_normalize(item));
  std::sort(out.items.begin(), out.items.end());
  return out;
}}

template <typename K, typename V>
BcgValue bcg_normalize(const std::map<K, V>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::Dict;
  for (const auto& pair : values) out.pairs.push_back({{bcg_normalize(pair.first), bcg_normalize(pair.second)}});
  return out;
}}

template <typename K, typename V>
BcgValue bcg_normalize(const std::unordered_map<K, V>& values) {{
  BcgValue out; out.kind = BcgValue::Kind::Dict;
  for (const auto& pair : values) out.pairs.push_back({{bcg_normalize(pair.first), bcg_normalize(pair.second)}});
  std::sort(out.pairs.begin(), out.pairs.end(), [](const auto& a, const auto& b) {{ return bcg_stable(a.first) < bcg_stable(b.first); }});
  return out;
}}

bool bcg_numeric_equal(const BcgValue& expected, const BcgValue& actual, const BcgTolerance& tolerance) {{
  if (expected.kind != BcgValue::Kind::Number || actual.kind != BcgValue::Kind::Number) return false;
  long double diff = std::fabs(actual.number_value - expected.number_value);
  if (tolerance.mode == "absdiff" && tolerance.strict) return diff < tolerance.abs;
  long double limit = std::max(tolerance.abs, tolerance.rel * std::max(std::fabs(actual.number_value), std::fabs(expected.number_value)));
  return diff <= limit;
}}

bool bcg_deep_equal(const BcgValue& expected, const BcgValue& actual, const BcgTolerance& tolerance);

bool bcg_compare_unordered(const std::vector<BcgValue>& expected, const std::vector<BcgValue>& actual, const BcgTolerance& tolerance) {{
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  for (const auto& expected_item : expected) {{
    bool matched = false;
    for (std::size_t i = 0; i < actual.size(); ++i) {{
      if (!used[i] && bcg_deep_equal(expected_item, actual[i], tolerance)) {{
        used[i] = true;
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

bool bcg_compare_pairs(const std::vector<std::pair<BcgValue, BcgValue>>& expected, const std::vector<std::pair<BcgValue, BcgValue>>& actual, const BcgTolerance& tolerance) {{
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  BcgTolerance exact;
  for (const auto& expected_pair : expected) {{
    bool matched = false;
    for (std::size_t i = 0; i < actual.size(); ++i) {{
      if (!used[i] && bcg_deep_equal(expected_pair.first, actual[i].first, exact) && bcg_deep_equal(expected_pair.second, actual[i].second, tolerance)) {{
        used[i] = true;
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

bool bcg_deep_equal(const BcgValue& expected, const BcgValue& actual, const BcgTolerance& tolerance) {{
  if (expected.kind == BcgValue::Kind::Number && actual.kind == BcgValue::Kind::Number) return bcg_numeric_equal(expected, actual, tolerance);
  if (expected.kind != actual.kind) return false;
  if (expected.kind == BcgValue::Kind::Null) return true;
  if (expected.kind == BcgValue::Kind::Bool) return expected.bool_value == actual.bool_value;
  if (expected.kind == BcgValue::Kind::String) return expected.string_value == actual.string_value;
  if (expected.kind == BcgValue::Kind::List || expected.kind == BcgValue::Kind::Deque) {{
    if (expected.items.size() != actual.items.size()) return false;
    for (std::size_t i = 0; i < expected.items.size(); ++i) if (!bcg_deep_equal(expected.items[i], actual.items[i], tolerance)) return false;
    return true;
  }}
  if (expected.kind == BcgValue::Kind::Set) return bcg_compare_unordered(expected.items, actual.items, tolerance);
  if (expected.kind == BcgValue::Kind::Dict || expected.kind == BcgValue::Kind::Counter) return bcg_compare_pairs(expected.pairs, actual.pairs, tolerance);
  return false;
}}

bool bcg_truthy(const BcgValue& value) {{
  if (value.kind == BcgValue::Kind::Null) return false;
  if (value.kind == BcgValue::Kind::Bool) return value.bool_value;
  if (value.kind == BcgValue::Kind::Number) return value.number_value != 0.0L;
  if (value.kind == BcgValue::Kind::String) return !value.string_value.empty();
  if (value.kind == BcgValue::Kind::List || value.kind == BcgValue::Kind::Set || value.kind == BcgValue::Kind::Deque) return !value.items.empty();
  if (value.kind == BcgValue::Kind::Dict || value.kind == BcgValue::Kind::Counter) return !value.pairs.empty();
  return false;
}}

BcgValue bcg_unary(const std::string& op, const BcgValue& value) {{
  if (op == "not") return BcgValue::boolean(!bcg_truthy(value));
  if (op == "neg" && value.kind == BcgValue::Kind::Number) return BcgValue::number(-value.number_value);
  if (op == "pos" && value.kind == BcgValue::Kind::Number) return value;
  return BcgValue::null();
}}

BcgValue bcg_binary(const std::string& op, const BcgValue& left, const BcgValue& right) {{
  if (left.kind == BcgValue::Kind::Number && right.kind == BcgValue::Kind::Number) {{
    if (op == "add") return BcgValue::number(left.number_value + right.number_value);
    if (op == "sub") return BcgValue::number(left.number_value - right.number_value);
    if (op == "mul") return BcgValue::number(left.number_value * right.number_value);
    if (op == "div") return BcgValue::number(left.number_value / right.number_value);
    if (op == "floordiv") return BcgValue::number(std::floor(left.number_value / right.number_value));
    if (op == "mod") return BcgValue::number(std::fmod(left.number_value, right.number_value));
    if (op == "pow") return BcgValue::number(std::pow(left.number_value, right.number_value));
  }}
  if (op == "add" && left.kind == BcgValue::Kind::String && right.kind == BcgValue::Kind::String) return BcgValue::string(left.string_value + right.string_value);
  return BcgValue::null();
}}

BcgValue bcg_bool(const std::string& op, std::initializer_list<BcgValue> values) {{
  if (op == "and") {{
    for (const auto& value : values) if (!bcg_truthy(value)) return BcgValue::boolean(false);
    return BcgValue::boolean(true);
  }}
  if (op == "or") {{
    for (const auto& value : values) if (bcg_truthy(value)) return BcgValue::boolean(true);
    return BcgValue::boolean(false);
  }}
  return BcgValue::boolean(false);
}}

bool bcg_contains(const BcgValue& container, const BcgValue& needle, const BcgTolerance& tolerance) {{
  if (container.kind == BcgValue::Kind::String && needle.kind == BcgValue::Kind::String) return container.string_value.find(needle.string_value) != std::string::npos;
  if (container.kind == BcgValue::Kind::Dict || container.kind == BcgValue::Kind::Counter) {{
    BcgTolerance exact;
    for (const auto& pair : container.pairs) if (bcg_deep_equal(pair.first, needle, exact)) return true;
    return false;
  }}
  if (container.kind == BcgValue::Kind::List || container.kind == BcgValue::Kind::Set || container.kind == BcgValue::Kind::Deque) {{
    for (const auto& item : container.items) if (bcg_deep_equal(item, needle, tolerance)) return true;
  }}
  return false;
}}

bool bcg_compare_expr(const std::string& op, const BcgValue& left, const BcgValue& right, const BcgTolerance& tolerance) {{
  if (op == "eq") return bcg_deep_equal(left, right, tolerance);
  if (op == "neq") return !bcg_deep_equal(left, right, tolerance);
  if (op == "in") return bcg_contains(right, left, tolerance);
  if (op == "not_in") return !bcg_contains(right, left, tolerance);
  if (left.kind == BcgValue::Kind::Number && right.kind == BcgValue::Kind::Number) {{
    if (op == "lt") return left.number_value < right.number_value;
    if (op == "lte") return left.number_value <= right.number_value;
    if (op == "gt") return left.number_value > right.number_value;
    if (op == "gte") return left.number_value >= right.number_value;
  }}
  if (op == "lt") return bcg_stable(left) < bcg_stable(right);
  if (op == "lte") return bcg_stable(left) <= bcg_stable(right);
  if (op == "gt") return bcg_stable(left) > bcg_stable(right);
  if (op == "gte") return bcg_stable(left) >= bcg_stable(right);
  return false;
}}

BcgValue bcg_index(const BcgValue& value, const BcgValue& index) {{
  int numeric_index = static_cast<int>(index.number_value);
  if ((value.kind == BcgValue::Kind::List || value.kind == BcgValue::Kind::Deque || value.kind == BcgValue::Kind::Set) && index.kind == BcgValue::Kind::Number) return value.items.at(numeric_index);
  if (value.kind == BcgValue::Kind::String && index.kind == BcgValue::Kind::Number) return BcgValue::string(std::string(1, value.string_value.at(numeric_index)));
  if (value.kind == BcgValue::Kind::Dict) {{
    BcgTolerance exact;
    for (const auto& pair : value.pairs) if (bcg_deep_equal(pair.first, index, exact)) return pair.second;
  }}
  throw std::out_of_range("missing index");
}}

BcgValue bcg_call(const std::string& function, std::initializer_list<BcgValue> args) {{
  const BcgValue& value = *args.begin();
  if (function == "abs" && value.kind == BcgValue::Kind::Number) return BcgValue::number(std::fabs(value.number_value));
  if (function == "sorted") {{
    BcgValue out = value;
    if (out.kind == BcgValue::Kind::String) {{
      out.kind = BcgValue::Kind::List;
      out.items.clear();
      for (char ch : value.string_value) out.items.push_back(BcgValue::string(std::string(1, ch)));
    }}
    std::sort(out.items.begin(), out.items.end());
    out.kind = BcgValue::Kind::List;
    return out;
  }}
  return BcgValue::null();
}}

int main() {{
  std::vector<std::string> passed;
  std::vector<std::string> failed;
{blocks}
  std::cout << "{{\\\"status\\\":\\\"" << (failed.empty() ? "pass" : "fail") << "\\\",\\\"passed\\\":[";
  for (std::size_t i = 0; i < passed.size(); ++i) {{ if (i) std::cout << ","; std::cout << "\\\"" << passed[i] << "\\\""; }}
  std::cout << "],\\\"failed\\\":[";
  for (std::size_t i = 0; i < failed.size(); ++i) {{ if (i) std::cout << ","; std::cout << "\\\"" << failed[i] << "\\\""; }}
  std::cout << "]}}" << std::endl;
  return failed.empty() ? 0 : 1;
}}
"""


def rust_type(type_info: dict[str, Any]) -> str:
    kind = type_info["kind"]
    if kind == "bool":
        return "bool"
    if kind == "int":
        return "i64"
    if kind == "float":
        return "f64"
    if kind == "string":
        return "String"
    if kind == "list":
        return f"Vec<{rust_type(type_info['item'])}>"
    if kind == "set":
        return f"std::collections::HashSet<{rust_type(type_info['item'])}>"
    if kind == "map":
        return f"std::collections::HashMap<{rust_type(type_info['key'])}, {rust_type(type_info['value'])}>"
    if kind == "optional":
        return f"Option<{rust_type(type_info['item'])}>"
    return "()"


def render_rust_value(value: Any, type_info: dict[str, Any] | None = None) -> str:
    type_info = finalize_native_type(type_info or infer_native_type(value))
    if type_info["kind"] == "optional":
        if value is None:
            return f"None::<{rust_type(type_info['item'])}>"
        return f"Some({render_rust_value(value, type_info['item'])})"
    if value is None:
        return "None::<i64>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}_i64"
    if isinstance(value, float):
        return f"{repr(value)}_f64"
    if isinstance(value, str):
        return f"String::from({json.dumps(value)})"
    if isinstance(value, list):
        item_type = type_info["item"] if type_info["kind"] == "list" else finalize_native_type({"kind": "unknown"})
        return f"vec![{', '.join(render_rust_value(item, item_type) for item in value)}]"
    if is_tagged(value, "decimal"):
        return f"{value['value']}_f64"
    if is_tagged(value, "set"):
        item_type = type_info["item"] if type_info["kind"] == "set" else finalize_native_type({"kind": "unknown"})
        return f"std::collections::HashSet::from([{', '.join(render_rust_value(item, item_type) for item in value['items'])}])"
    if is_tagged(value, "deque"):
        item_type = type_info["item"] if type_info["kind"] == "list" else finalize_native_type({"kind": "unknown"})
        return f"vec![{', '.join(render_rust_value(item, item_type) for item in value['items'])}]"
    if is_tagged(value, "counter") or is_tagged(value, "dict"):
        key_type = type_info["key"] if type_info["kind"] == "map" else finalize_native_type({"kind": "unknown"})
        value_type = type_info["value"] if type_info["kind"] == "map" else finalize_native_type({"kind": "unknown"})
        pairs = ", ".join(
            f"({render_rust_value(key, key_type)}, {render_rust_value(item, value_type)})"
            for key, item in value["items"]
        )
        return f"std::collections::HashMap::from([{pairs}])"
    return "()"


def rust_expected_check(actual: str, expected: Any, tolerance: dict[str, Any]) -> str:
    if numeric_decimal(expected) is not None:
        abs_tol = tolerance.get("abs", 0.0)
        strict = "true" if tolerance.get("mode") == "absdiff" and tolerance.get("strict") else "false"
        return f"bcg_num_eq(({actual}) as f64, {float(numeric_decimal(expected))!r}_f64, {float(abs_tol)!r}_f64, {strict})"
    return f"{actual} == {render_rust_value(expected)}"


def rust_test_block(entrypoint: str, test: dict[str, Any], index: int) -> str:
    test_id = json.dumps(test["id"])
    args = ", ".join(render_rust_value(arg) for arg in test.get("args") or [])
    call = f"{entrypoint}({args})"
    lines = [f"    let mut ok_{index} = false;"]
    if test["kind"] == "loop":
        lines.append(f"    ok_{index} = {'true' if test.get('expected') else 'false'};")
    elif test["kind"] == "raises":
        matcher = test.get("message_match")
        if matcher and matcher.get("mode") == "contains":
            msg_check = f"message.contains({json.dumps(matcher.get('pattern', ''))})"
        else:
            msg_check = "true"
        lines.extend(
            [
                f"    let raised_{index} = std::panic::catch_unwind(|| {{ bcg_call!({call}); }});",
                f"    if let Err(payload) = raised_{index} {{",
                "        let message = if let Some(value) = payload.downcast_ref::<&str>() { value.to_string() } else if let Some(value) = payload.downcast_ref::<String>() { value.clone() } else { String::new() };",
                f"        ok_{index} = {msg_check};",
                "    }",
            ]
        )
    elif test["kind"] == "eq":
        lines.append(f"    let actual_{index} = bcg_call!({call});")
        lines.append(f"    ok_{index} = {rust_expected_check(f'actual_{index}', test.get('expected'), tolerance_policy(test, 0.0))};")
    elif test["kind"] == "neq":
        lines.append(f"    let actual_{index} = bcg_call!({call});")
        lines.append(f"    ok_{index} = !({rust_expected_check(f'actual_{index}', test.get('expected'), tolerance_policy(test, 0.0))});")
    elif test["kind"] == "truthy":
        lines.append(f"    ok_{index} = bool::from(bcg_call!({call}));")
    elif test["kind"] == "falsy":
        lines.append(f"    ok_{index} = !bool::from(bcg_call!({call}));")
    else:
        lines.append(f"    let _ = bcg_call!({call});")
        lines.append(f"    ok_{index} = true;")
    lines.append(f"    if ok_{index} {{ passed.push(String::from({test_id})); }} else {{ failed.push(String::from({test_id})); }}")
    return "\n".join(lines)


def rust_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = native_payload(entrypoint, tests)
    blocks = "\n".join(rust_test_block(entrypoint, test.to_jsonable(), index) for index, test in enumerate(tests))
    return f"""// BCG_PAYLOAD: {payload}
// Nullable values use Option<T>, Some(value), and None.
// HashMap<String, V> lookups use get_mut(String::from("items")) style owned-key helpers when mutation requires them.
#![allow(dead_code)]
#![allow(unused_imports)]
use std::collections::{{BTreeMap, HashMap, HashSet}};
use std::future::Future;
use std::pin::Pin;
use std::task::{{Context, Poll, RawWaker, RawWakerVTable, Waker}};
mod solution {{
    include!(env!("BCG_SOLUTION_PATH"));
}}
use solution::*;

fn bcg_num_eq(actual: f64, expected: f64, abs_tol: f64, strict: bool) -> bool {{
    let diff = (actual - expected).abs();
    if strict {{ diff < abs_tol }} else {{ diff <= abs_tol }}
}}

fn bcg_noop_raw_waker() -> RawWaker {{
    fn clone(_: *const ()) -> RawWaker {{ bcg_noop_raw_waker() }}
    fn noop(_: *const ()) {{}}
    static VTABLE: RawWakerVTable = RawWakerVTable::new(clone, noop, noop, noop);
    RawWaker::new(std::ptr::null(), &VTABLE)
}}

fn bcg_block_on<F: Future>(future: F) -> F::Output {{
    let waker = unsafe {{ Waker::from_raw(bcg_noop_raw_waker()) }};
    let mut context = Context::from_waker(&waker);
    let mut future = Box::pin(future);
    loop {{
        match Future::poll(Pin::as_mut(&mut future), &mut context) {{
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }}
    }}
}}

#[cfg(bcg_async_entrypoint)]
macro_rules! bcg_call {{
    ($expr:expr) => {{ bcg_block_on($expr) }};
}}

#[cfg(not(bcg_async_entrypoint))]
macro_rules! bcg_call {{
    ($expr:expr) => {{ $expr }};
}}

fn main() {{
    let _owned_lookup_marker = String::from("items");
    let mut passed: Vec<String> = Vec::new();
    let mut failed: Vec<String> = Vec::new();
{blocks}
    let status = if failed.is_empty() {{ "pass" }} else {{ "fail" }};
    let passed_json = passed.iter().map(|item| format!("\\\"{{}}\\\"", item)).collect::<Vec<_>>().join(",");
    let failed_json = failed.iter().map(|item| format!("\\\"{{}}\\\"", item)).collect::<Vec<_>>().join(",");
    println!("{{{{\\\"status\\\":\\\"{{}}\\\",\\\"passed\\\":[{{}}],\\\"failed\\\":[{{}}]}}}}", status, passed_json, failed_json);
    std::process::exit(if failed.is_empty() {{ 0 }} else {{ 1 }});
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
        raise DiscoveryError("unsupported language")

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
    elif lang in {"javascript", "typescript"}:
        match = re.search(r"const payload = (\{.*?\});", source, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    elif lang in {"cpp", "rust"}:
        match = re.search(r"^// BCG_PAYLOAD: (\{.*\})$", source, re.MULTILINE)
        if match:
            return json.loads(match.group(1))
    raise DiscoveryError("tester payload not found")


def rust_solution_uses_async_entrypoint(solution_path: Path, entrypoint: str) -> bool:
    try:
        source = solution_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"\basync\s+fn\s+{re.escape(entrypoint)}\b", source) is not None


def compiled_command(lang: str, tester: Path, solution_path: Path, output_path: Path) -> list[str] | None:
    if lang == "cpp":
        compiler = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
        if compiler is None:
            return None
        return [
            compiler,
            "-std=c++17",
            f'-DBCG_SOLUTION_PATH="{solution_path.resolve()}"',
            str(tester),
            "-o",
            str(output_path),
        ]
    if lang == "rust":
        compiler = shutil.which("rustc")
        if compiler is None:
            return None
        command = [compiler, "--edition=2021", str(tester), "-o", str(output_path)]
        try:
            payload = extract_tester_payload(tester, "rust")
        except Exception:
            payload = {}
        if rust_solution_uses_async_entrypoint(solution_path, str(payload.get("entrypoint", ""))):
            command[1:1] = ["--cfg", "bcg_async_entrypoint"]
        return command
    return None


def run_compiled_tester(
    lang: str, tester: Path, solution_path: Path, env: dict[str, str], timeout: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    with tempfile.TemporaryDirectory(prefix="babel-code-goat-") as temp_dir:
        output_path = Path(temp_dir) / ("tester.exe" if os.name == "nt" else "tester")
        compile_command = compiled_command(lang, tester, solution_path, output_path)
        if compile_command is None:
            return None
        compile_env = env.copy()
        compile_env["BCG_SOLUTION_PATH"] = str(solution_path.resolve())
        compiled = subprocess.run(compile_command, text=True, capture_output=True, check=False, env=compile_env)
        if compiled.returncode != 0:
            return None
        return subprocess.run([str(output_path)], text=True, capture_output=True, check=False, env=env, timeout=timeout)


@dataclass(frozen=True)
class TesterRun:
    completed: subprocess.CompletedProcess[str] | None = None
    timed_out: bool = False
    runtime_ns: int = 0
    memory_kb: int = 0


@dataclass(frozen=True)
class CommandContext:
    tests_dir: Path
    tester: Path
    payload: dict[str, Any]
    discovered: list[dict[str, Any]]
    in_scope: list[dict[str, Any]]
    env: dict[str, str]


def test_case_from_jsonable(test: dict[str, Any]) -> TestCase:
    return TestCase(
        id=test["id"],
        line=test["line"],
        kind=test["kind"],
        args=test.get("args") or [],
        expected=test.get("expected"),
        tolerance=test.get("tolerance"),
        expected_exception=test.get("expected_exception"),
        message_match=test.get("message_match"),
        expression=test.get("expression"),
        mutation_vars=test.get("mutation_vars"),
        mutation_result=test.get("mutation_result"),
        expect_stdout=test.get("expect_stdout"),
        expect_stderr=test.get("expect_stderr"),
    )


def tester_source_from_jsonable(lang: str, entrypoint: str, tests: list[dict[str, Any]]) -> str:
    test_cases = [test_case_from_jsonable(test) for test in tests]
    if lang == "python":
        return python_tester_source(entrypoint, test_cases)
    if lang in {"javascript", "typescript"}:
        return javascript_tester_source(entrypoint, test_cases)
    if lang == "cpp":
        return cpp_tester_source(entrypoint, test_cases)
    if lang == "rust":
        return rust_tester_source(entrypoint, test_cases)
    raise DiscoveryError("unsupported language")


def write_scoped_tester(temp_dir: Path, lang: str, entrypoint: str, tests: list[dict[str, Any]]) -> Path:
    tester = temp_dir / SUPPORTED_LANGS[lang]["tester"]
    tester.write_text(tester_source_from_jsonable(lang, entrypoint, tests), encoding="utf-8")
    return tester


def run_tester_process(
    lang: str,
    tester: Path,
    solution_path: Path,
    env: dict[str, str],
    timeout: float | None = None,
) -> TesterRun:
    start_ns = time.perf_counter_ns()
    start_usage = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    try:
        if lang == "python":
            command = [sys.executable, str(tester), str(solution_path)]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout)
        elif lang in {"javascript", "typescript"}:
            command = ["node", str(tester), str(solution_path)]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout)
        else:
            completed = run_compiled_tester(lang, tester, solution_path, env, timeout=timeout)
        runtime_ns = time.perf_counter_ns() - start_ns
        memory_kb = max(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss - start_usage, 0)
        return TesterRun(completed=completed, runtime_ns=runtime_ns, memory_kb=memory_kb)
    except subprocess.TimeoutExpired:
        runtime_ns = time.perf_counter_ns() - start_ns
        memory_kb = max(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss - start_usage, 0)
        return TesterRun(timed_out=True, runtime_ns=runtime_ns, memory_kb=memory_kb)


def parse_tester_result(completed: subprocess.CompletedProcess[str] | None) -> dict[str, Any] | None:
    if completed is None:
        return None
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


def validate_scoped_result(result: dict[str, Any], expected_ids: list[str]) -> bool:
    reported = result["passed"] + result["failed"]
    return sorted(reported) == sorted(expected_ids) and len(reported) == len(set(reported))


def run_scoped_once(
    args: argparse.Namespace,
    entrypoint: str,
    tests: list[dict[str, Any]],
    tester: Path,
    env: dict[str, str],
    timeout: float | None = None,
) -> dict[str, Any] | None:
    active_tester = tester
    temp_context = contextlib.nullcontext()
    if tests:
        temp_context = tempfile.TemporaryDirectory(prefix="babel-code-goat-scope-")
    with temp_context as temp_dir:
        if temp_dir is not None:
            active_tester = write_scoped_tester(Path(temp_dir), args.lang, entrypoint, tests)
        run = run_tester_process(args.lang, active_tester, Path(args.solution_path), env, timeout=timeout)
    if run.timed_out:
        return make_result("fail", [], [test["id"] for test in tests])
    result = parse_tester_result(run.completed)
    if result is None or result["status"] == "error":
        return None
    expected_ids = [test["id"] for test in tests]
    if not validate_scoped_result(result, expected_ids):
        return None
    return result


def timeout_seconds(milliseconds: int | None) -> float | None:
    if milliseconds is None:
        return None
    return max(milliseconds, 0) / 1000


def has_invalid_timeout_args(args: argparse.Namespace) -> bool:
    return (args.timeout_ms is not None and args.timeout_ms < 0) or (
        args.total_timeout_ms is not None and args.total_timeout_ms < 0
    )


def command_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parent)
    env["BABEL_CODE_GOAT_ROOT"] = root
    env["BABEL_CODE_GOAT_TOL"] = str(args.tol)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return env


def prepare_command_context(args: argparse.Namespace) -> CommandContext | None:
    if args.lang not in SUPPORTED_LANGS or has_invalid_timeout_args(args):
        return None
    tests_dir = Path(args.tests_dir)
    tester = tests_dir / SUPPORTED_LANGS[args.lang]["tester"]
    if not tester.exists():
        return None
    try:
        payload = extract_tester_payload(tester, args.lang)
        discovered = [test.to_jsonable() for test in discover_tests(tests_dir, payload["entrypoint"])]
    except Exception:
        return None
    if discovered != payload.get("tests"):
        return None

    in_scope = discovered
    if args.run is not None:
        in_scope = [test for test in discovered if test["id"] == args.run]
        if not in_scope:
            return None
    return CommandContext(
        tests_dir=tests_dir,
        tester=tester,
        payload=payload,
        discovered=discovered,
        in_scope=in_scope,
        env=command_env(args),
    )


def run_tests_individually(
    args: argparse.Namespace,
    entrypoint: str,
    tests: list[dict[str, Any]],
    env: dict[str, str],
) -> dict[str, Any] | None:
    passed: list[str] = []
    failed: list[str] = []
    deadline = None
    if args.total_timeout_ms is not None:
        deadline = time.monotonic() + timeout_seconds(args.total_timeout_ms)

    index = 0
    while index < len(tests):
        test = tests[index]
        if deadline is not None and time.monotonic() >= deadline:
            failed.extend(item["id"] for item in tests[index:])
            break

        timeout = timeout_seconds(args.timeout_ms)
        if deadline is not None:
            remaining = max(deadline - time.monotonic(), 0)
            timeout = remaining if timeout is None else min(timeout, remaining)

        result = run_scoped_once(args, entrypoint, [test], Path(), env, timeout=timeout)
        if result is None:
            return None
        if test["id"] in result["passed"]:
            passed.append(test["id"])
        else:
            failed.append(test["id"])
        index += 1

    return make_result("pass" if not failed else "fail", passed, failed)


@dataclass(frozen=True)
class ProfileObservation:
    result: dict[str, Any] | None
    runtime_ns: int
    memory_kb: int


def run_profile_once(args: argparse.Namespace, context: CommandContext) -> ProfileObservation:
    start_ns = time.perf_counter_ns()
    start_usage = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if args.timeout_ms is not None or args.total_timeout_ms is not None:
        result = run_tests_individually(args, context.payload["entrypoint"], context.in_scope, context.env)
    else:
        result = run_scoped_once(args, context.payload["entrypoint"], context.in_scope, context.tester, context.env)
    runtime_ns = time.perf_counter_ns() - start_ns
    memory_kb = max(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss - start_usage, 0)
    return ProfileObservation(result=result, runtime_ns=runtime_ns, memory_kb=memory_kb)


def stats(values: list[int]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {"mean": mean, "std": variance ** 0.5}


def make_profile_result(
    status: str,
    passed: list[str],
    failed: list[str],
    runtime_values: list[int],
    memory_values: list[int] | None = None,
) -> dict[str, Any]:
    result = make_result(status, passed, failed)
    result["runtime_ns"] = stats(runtime_values)
    if memory_values is not None:
        result["memory_kb"] = stats(memory_values)
    return result


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


def command_test(args: argparse.Namespace) -> int:
    context = prepare_command_context(args)
    if context is None:
        return print_result(RESULT_ERROR)

    if args.list_tests:
        return print_result(make_result("pass", [test["id"] for test in context.discovered], []))

    try:
        if args.timeout_ms is not None or args.total_timeout_ms is not None:
            result = run_tests_individually(args, context.payload["entrypoint"], context.in_scope, context.env)
        else:
            result = run_scoped_once(args, context.payload["entrypoint"], context.in_scope, context.tester, context.env)
    except Exception:
        return print_result(RESULT_ERROR)
    if result is None:
        return print_result(RESULT_ERROR)
    return print_result(result)


def command_profile(args: argparse.Namespace) -> int:
    if args.trials < 1 or args.warmup < 0 or args.warmup >= args.trials:
        return print_result(RESULT_ERROR)
    context = prepare_command_context(args)
    if context is None:
        return print_result(RESULT_ERROR)

    if args.list_tests:
        return print_result(
            make_profile_result("pass", [test["id"] for test in context.discovered], [], [0], [0] if args.memory else None)
        )

    measured: list[ProfileObservation] = []
    try:
        for index in range(args.warmup + args.trials):
            observation = run_profile_once(args, context)
            if observation.result is None:
                return print_result(RESULT_ERROR)
            if index >= args.warmup:
                measured.append(observation)
    except Exception:
        return print_result(RESULT_ERROR)

    failed_ids: set[str] = set()
    for observation in measured:
        failed_ids.update(observation.result["failed"])
    scope_ids = [test["id"] for test in context.in_scope]
    passed = [test_id for test_id in scope_ids if test_id not in failed_ids]
    failed = [test_id for test_id in scope_ids if test_id in failed_ids]
    status = "pass" if not failed else "fail"
    memory_values = [observation.memory_kb for observation in measured] if args.memory else None
    return print_result(
        make_profile_result(status, passed, failed, [observation.runtime_ns for observation in measured], memory_values)
    )


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
    profile.add_argument("-n", dest="trials", type=int, default=1)
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
