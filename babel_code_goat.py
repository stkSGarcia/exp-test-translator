#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import asyncio
from collections import Counter, defaultdict, deque
import contextlib
from decimal import Decimal, InvalidOperation
import fnmatch
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
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
# Internal runtime contract from the CLI to generated testers.
SELECTED_IDS_ENV = "BABEL_CODE_GOAT_SELECTED_IDS"
TIMEOUT_MS_ENV = "BABEL_CODE_GOAT_TIMEOUT_MS"
TOTAL_TIMEOUT_MS_ENV = "BABEL_CODE_GOAT_TOTAL_TIMEOUT_MS"


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
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    in_loop: bool = False
    mutation_group: str | None = None
    mutation_arg_names: dict[str, int] | None = None
    mutation_assign: str | None = None

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
            "expect_stdout": self.expect_stdout,
            "expect_stderr": self.expect_stderr,
            "mutation_group": self.mutation_group,
            "mutation_arg_names": self.mutation_arg_names,
            "mutation_assign": self.mutation_assign,
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
    node: ast.AST, entrypoint: str, context: DiscoveryContext, variable_refs: set[str] | None = None
) -> ExpressionBuild:
    variable_refs = variable_refs or set()
    if isinstance(node, ast.Name) and node.id in variable_refs:
        return ExpressionBuild({"op": "var", "name": node.id}, None, 0)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint:
        return ExpressionBuild({"op": "actual"}, parse_entrypoint_call(node, entrypoint, context), 1)

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = expression_from_node(node.args[0], entrypoint, context, variable_refs)
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
        operand = expression_from_node(node.operand, entrypoint, context, variable_refs)
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
        left = expression_from_node(node.left, entrypoint, context, variable_refs)
        right = expression_from_node(node.right, entrypoint, context, variable_refs)
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
        values = [expression_from_node(value, entrypoint, context, variable_refs) for value in node.values]
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
            ast.Is: "is",
            ast.IsNot: "is_not",
        }
        operator = next((name for op_type, name in compare_ops.items() if isinstance(node.ops[0], op_type)), None)
        if operator is None:
            raise DiscoveryError("unsupported comparison expression")
        left = expression_from_node(node.left, entrypoint, context, variable_refs)
        right = expression_from_node(node.comparators[0], entrypoint, context, variable_refs)
        args, call_count = merge_expression_args([left, right])
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression},
            args,
            call_count,
        )

    if isinstance(node, ast.Subscript):
        if entrypoint_call_count(node, entrypoint) == 0 and not (referenced_names(node) & variable_refs):
            return const_expression(node, context)
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = expression_from_node(node.value, entrypoint, context, variable_refs)
        index = expression_from_node(node.slice, entrypoint, context, variable_refs)
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


def clone_test_case(test_case: TestCase, source: str, in_loop: bool) -> TestCase:
    return TestCase(
        id=test_case.id,
        line=test_case.line,
        kind=test_case.kind,
        args=test_case.args,
        source=source,
        expected=test_case.expected,
        tolerance=test_case.tolerance,
        expected_exception=test_case.expected_exception,
        message_match=test_case.message_match,
        expression=test_case.expression,
        expect_stdout=test_case.expect_stdout,
        expect_stderr=test_case.expect_stderr,
        in_loop=in_loop,
        mutation_group=test_case.mutation_group,
        mutation_arg_names=test_case.mutation_arg_names,
        mutation_assign=test_case.mutation_assign,
    )


def loop_case(node: ast.stmt, executed: bool, source: str) -> TestCase:
    return TestCase(id="", line=node.lineno, kind="loop", args=[], source=source, expected=executed)


def is_configured_entrypoint_call(node: ast.AST, entrypoint: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint


def mutation_start(stmt: ast.stmt, entrypoint: str) -> tuple[ast.Call, str | None] | None:
    if isinstance(stmt, ast.Expr) and is_configured_entrypoint_call(stmt.value, entrypoint):
        return stmt.value, None
    if (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and is_configured_entrypoint_call(stmt.value, entrypoint)
    ):
        return stmt.value, stmt.targets[0].id
    return None


def mutation_arg_name_indexes(call: ast.Call) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, arg in enumerate(call.args):
        if isinstance(arg, ast.Name):
            indexes[arg.id] = index
    return indexes


def parse_mutation_group(
    stmt: ast.stmt,
    call: ast.Call,
    assign_name: str | None,
    assertions: list[ast.Assert],
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source: str,
    group_counter: dict[str, int],
    in_loop: bool,
) -> list[TestCase]:
    if not assertions:
        raise DiscoveryError("mutation call must be immediately followed by assertions")
    args = parse_entrypoint_call(call, entrypoint, context)
    arg_names = mutation_arg_name_indexes(call)
    allowed_refs = set(arg_names)
    if assign_name is not None:
        allowed_refs.add(assign_name)
    if not allowed_refs:
        raise DiscoveryError("mutation call must expose a referenced variable")

    group_key = f"{source}:{stmt.lineno}"
    group_index = group_counter.get(group_key, 0)
    group_counter[group_key] = group_index + 1
    group_id = f"{group_key}:{group_index}"

    discovered: list[TestCase] = []
    for assertion in assertions:
        if entrypoint_call_count(assertion.test, entrypoint):
            raise DiscoveryError("mutation assertion cannot call entrypoint")
        if not (referenced_names(assertion.test) & allowed_refs):
            raise DiscoveryError("mutation assertion must reference a mutation variable")
        parsed = expression_from_node(assertion.test, entrypoint, context, allowed_refs)
        if parsed.call_count != 0:
            raise DiscoveryError("mutation assertion cannot call entrypoint")
        expect_stdout, expect_stderr = parse_expectations(lines, assertion.lineno)
        discovered.append(
            TestCase(
                id="",
                line=assertion.lineno,
                kind="mutation",
                args=args,
                source=source,
                expression=parsed.expression,
                expect_stdout=expect_stdout,
                expect_stderr=expect_stderr,
                in_loop=in_loop,
                mutation_group=group_id,
                mutation_arg_names=arg_names,
                mutation_assign=assign_name,
            )
        )
    return discovered


def discover_for_loop(
    stmt: ast.For,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source: str,
    group_counter: dict[str, int],
    in_loop: bool,
) -> list[TestCase]:
    if stmt.orelse:
        raise DiscoveryError("unsupported loop else block")
    try:
        iterable = iterable_from_node(stmt.iter, context)
    except DiscoveryError:
        return [loop_case(stmt, False, source)]
    if not iterable:
        return [loop_case(stmt, False, source)]

    discovered = [loop_case(stmt, True, source)]
    for item in iterable:
        iteration_context = context.child()
        bind_target(stmt.target, item, iteration_context)
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, iteration_context, source, group_counter, True))
    return discovered


def discover_while_loop(
    stmt: ast.While,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source: str,
    group_counter: dict[str, int],
    in_loop: bool,
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
            return [loop_case(stmt, False, source)]
        if not condition:
            return [loop_case(stmt, True, source), *discovered] if executed else [loop_case(stmt, False, source)]
        executed = True
        discovered.extend(discover_in_body(stmt.body, entrypoint, lines, working_context, source, group_counter, True))

    return [loop_case(stmt, False, source)]


def discover_in_body(
    body: list[ast.stmt],
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    source: str = "tests.py",
    group_counter: dict[str, int] | None = None,
    in_loop: bool = False,
) -> list[TestCase]:
    if group_counter is None:
        group_counter = {}
    discovered: list[TestCase] = []
    index = 0
    while index < len(body):
        stmt = body[index]
        start = mutation_start(stmt, entrypoint)
        if start is not None:
            call, assign_name = start
            assertions: list[ast.Assert] = []
            cursor = index + 1
            while cursor < len(body) and isinstance(body[cursor], ast.Assert):
                assertions.append(body[cursor])
                cursor += 1
            discovered.extend(
                parse_mutation_group(
                    stmt, call, assign_name, assertions, entrypoint, lines, context, source, group_counter, in_loop
                )
            )
            index = cursor
            continue
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context.child(), source, group_counter, in_loop))
        elif isinstance(stmt, ast.Assert):
            test_case = parse_assert(stmt, entrypoint, lines, context)
            discovered.append(clone_test_case(test_case, source, in_loop))
        elif isinstance(stmt, ast.Try):
            test_case = parse_raise_any(stmt, entrypoint, lines, context)
            discovered.append(clone_test_case(test_case, source, in_loop))
        elif isinstance(stmt, ast.For):
            discovered.extend(discover_for_loop(stmt, entrypoint, lines, context, source, group_counter, in_loop))
        elif isinstance(stmt, ast.While):
            discovered.extend(discover_while_loop(stmt, entrypoint, lines, context, source, group_counter, in_loop))
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
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=test_case.in_loop,
                mutation_group=test_case.mutation_group,
                mutation_arg_names=test_case.mutation_arg_names,
                mutation_assign=test_case.mutation_assign,
            )
        )
    return assigned


TESTER_FILENAMES = {config["tester"] for config in SUPPORTED_LANGS.values()}


def is_test_like_non_python(path: Path) -> bool:
    if path.name in TESTER_FILENAMES or path.suffix.lower() == ".py":
        return False
    if not path.suffix:
        return False
    stem = path.stem
    return (
        fnmatch.fnmatch(stem, "test*")
        or fnmatch.fnmatch(stem, "*_test")
        or stem == "tests"
        or fnmatch.fnmatch(stem, "*_tests")
    )


def python_test_sources(tests_dir: Path) -> list[Path]:
    if not tests_dir.exists() or not tests_dir.is_dir():
        raise DiscoveryError("tests directory not found")
    for path in tests_dir.rglob("*"):
        if path.is_file() and is_test_like_non_python(path):
            raise DiscoveryError("non-python test-like file")
    return sorted(
        (path for path in tests_dir.rglob("*.py") if path.is_file() and path.name not in TESTER_FILENAMES),
        key=lambda path: path.relative_to(tests_dir).as_posix(),
    )


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    discovered: list[TestCase] = []
    group_counter: dict[str, int] = {}
    for tests_path in python_test_sources(tests_dir):
        relative_path = tests_path.relative_to(tests_dir).as_posix()
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
        discovered.extend(discover_in_body(tree.body, entrypoint, lines, context, relative_path, group_counter))
    if not discovered:
        raise DiscoveryError("no tests discovered")
    return assign_ids(discovered)


def make_result(status: str, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "passed": passed or [], "failed": failed or []}


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


def evaluate_expression(expression: dict[str, Any], actual: Any, tolerance: dict[str, Any]) -> Any:
    op = expression.get("op")
    if op == "const":
        return expression.get("value")
    if op == "actual":
        return actual
    if op == "var":
        raise RuntimeError("variable expression requires runtime variables")
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
        if operator == "is":
            return left is right
        if operator == "is_not":
            return left is not right
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


def evaluate_expression_with_vars(
    expression: dict[str, Any], actual: Any, tolerance: dict[str, Any], variables: dict[str, Any]
) -> Any:
    if expression.get("op") == "var":
        return variables[expression["name"]]
    if expression.get("op") == "unary":
        operand = evaluate_expression_with_vars(expression["operand"], actual, tolerance, variables)
        operator = expression.get("operator")
        if operator == "not":
            return not bool(operand)
        if operator == "neg":
            return -operand
        if operator == "pos":
            return +operand
    if expression.get("op") == "binary":
        left = evaluate_expression_with_vars(expression["left"], actual, tolerance, variables)
        right = evaluate_expression_with_vars(expression["right"], actual, tolerance, variables)
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
    if expression.get("op") == "bool":
        values = [evaluate_expression_with_vars(value, actual, tolerance, variables) for value in expression["values"]]
        if expression.get("operator") == "and":
            return all(bool(value) for value in values)
        if expression.get("operator") == "or":
            return any(bool(value) for value in values)
    if expression.get("op") == "compare":
        left = evaluate_expression_with_vars(expression["left"], actual, tolerance, variables)
        right = evaluate_expression_with_vars(expression["right"], actual, tolerance, variables)
        operator = expression.get("operator")
        if operator == "eq":
            return deep_compare(normalize_comparable(left), normalize_comparable(right), tolerance)
        if operator == "neq":
            return not deep_compare(normalize_comparable(left), normalize_comparable(right), tolerance)
        if operator == "is":
            return left is right
        if operator == "is_not":
            return left is not right
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
    if expression.get("op") == "index":
        value = evaluate_expression_with_vars(expression["value"], actual, tolerance, variables)
        index = evaluate_expression_with_vars(expression["index"], actual, tolerance, variables)
        return expression_index(value, index)
    if expression.get("op") == "call":
        args = [evaluate_expression_with_vars(arg, actual, tolerance, variables) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return expression_sorted(args[0])
        if expression.get("function") == "abs":
            return abs(args[0])
    return evaluate_expression(expression, actual, tolerance)


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


def complete_python_value(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def execute_python_mutation_group(
    callable_under_test: Any, group: list[dict[str, Any]], default_tol: float
) -> tuple[list[str], list[str]]:
    call_args = [decode_arg(arg) for arg in group[0]["args"]]
    variables = {
        name: call_args[index]
        for name, index in (group[0].get("mutation_arg_names") or {}).items()
        if index < len(call_args)
    }
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    raised = False
    actual = None
    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            actual = complete_python_value(callable_under_test(*call_args))
    except Exception:
        raised = True
    if group[0].get("mutation_assign") is not None:
        variables[group[0]["mutation_assign"]] = actual

    passed: list[str] = []
    failed: list[str] = []
    for test in group:
        ok = False
        if not raised:
            try:
                ok = bool(
                    evaluate_expression_with_vars(
                        test["expression"],
                        actual,
                        tolerance_policy(test, default_tol),
                        variables,
                    )
                )
            except Exception:
                ok = False
        if test.get("expect_stdout") is not None and stdout_buffer.getvalue() != test["expect_stdout"]:
            ok = False
        if test.get("expect_stderr") is not None and stderr_buffer.getvalue() != test["expect_stderr"]:
            ok = False
        (passed if ok else failed).append(test["id"])
    return passed, failed


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
    index = 0
    while index < len(tests):
        test = tests[index]
        if test["kind"] == "mutation":
            cursor = index + 1
            while (
                cursor < len(tests)
                and tests[cursor]["kind"] == "mutation"
                and tests[cursor].get("mutation_group") == test.get("mutation_group")
            ):
                cursor += 1
            group_passed, group_failed = execute_python_mutation_group(
                callable_under_test, tests[index:cursor], default_tol
            )
            passed.extend(group_passed)
            failed.extend(group_failed)
            index = cursor
            continue
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
        index += 1
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
    selected_raw = os.environ.get("{SELECTED_IDS_ENV}", "")
    selected_ids = set(json.loads(selected_raw)) if selected_raw else None
    tests = [test for test in data["tests"] if selected_ids is None or test["id"] in selected_ids]
    result = execute_python_tests(Path(sys.argv[1]), data["entrypoint"], tests, float(os.environ.get("BABEL_CODE_GOAT_TOL", "0")))
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
const selectedRaw = process.env.{SELECTED_IDS_ENV} || "";
const selectedIds = selectedRaw ? new Set(JSON.parse(selectedRaw)) : null;
const selectedTests = selectedIds ? payload.tests.filter(test => selectedIds.has(test.id)) : payload.tests;

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
  if (value === undefined) return null;
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

function evaluateExpression(expression, actual, tolerance, variables = {{}}) {{
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
    if (expression.operator === "is") return right === null ? left == null : Object.is(left, right);
    if (expression.operator === "is_not") return !(right === null ? left == null : Object.is(left, right));
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

async function executeMutationGroup(fn, group) {{
  const callArgs = group[0].args.map(decodeArg);
  const variables = {{}};
  for (const [name, index] of Object.entries(group[0].mutation_arg_names || {{}})) {{
    if (index < callArgs.length) variables[name] = callArgs[index];
  }}
  let stdout = "";
  let stderr = "";
  const oldOut = process.stdout.write;
  const oldErr = process.stderr.write;
  process.stdout.write = function(chunk, encoding, cb) {{ stdout += String(chunk); if (typeof cb === "function") cb(); return true; }};
  process.stderr.write = function(chunk, encoding, cb) {{ stderr += String(chunk); if (typeof cb === "function") cb(); return true; }};
  let raised = false;
  let actual;
  try {{
    actual = fn(...callArgs);
    if (actual && typeof actual.then === "function") actual = await actual;
  }} catch (error) {{
    raised = true;
  }} finally {{
    process.stdout.write = oldOut;
    process.stderr.write = oldErr;
  }}
  if (group[0].mutation_assign !== null) variables[group[0].mutation_assign] = actual;
  const passed = [];
  const failed = [];
  for (const test of group) {{
    let ok = false;
    if (!raised) {{
      try {{
        ok = !!evaluateExpression(test.expression, actual, tolerancePolicy(test), variables);
      }} catch (error) {{
        ok = false;
      }}
    }}
    if (test.expect_stdout !== null && stdout !== test.expect_stdout) ok = false;
    if (test.expect_stderr !== null && stderr !== test.expect_stderr) ok = false;
    (ok ? passed : failed).push(test.id);
  }}
  return {{passed, failed}};
}}

async function main() {{
  if (process.argv.length !== 3) {{
    console.log(JSON.stringify({{status: "error", passed: [], failed: []}}));
    return 2;
  }}
  const solutionPath = path.resolve(process.argv[2]);
  let fn;
  const hasExecutableTests = selectedTests.some(test => test.kind !== "loop");
  if (hasExecutableTests) {{
    try {{
      fn = findCallable(await loadSolution(solutionPath), payload.entrypoint);
    }} catch (error) {{
      console.log(JSON.stringify({{status: "fail", passed: [], failed: selectedTests.map(test => test.id)}}));
      return 1;
    }}
  }}

  const passed = [];
  const failed = [];
  for (let index = 0; index < selectedTests.length; index++) {{
    const test = selectedTests[index];
    if (test.kind === "mutation") {{
      let cursor = index + 1;
      while (cursor < selectedTests.length && selectedTests[cursor].kind === "mutation" && selectedTests[cursor].mutation_group === test.mutation_group) cursor++;
      const result = await executeMutationGroup(fn, selectedTests.slice(index, cursor));
      passed.push(...result.passed);
      failed.push(...result.failed);
      index = cursor - 1;
      continue;
    }}
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


def c_string(value: str) -> str:
    return json.dumps(value)


def cpp_value_literal(value: Any) -> str:
    if value is None:
        return "BcgValue::null()"
    if isinstance(value, bool):
        return f"BcgValue::boolean({str(value).lower()})"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"BcgValue::number({repr(value)}L)"
    if isinstance(value, str):
        return f"BcgValue::string({c_string(value)})"
    if isinstance(value, list):
        return "BcgValue::array(std::vector<BcgValue>{" + ",".join(cpp_value_literal(item) for item in value) + "})"
    if is_tagged(value, "decimal"):
        return f"BcgValue::number({c_string(value['value'])})"
    if is_tagged(value, "dict"):
        pairs = ",".join(
            "{" + cpp_value_literal(key) + "," + cpp_value_literal(item) + "}" for key, item in value["items"]
        )
        return f"BcgValue::dict(std::vector<std::pair<BcgValue,BcgValue>>{{{pairs}}})"
    if is_tagged(value, "set"):
        return "BcgValue::set(std::vector<BcgValue>{" + ",".join(cpp_value_literal(item) for item in value["items"]) + "})"
    if is_tagged(value, "counter"):
        pairs = ",".join(
            "{" + cpp_value_literal(key) + "," + cpp_value_literal(item) + "}" for key, item in value["items"]
        )
        return f"BcgValue::counter(std::vector<std::pair<BcgValue,BcgValue>>{{{pairs}}})"
    if is_tagged(value, "deque"):
        return "BcgValue::deque(std::vector<BcgValue>{" + ",".join(cpp_value_literal(item) for item in value["items"]) + "})"
    return "BcgValue::null()"


def cpp_merge_types(types: list[str]) -> str:
    non_null = [type_name for type_name in types if type_name != "std::nullopt_t"]
    if not non_null:
        return "std::optional<int>"
    first = non_null[0]
    if any(type_name != first for type_name in non_null):
        first = "BcgValue"
    if len(non_null) != len(types):
        return f"std::optional<{first}>"
    return first


def cpp_native_type(value: Any) -> str:
    if value is None:
        return "std::nullopt_t"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "long double"
    if isinstance(value, str):
        return "std::string"
    if isinstance(value, list):
        item_type = cpp_merge_types([cpp_native_type(item) for item in value])
        return f"std::vector<{item_type}>"
    if is_tagged(value, "decimal"):
        return "long double"
    if is_tagged(value, "set"):
        item_type = cpp_merge_types([cpp_native_type(item) for item in value["items"]])
        return f"std::set<{item_type}>"
    if is_tagged(value, "deque"):
        item_type = cpp_merge_types([cpp_native_type(item) for item in value["items"]])
        return f"std::deque<{item_type}>"
    if is_tagged(value, "counter"):
        key_type = cpp_merge_types([cpp_native_type(key) for key, _ in value["items"]])
        return f"std::map<{key_type}, int>"
    if is_tagged(value, "dict"):
        key_type = cpp_merge_types([cpp_native_type(key) for key, _ in value["items"]])
        item_type = cpp_merge_types([cpp_native_type(item) for _, item in value["items"]])
        return f"std::map<{key_type}, {item_type}>"
    return "BcgValue"


def cpp_native_literal(value: Any, type_hint: str | None = None) -> str:
    if type_hint is None:
        type_hint = cpp_native_type(value)
    if value is None:
        return f"{type_hint}{{}}"
    if type_hint.startswith("std::optional<"):
        inner = type_hint.removeprefix("std::optional<").removesuffix(">")
        return f"{type_hint}{{{cpp_native_literal(value, inner)}}}"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{repr(value)}L"
    if isinstance(value, str):
        return f"std::string({c_string(value)})"
    if isinstance(value, list):
        item_type = type_hint.removeprefix("std::vector<").removesuffix(">")
        return f"{type_hint}{{" + ",".join(cpp_native_literal(item, item_type) for item in value) + "}"
    if is_tagged(value, "decimal"):
        return f"static_cast<long double>({c_string(value['value'])})"
    if is_tagged(value, "set"):
        item_type = type_hint.removeprefix("std::set<").removesuffix(">")
        return f"{type_hint}{{" + ",".join(cpp_native_literal(item, item_type) for item in value["items"]) + "}"
    if is_tagged(value, "deque"):
        item_type = type_hint.removeprefix("std::deque<").removesuffix(">")
        return f"{type_hint}{{" + ",".join(cpp_native_literal(item, item_type) for item in value["items"]) + "}"
    if is_tagged(value, "counter"):
        key_type = type_hint.removeprefix("std::map<").split(",", 1)[0]
        pairs = ",".join("{" + cpp_native_literal(key, key_type) + "," + cpp_native_literal(count, "int") + "}" for key, count in value["items"])
        return f"{type_hint}{{{pairs}}}"
    if is_tagged(value, "dict"):
        inside = type_hint.removeprefix("std::map<").removesuffix(">")
        key_type, item_type = inside.split(",", 1)
        pairs = ",".join(
            "{" + cpp_native_literal(key, key_type.strip()) + "," + cpp_native_literal(item, item_type.strip()) + "}"
            for key, item in value["items"]
        )
        return f"{type_hint}{{{pairs}}}"
    return cpp_value_literal(value)


def cpp_expression(expression: dict[str, Any], actual_expr: str = "actual", variables: set[str] | None = None) -> str:
    variables = variables or set()
    op = expression.get("op")
    if op == "const":
        return cpp_native_literal(expression.get("value"))
    if op == "actual":
        return actual_expr
    if op == "var":
        return expression["name"]
    if op == "unary":
        operand = cpp_expression(expression["operand"], actual_expr, variables)
        return f"(!({operand}))" if expression.get("operator") == "not" else f"(-({operand}))"
    if op == "binary":
        operators = {
            "add": "+",
            "sub": "-",
            "mul": "*",
            "div": "/",
            "floordiv": "/",
            "mod": "%",
        }
        left = cpp_expression(expression["left"], actual_expr, variables)
        right = cpp_expression(expression["right"], actual_expr, variables)
        if expression.get("operator") == "pow":
            return f"std::pow(({left}), ({right}))"
        return f"(({left}) {operators[expression['operator']]} ({right}))"
    if op == "bool":
        parts = [cpp_expression(value, actual_expr, variables) for value in expression["values"]]
        joiner = " && " if expression.get("operator") == "and" else " || "
        return "(" + joiner.join(f"({part})" for part in parts) + ")"
    if op == "compare":
        left = cpp_expression(expression["left"], actual_expr, variables)
        right = cpp_expression(expression["right"], actual_expr, variables)
        operator = expression.get("operator")
        if operator == "eq":
            return f"bcg_equal(bcg_normalize({left}), bcg_normalize({right}), tolerance)"
        if operator == "neq":
            return f"!bcg_equal(bcg_normalize({left}), bcg_normalize({right}), tolerance)"
        if operator == "is":
            return f"bcg_equal(bcg_normalize({left}), bcg_normalize({right}), tolerance)"
        if operator == "is_not":
            return f"!bcg_equal(bcg_normalize({left}), bcg_normalize({right}), tolerance)"
        if operator == "in":
            return f"bcg_contains(({right}), ({left}), tolerance)"
        if operator == "not_in":
            return f"!bcg_contains(({right}), ({left}), tolerance)"
        operators = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        return f"(({left}) {operators[operator]} ({right}))"
    if op == "index":
        value = cpp_expression(expression["value"], actual_expr, variables)
        index = cpp_expression(expression["index"], actual_expr, variables)
        return f"({value})[{index}]"
    if op == "call":
        args = [cpp_expression(arg, actual_expr, variables) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return f"bcg_sorted({args[0]})"
        if expression.get("function") == "abs":
            return f"std::abs({args[0]})"
    return "false"


def cpp_tolerance_literal(test: dict[str, Any]) -> str:
    tolerance = test.get("tolerance")
    if isinstance(tolerance, dict):
        strict = "true" if tolerance.get("strict") else "false"
        return (
            "BcgTolerance{"
            + c_string(str(tolerance.get("mode", "default")))
            + f",{float(tolerance.get('abs', 0.0))}L,{float(tolerance.get('rel', 0.0))}L,{strict}}}"
        )
    return "bcg_default_tolerance()"


def cpp_test_block(test: dict[str, Any], index: int) -> str:
    test_id = c_string(test["id"])
    stdout_expected = test.get("expect_stdout")
    stderr_expected = test.get("expect_stderr")
    output_checks = ""
    if stdout_expected is not None:
        output_checks += f"\n    if (stdout_capture.str() != {c_string(stdout_expected)}) ok = false;"
    if stderr_expected is not None:
        output_checks += f"\n    if (stderr_capture.str() != {c_string(stderr_expected)}) ok = false;"
    if test["kind"] == "loop":
        ok = "true" if test.get("expected") else "false"
        return f"""
  if (bcg_should_run({test_id})) {{
  {{
    bool ok = {ok};
    (ok ? passed : failed).push_back({test_id});
  }}
  }}
"""
    arg_types = [cpp_native_type(arg) for arg in test["args"]]
    arg_literals = [cpp_native_literal(arg, type_name) for arg, type_name in zip(test["args"], arg_types, strict=True)]
    arg_list = ",".join(arg_literals)
    tolerance = cpp_tolerance_literal(test)
    if test["kind"] == "raises":
        matcher = test.get("message_match") or {}
        message_check = "true"
        if matcher.get("mode") == "contains":
            message_check = f"std::string(exc.what()).find({c_string(matcher.get('pattern', ''))}) != std::string::npos"
        elif matcher.get("mode") == "regex":
            message_check = f"std::regex_search(std::string(exc.what()), std::regex({c_string(matcher.get('pattern', ''))}))"
        return f"""
  if (bcg_should_run({test_id})) {{
  {{
    bool ok = false;
    std::ostringstream stdout_capture;
    std::ostringstream stderr_capture;
    auto* old_out = std::cout.rdbuf(stdout_capture.rdbuf());
    auto* old_err = std::cerr.rdbuf(stderr_capture.rdbuf());
    try {{
      solve({arg_list});
    }} catch (const std::exception& exc) {{
      ok = {message_check};
    }} catch (...) {{
      ok = true;
    }}
    std::cout.rdbuf(old_out);
    std::cerr.rdbuf(old_err);{output_checks}
    (ok ? passed : failed).push_back({test_id});
  }}
  }}
"""
    if test["kind"] == "expr":
        expr = cpp_expression(test["expression"])
        ok_expr = f"static_cast<bool>({expr})"
    elif test["kind"] == "eq":
        ok_expr = f"bcg_equal({cpp_value_literal(test['expected'])}, bcg_normalize(actual), tolerance)"
    elif test["kind"] == "neq":
        ok_expr = f"!bcg_equal({cpp_value_literal(test['expected'])}, bcg_normalize(actual), tolerance)"
    elif test["kind"] == "truthy":
        ok_expr = "bcg_truthy(bcg_normalize(actual))"
    elif test["kind"] == "falsy":
        ok_expr = "!bcg_truthy(bcg_normalize(actual))"
    else:
        ok_expr = "false"
    return f"""
  if (bcg_should_run({test_id})) {{
  {{
    bool ok = false;
    BcgTolerance tolerance = {tolerance};
    std::ostringstream stdout_capture;
    std::ostringstream stderr_capture;
    auto* old_out = std::cout.rdbuf(stdout_capture.rdbuf());
    auto* old_err = std::cerr.rdbuf(stderr_capture.rdbuf());
    try {{
      auto actual = bcg_complete(solve({arg_list}));
      ok = {ok_expr};
    }} catch (...) {{
      ok = false;
    }}
    std::cout.rdbuf(old_out);
    std::cerr.rdbuf(old_err);{output_checks}
    (ok ? passed : failed).push_back({test_id});
  }}
  }}
"""


def cpp_test_blocks(tests: list[TestCase]) -> str:
    payload_tests = [test.to_jsonable() for test in tests]
    blocks: list[str] = []
    index = 0
    while index < len(payload_tests):
        test = payload_tests[index]
        if test["kind"] != "mutation":
            blocks.append(cpp_test_block(test, index))
            index += 1
            continue
        group_id = test.get("mutation_group")
        group: list[dict[str, Any]] = []
        while index < len(payload_tests) and payload_tests[index]["kind"] == "mutation" and payload_tests[index].get("mutation_group") == group_id:
            group.append(payload_tests[index])
            index += 1
        arg_types = [cpp_native_type(arg) for arg in group[0]["args"]]
        declarations = [
            f"    {type_name} arg{arg_index} = {cpp_native_literal(arg, type_name)};"
            for arg_index, (arg, type_name) in enumerate(zip(group[0]["args"], arg_types, strict=True))
        ]
        variables = {
            name: f"arg{arg_index}" for name, arg_index in (group[0].get("mutation_arg_names") or {}).items()
        }
        assigned = group[0].get("mutation_assign")
        call_args = ",".join(f"arg{arg_index}" for arg_index in range(len(group[0]["args"])))
        assertion_blocks = []
        for assertion in group:
            assertion_id = c_string(assertion["id"])
            expression = cpp_expression(assertion["expression"], assigned or "actual", set(variables))
            for name, actual_name in variables.items():
                expression = re.sub(rf"\b{re.escape(name)}\b", actual_name, expression)
            assertion_blocks.append(
                f"""
    if (bcg_should_run({assertion_id})) {{
    {{
      BcgTolerance tolerance = {cpp_tolerance_literal(assertion)};
      bool ok = !raised && static_cast<bool>({expression});
      (ok ? passed : failed).push_back({assertion_id});
    }}
    }}
"""
            )
        actual_declaration = "auto actual = " if assigned is not None else ""
        actual_call = f"{actual_declaration}bcg_complete(solve({call_args}));" if assigned is not None else f"solve({call_args});"
        group_condition = " || ".join(f"bcg_should_run({c_string(assertion['id'])})" for assertion in group)
        blocks.append(
            f"""
  if ({group_condition}) {{
  {{
{chr(10).join(declarations)}
    bool raised = false;
    try {{
      {actual_call}
    }} catch (...) {{
      raised = true;
    }}
{''.join(assertion_blocks)}
  }}
  }}
"""
        )
    return "".join(blocks)


def rust_value_literal(value: Any) -> str:
    if value is None:
        return "BcgValue::Null"
    if isinstance(value, bool):
        return f"BcgValue::Bool({str(value).lower()})"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"BcgValue::Number({repr(value)} as f64)"
    if isinstance(value, str):
        return f"BcgValue::String(String::from({c_string(value)}))"
    if isinstance(value, list):
        return "BcgValue::Array(vec![" + ",".join(rust_value_literal(item) for item in value) + "])"
    if is_tagged(value, "decimal"):
        return f"BcgValue::Number({c_string(value['value'])}.parse::<f64>().unwrap())"
    if is_tagged(value, "dict"):
        pairs = ",".join(
            "(" + rust_value_literal(key) + "," + rust_value_literal(item) + ")" for key, item in value["items"]
        )
        return f"BcgValue::Dict(vec![{pairs}])"
    if is_tagged(value, "set"):
        return "BcgValue::Set(vec![" + ",".join(rust_value_literal(item) for item in value["items"]) + "])"
    if is_tagged(value, "counter"):
        pairs = ",".join(
            "(" + rust_value_literal(key) + "," + rust_value_literal(item) + ")" for key, item in value["items"]
        )
        return f"BcgValue::Counter(vec![{pairs}])"
    if is_tagged(value, "deque"):
        return "BcgValue::Deque(vec![" + ",".join(rust_value_literal(item) for item in value["items"]) + "])"
    return "BcgValue::Null"


def rust_native_literal(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{repr(value)}f64"
    if isinstance(value, str):
        return f"String::from({c_string(value)})"
    if isinstance(value, list):
        return "vec![" + ",".join(rust_native_literal(item) for item in value) + "]"
    if is_tagged(value, "decimal"):
        return f"{c_string(value['value'])}.parse::<f64>().unwrap()"
    if is_tagged(value, "set"):
        return "HashSet::from([" + ",".join(rust_native_literal(item) for item in value["items"]) + "])"
    if is_tagged(value, "deque"):
        return "VecDeque::from([" + ",".join(rust_native_literal(item) for item in value["items"]) + "])"
    if is_tagged(value, "counter"):
        pairs = ",".join(
            "(" + rust_native_literal(key) + "," + rust_native_literal(count) + ")" for key, count in value["items"]
        )
        return f"HashMap::from([{pairs}])"
    if is_tagged(value, "dict"):
        pairs = ",".join(
            "(" + rust_native_literal(key) + "," + rust_native_literal(item) + ")" for key, item in value["items"]
        )
        return f"HashMap::from([{pairs}])"
    return rust_value_literal(value)


def rust_expression(expression: dict[str, Any], actual_expr: str = "actual") -> str:
    op = expression.get("op")
    if op == "const":
        return rust_native_literal(expression.get("value"))
    if op == "actual":
        return actual_expr
    if op == "var":
        return expression["name"]
    if op == "unary":
        operand = rust_expression(expression["operand"], actual_expr)
        return f"!({operand})" if expression.get("operator") == "not" else f"-({operand})"
    if op == "binary":
        operators = {
            "add": "+",
            "sub": "-",
            "mul": "*",
            "div": "/",
            "floordiv": "/",
            "mod": "%",
        }
        left = rust_expression(expression["left"], actual_expr)
        right = rust_expression(expression["right"], actual_expr)
        if expression.get("operator") == "pow":
            return f"({left}).powf({right} as f64)"
        return f"(({left}) {operators[expression['operator']]} ({right}))"
    if op == "bool":
        parts = [rust_expression(value, actual_expr) for value in expression["values"]]
        joiner = " && " if expression.get("operator") == "and" else " || "
        return "(" + joiner.join(f"({part})" for part in parts) + ")"
    if op == "compare":
        left = rust_expression(expression["left"], actual_expr)
        right = rust_expression(expression["right"], actual_expr)
        operator = expression.get("operator")
        if operator == "eq":
            return f"bcg_equal(&bcg_normalize_value(&({left})), &bcg_normalize_value(&({right})), tolerance)"
        if operator == "neq":
            return f"!bcg_equal(&bcg_normalize_value(&({left})), &bcg_normalize_value(&({right})), tolerance)"
        if operator == "is":
            return f"bcg_equal(&bcg_normalize_value(&({left})), &bcg_normalize_value(&({right})), tolerance)"
        if operator == "is_not":
            return f"!bcg_equal(&bcg_normalize_value(&({left})), &bcg_normalize_value(&({right})), tolerance)"
        if operator == "in":
            return f"bcg_contains(&({right}), &({left}), tolerance)"
        if operator == "not_in":
            return f"!bcg_contains(&({right}), &({left}), tolerance)"
        operators = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        return f"(({left}) {operators[operator]} ({right}))"
    if op == "index":
        value = rust_expression(expression["value"], actual_expr)
        index = rust_expression(expression["index"], actual_expr)
        return f"({value})[{index} as usize].clone()"
    if op == "call":
        args = [rust_expression(arg, actual_expr) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return f"bcg_sorted({args[0]}.clone())"
        if expression.get("function") == "abs":
            return f"({args[0]}).abs()"
    return "false"


def rust_tolerance_literal(test: dict[str, Any]) -> str:
    tolerance = test.get("tolerance")
    if isinstance(tolerance, dict):
        strict = "true" if tolerance.get("strict") else "false"
        return f"BcgTolerance {{ abs: {float(tolerance.get('abs', 0.0))}f64, rel: {float(tolerance.get('rel', 0.0))}f64, strict: {strict} }}"
    return "bcg_default_tolerance()"


def rust_test_block(test: dict[str, Any]) -> str:
    test_id = c_string(test["id"])
    if test["kind"] == "loop":
        ok = "true" if test.get("expected") else "false"
        return f"""
    if bcg_should_run({test_id}) {{
    {{
        let ok = {ok};
        if ok {{ passed.push({test_id}); }} else {{ failed.push({test_id}); }}
    }}
    }}
"""
    arg_list = ",".join(rust_native_literal(arg) for arg in test["args"])
    if test["kind"] == "raises":
        matcher = test.get("message_match") or {}
        message_check = "true"
        if matcher.get("mode") in {"contains", "regex"}:
            message_check = f"message.contains({c_string(matcher.get('pattern', ''))})"
        return f"""
    if bcg_should_run({test_id}) {{
    {{
        let result = panic::catch_unwind(AssertUnwindSafe(|| {{ solve({arg_list}); }}));
        let ok = match result {{
            Ok(_) => false,
            Err(error) => {{
                let message = bcg_panic_message(error.as_ref());
                {message_check}
            }}
        }};
        if ok {{ passed.push({test_id}); }} else {{ failed.push({test_id}); }}
    }}
    }}
"""
    tolerance = rust_tolerance_literal(test)
    if test["kind"] == "expr":
        ok_expr = rust_expression(test["expression"])
    elif test["kind"] == "eq":
        ok_expr = f"bcg_equal(&{rust_value_literal(test['expected'])}, &actual.bcg_normalize(), tolerance)"
    elif test["kind"] == "neq":
        ok_expr = f"!bcg_equal(&{rust_value_literal(test['expected'])}, &actual.bcg_normalize(), tolerance)"
    elif test["kind"] == "truthy":
        ok_expr = "actual.bcg_normalize().is_truthy()"
    elif test["kind"] == "falsy":
        ok_expr = "!actual.bcg_normalize().is_truthy()"
    else:
        ok_expr = "false"
    return f"""
    if bcg_should_run({test_id}) {{
    {{
        let tolerance = {tolerance};
        let ok = match panic::catch_unwind(AssertUnwindSafe(|| solve({arg_list}))) {{
            Ok(actual) => {ok_expr},
            Err(_) => false,
        }};
        if ok {{ passed.push({test_id}); }} else {{ failed.push({test_id}); }}
    }}
    }}
"""


def rust_test_blocks(tests: list[TestCase]) -> str:
    payload_tests = [test.to_jsonable() for test in tests]
    blocks: list[str] = []
    index = 0
    while index < len(payload_tests):
        test = payload_tests[index]
        if test["kind"] != "mutation":
            blocks.append(rust_test_block(test))
            index += 1
            continue
        group_id = test.get("mutation_group")
        group: list[dict[str, Any]] = []
        while index < len(payload_tests) and payload_tests[index]["kind"] == "mutation" and payload_tests[index].get("mutation_group") == group_id:
            group.append(payload_tests[index])
            index += 1
        declarations = [
            f"        let mut arg{arg_index} = {rust_native_literal(arg)};"
            for arg_index, arg in enumerate(group[0]["args"])
        ]
        variables = {
            name: f"arg{arg_index}" for name, arg_index in (group[0].get("mutation_arg_names") or {}).items()
        }
        call_args = ",".join(f"&mut arg{arg_index}" for arg_index in range(len(group[0]["args"])))
        assigned = group[0].get("mutation_assign")
        actual_line = f"let {assigned} = solve({call_args});" if assigned else f"solve({call_args});"
        assertion_blocks = []
        for assertion in group:
            assertion_id = c_string(assertion["id"])
            expression = rust_expression(assertion["expression"], assigned or "()")
            for name, actual_name in variables.items():
                expression = re.sub(rf"\b{re.escape(name)}\b", actual_name, expression)
            assertion_blocks.append(
                f"""
        if bcg_should_run({assertion_id}) {{
        {{
            let tolerance = {rust_tolerance_literal(assertion)};
            let ok = !raised && ({expression});
            if ok {{ passed.push({assertion_id}); }} else {{ failed.push({assertion_id}); }}
        }}
        }}
"""
            )
        blocks.append(
            f"""
    if {" || ".join(f"bcg_should_run({c_string(assertion['id'])})" for assertion in group)} {{
    {{
{chr(10).join(declarations)}
        let mut raised = false;
        if panic::catch_unwind(AssertUnwindSafe(|| {{ {actual_line} }})).is_err() {{
            raised = true;
        }}
{''.join(assertion_blocks)}
    }}
    }}
"""
        )
    return "".join(blocks)


def cpp_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    test_blocks = cpp_test_blocks(tests)
    return f"""// Generated by babel_code_goat.py. Requires C++17 or later.
// BCG_PAYLOAD_BEGIN
// {payload}
// BCG_PAYLOAD_END
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <future>
#include <iostream>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include BCG_SOLUTION_PATH

struct BcgTolerance {{
  std::string mode;
  long double abs;
  long double rel;
  bool strict;
}};

BcgTolerance bcg_default_tolerance() {{
  const char* raw = std::getenv("BABEL_CODE_GOAT_TOL");
  long double value = raw ? std::strtold(raw, nullptr) : 0.0L;
  return BcgTolerance{{"default", value, 0.0L, false}};
}}

struct BcgValue {{
  std::string type;
  long double number_value = 0.0L;
  bool bool_value = false;
  std::string string_value;
  std::vector<BcgValue> items;
  std::vector<std::pair<BcgValue, BcgValue>> pairs;

  static BcgValue null() {{ BcgValue value; value.type = "null"; return value; }}
  static BcgValue boolean(bool inner) {{ BcgValue value; value.type = "bool"; value.bool_value = inner; return value; }}
  static BcgValue number(long double inner) {{ BcgValue value; value.type = "number"; value.number_value = inner; return value; }}
  static BcgValue number(const std::string& inner) {{ return number(std::strtold(inner.c_str(), nullptr)); }}
  static BcgValue string(const std::string& inner) {{ BcgValue value; value.type = "string"; value.string_value = inner; return value; }}
  static BcgValue array(std::vector<BcgValue> inner) {{ BcgValue value; value.type = "array"; value.items = std::move(inner); return value; }}
  static BcgValue set(std::vector<BcgValue> inner) {{ BcgValue value; value.type = "set"; value.items = std::move(inner); return value; }}
  static BcgValue deque(std::vector<BcgValue> inner) {{ BcgValue value; value.type = "deque"; value.items = std::move(inner); return value; }}
  static BcgValue dict(std::vector<std::pair<BcgValue, BcgValue>> inner) {{ BcgValue value; value.type = "dict"; value.pairs = std::move(inner); return value; }}
  static BcgValue counter(std::vector<std::pair<BcgValue, BcgValue>> inner) {{ BcgValue value; value.type = "counter"; value.pairs = std::move(inner); return value; }}
}};

bool bcg_should_run(const std::string& id) {{
  const char* raw = std::getenv("{SELECTED_IDS_ENV}");
  if (!raw || !*raw) return true;
  return std::string(raw).find("\\"" + id + "\\"") != std::string::npos;
}}

template <typename T>
T bcg_complete(T value) {{ return value; }}

template <typename T>
T bcg_complete(std::future<T> value) {{ return value.get(); }}

template <typename T>
T bcg_complete(std::shared_future<T> value) {{ return value.get(); }}

bool bcg_numeric(const BcgValue& value) {{
  return value.type == "number";
}}

bool bcg_equal(const BcgValue& expected, const BcgValue& actual, const BcgTolerance& tolerance);

bool bcg_equal_unordered(const std::vector<BcgValue>& expected, const std::vector<BcgValue>& actual, const BcgTolerance& tolerance) {{
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  for (const auto& expected_item : expected) {{
    bool matched = false;
    for (std::size_t index = 0; index < actual.size(); ++index) {{
      if (!used[index] && bcg_equal(expected_item, actual[index], tolerance)) {{
        used[index] = true;
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

bool bcg_equal_pairs(const std::vector<std::pair<BcgValue, BcgValue>>& expected, const std::vector<std::pair<BcgValue, BcgValue>>& actual, const BcgTolerance& tolerance) {{
  if (expected.size() != actual.size()) return false;
  std::vector<bool> used(actual.size(), false);
  BcgTolerance exact{{"default", 0.0L, 0.0L, false}};
  for (const auto& expected_pair : expected) {{
    bool matched = false;
    for (std::size_t index = 0; index < actual.size(); ++index) {{
      if (!used[index] && bcg_equal(expected_pair.first, actual[index].first, exact) && bcg_equal(expected_pair.second, actual[index].second, tolerance)) {{
        used[index] = true;
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

bool bcg_equal(const BcgValue& expected, const BcgValue& actual, const BcgTolerance& tolerance) {{
  if (bcg_numeric(expected) && bcg_numeric(actual)) {{
    long double diff = std::fabs(expected.number_value - actual.number_value);
    if (tolerance.mode == "absdiff" && tolerance.strict) return diff < tolerance.abs;
    long double limit = std::max(tolerance.abs, tolerance.rel * std::max(std::fabs(expected.number_value), std::fabs(actual.number_value)));
    return diff <= limit;
  }}
  if (expected.type != actual.type) return false;
  if (expected.type == "null") return true;
  if (expected.type == "bool") return expected.bool_value == actual.bool_value;
  if (expected.type == "string") return expected.string_value == actual.string_value;
  if (expected.type == "array" || expected.type == "deque") {{
    if (expected.items.size() != actual.items.size()) return false;
    for (std::size_t index = 0; index < expected.items.size(); ++index) {{
      if (!bcg_equal(expected.items[index], actual.items[index], tolerance)) return false;
    }}
    return true;
  }}
  if (expected.type == "set") return bcg_equal_unordered(expected.items, actual.items, tolerance);
  if (expected.type == "dict" || expected.type == "counter") return bcg_equal_pairs(expected.pairs, actual.pairs, tolerance);
  return false;
}}

bool bcg_truthy(const BcgValue& value) {{
  if (value.type == "null") return false;
  if (value.type == "bool") return value.bool_value;
  if (value.type == "number") return value.number_value != 0.0L;
  if (value.type == "string") return !value.string_value.empty();
  if (value.type == "array" || value.type == "set" || value.type == "deque") return !value.items.empty();
  if (value.type == "dict" || value.type == "counter") return !value.pairs.empty();
  return false;
}}

BcgValue bcg_normalize(const BcgValue& value) {{ return value; }}
BcgValue bcg_normalize(std::nullptr_t) {{ return BcgValue::null(); }}
BcgValue bcg_normalize(bool value) {{ return BcgValue::boolean(value); }}
BcgValue bcg_normalize(int value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(long value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(long long value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(float value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(double value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(long double value) {{ return BcgValue::number(value); }}
BcgValue bcg_normalize(const char* value) {{ return BcgValue::string(value); }}
BcgValue bcg_normalize(const std::string& value) {{ return BcgValue::string(value); }}

template <typename T>
BcgValue bcg_normalize(const std::optional<T>& value) {{
  return value.has_value() ? bcg_normalize(*value) : BcgValue::null();
}}

template <typename T>
BcgValue bcg_normalize(const std::vector<T>& value) {{
  std::vector<BcgValue> items;
  for (const auto& item : value) items.push_back(bcg_normalize(item));
  return BcgValue::array(items);
}}

template <typename T>
BcgValue bcg_normalize(const std::deque<T>& value) {{
  std::vector<BcgValue> items;
  for (const auto& item : value) items.push_back(bcg_normalize(item));
  return BcgValue::deque(items);
}}

template <typename T>
BcgValue bcg_normalize(const std::set<T>& value) {{
  std::vector<BcgValue> items;
  for (const auto& item : value) items.push_back(bcg_normalize(item));
  return BcgValue::set(items);
}}

template <typename K, typename V>
BcgValue bcg_normalize(const std::map<K, V>& value) {{
  std::vector<std::pair<BcgValue, BcgValue>> items;
  for (const auto& item : value) items.push_back({{bcg_normalize(item.first), bcg_normalize(item.second)}});
  return BcgValue::dict(items);
}}

template <typename T>
BcgValue bcg_normalize(std::future<T>& value) {{
  return bcg_normalize(value.get());
}}

template <typename T>
BcgValue bcg_normalize(std::shared_future<T>& value) {{
  return bcg_normalize(value.get());
}}

template <typename T>
bool bcg_contains(const std::vector<T>& container, const T& needle, const BcgTolerance& tolerance) {{
  for (const auto& item : container) if (bcg_equal(bcg_normalize(item), bcg_normalize(needle), tolerance)) return true;
  return false;
}}

bool bcg_contains(const std::string& container, const std::string& needle, const BcgTolerance&) {{
  return container.find(needle) != std::string::npos;
}}

template <typename T>
std::vector<T> bcg_sorted(std::vector<T> value) {{
  std::sort(value.begin(), value.end());
  return value;
}}

void bcg_print_result(const std::vector<std::string>& passed, const std::vector<std::string>& failed) {{
  std::cout << "{{\\"status\\":\\"" << (failed.empty() ? "pass" : "fail") << "\\",\\"passed\\":[";
  for (std::size_t index = 0; index < passed.size(); ++index) {{
    if (index) std::cout << ",";
    std::cout << "\\"" << passed[index] << "\\"";
  }}
  std::cout << "],\\"failed\\":[";
  for (std::size_t index = 0; index < failed.size(); ++index) {{
    if (index) std::cout << ",";
    std::cout << "\\"" << failed[index] << "\\"";
  }}
  std::cout << "]}}" << std::endl;
}}

int main() {{
  std::vector<std::string> passed;
  std::vector<std::string> failed;
{test_blocks}
  bcg_print_result(passed, failed);
  return failed.empty() ? 0 : 1;
}}
"""


def rust_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )
    test_blocks = rust_test_blocks(tests)
    return f"""// Generated by babel_code_goat.py. Requires Rust 1.70 or later.
// BCG_PAYLOAD_BEGIN
// {payload}
// BCG_PAYLOAD_END
use std::collections::{{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque}};
use std::env;
use std::future::Future;
use std::hash::Hash;
use std::panic::{{self, AssertUnwindSafe}};
use std::pin::Pin;
use std::task::{{Context, Poll, RawWaker, RawWakerVTable, Waker}};

include!(env!("BCG_SOLUTION_PATH"));

#[derive(Clone, Debug)]
enum BcgValue {{
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    Array(Vec<BcgValue>),
    Set(Vec<BcgValue>),
    Deque(Vec<BcgValue>),
    Dict(Vec<(BcgValue, BcgValue)>),
    Counter(Vec<(BcgValue, BcgValue)>),
}}

impl BcgValue {{
    fn is_truthy(&self) -> bool {{
        match self {{
            BcgValue::Null => false,
            BcgValue::Bool(value) => *value,
            BcgValue::Number(value) => *value != 0.0,
            BcgValue::String(value) => !value.is_empty(),
            BcgValue::Array(value) | BcgValue::Set(value) | BcgValue::Deque(value) => !value.is_empty(),
            BcgValue::Dict(value) | BcgValue::Counter(value) => !value.is_empty(),
        }}
    }}
}}

#[derive(Clone, Copy)]
struct BcgTolerance {{
    abs: f64,
    rel: f64,
    strict: bool,
}}

fn bcg_default_tolerance() -> BcgTolerance {{
    let abs = env::var("BABEL_CODE_GOAT_TOL").ok().and_then(|value| value.parse::<f64>().ok()).unwrap_or(0.0);
    BcgTolerance {{ abs, rel: 0.0, strict: false }}
}}

fn bcg_should_run(id: &str) -> bool {{
    let raw = match env::var("{SELECTED_IDS_ENV}") {{
        Ok(value) if !value.is_empty() => value,
        _ => return true,
    }};
    raw.contains(&format!("\\"{{}}\\"", id))
}}

fn bcg_raw_waker() -> RawWaker {{
    fn clone(_: *const ()) -> RawWaker {{ bcg_raw_waker() }}
    fn noop(_: *const ()) {{}}
    RawWaker::new(std::ptr::null(), &RawWakerVTable::new(clone, noop, noop, noop))
}}

fn bcg_block_on<F: Future>(future: F) -> F::Output {{
    let waker = unsafe {{ Waker::from_raw(bcg_raw_waker()) }};
    let mut context = Context::from_waker(&waker);
    let mut future = Box::pin(future);
    loop {{
        match Pin::as_mut(&mut future).poll(&mut context) {{
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }}
    }}
}}

trait BcgNormalize {{
    fn bcg_normalize(&self) -> BcgValue;
}}

fn bcg_normalize_value<T: BcgNormalize + ?Sized>(value: &T) -> BcgValue {{
    value.bcg_normalize()
}}

impl BcgNormalize for BcgValue {{
    fn bcg_normalize(&self) -> BcgValue {{ self.clone() }}
}}
impl BcgNormalize for () {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Null }}
}}
impl BcgNormalize for bool {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Bool(*self) }}
}}
impl BcgNormalize for i32 {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Number(*self as f64) }}
}}
impl BcgNormalize for i64 {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Number(*self as f64) }}
}}
impl BcgNormalize for usize {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Number(*self as f64) }}
}}
impl BcgNormalize for f32 {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Number(*self as f64) }}
}}
impl BcgNormalize for f64 {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::Number(*self) }}
}}
impl BcgNormalize for String {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::String(self.clone()) }}
}}
impl BcgNormalize for str {{
    fn bcg_normalize(&self) -> BcgValue {{ BcgValue::String(self.to_string()) }}
}}
impl<T: BcgNormalize> BcgNormalize for Option<T> {{
    fn bcg_normalize(&self) -> BcgValue {{
        self.as_ref().map_or(BcgValue::Null, |value| value.bcg_normalize())
    }}
}}
impl<T: BcgNormalize> BcgNormalize for Vec<T> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Array(self.iter().map(|item| item.bcg_normalize()).collect())
    }}
}}
impl<T: BcgNormalize> BcgNormalize for VecDeque<T> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Deque(self.iter().map(|item| item.bcg_normalize()).collect())
    }}
}}
impl<T: BcgNormalize + Eq + Hash> BcgNormalize for HashSet<T> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Set(self.iter().map(|item| item.bcg_normalize()).collect())
    }}
}}
impl<T: BcgNormalize + Ord> BcgNormalize for BTreeSet<T> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Set(self.iter().map(|item| item.bcg_normalize()).collect())
    }}
}}
impl<K: BcgNormalize + Eq + Hash, V: BcgNormalize> BcgNormalize for HashMap<K, V> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Dict(self.iter().map(|(key, value)| (key.bcg_normalize(), value.bcg_normalize())).collect())
    }}
}}
impl<K: BcgNormalize + Ord, V: BcgNormalize> BcgNormalize for BTreeMap<K, V> {{
    fn bcg_normalize(&self) -> BcgValue {{
        BcgValue::Dict(self.iter().map(|(key, value)| (key.bcg_normalize(), value.bcg_normalize())).collect())
    }}
}}
impl<F> BcgNormalize for F
where
    F: Future + Clone,
    F::Output: BcgNormalize,
{{
    fn bcg_normalize(&self) -> BcgValue {{
        bcg_block_on(self.clone()).bcg_normalize()
    }}
}}

fn bcg_numeric(value: &BcgValue) -> Option<f64> {{
    match value {{
        BcgValue::Number(inner) => Some(*inner),
        _ => None,
    }}
}}

fn bcg_equal(expected: &BcgValue, actual: &BcgValue, tolerance: BcgTolerance) -> bool {{
    if let (Some(expected_num), Some(actual_num)) = (bcg_numeric(expected), bcg_numeric(actual)) {{
        let diff = (expected_num - actual_num).abs();
        if tolerance.strict {{ return diff < tolerance.abs; }}
        return diff <= tolerance.abs.max(tolerance.rel * expected_num.abs().max(actual_num.abs()));
    }}
    match (expected, actual) {{
        (BcgValue::Null, BcgValue::Null) => true,
        (BcgValue::Bool(left), BcgValue::Bool(right)) => left == right,
        (BcgValue::String(left), BcgValue::String(right)) => left == right,
        (BcgValue::Array(left), BcgValue::Array(right)) | (BcgValue::Deque(left), BcgValue::Deque(right)) => {{
            left.len() == right.len() && left.iter().zip(right.iter()).all(|(l, r)| bcg_equal(l, r, tolerance))
        }}
        (BcgValue::Set(left), BcgValue::Set(right)) => bcg_equal_unordered(left, right, tolerance),
        (BcgValue::Dict(left), BcgValue::Dict(right)) | (BcgValue::Counter(left), BcgValue::Counter(right)) => bcg_equal_pairs(left, right, tolerance),
        _ => false,
    }}
}}

fn bcg_equal_unordered(expected: &[BcgValue], actual: &[BcgValue], tolerance: BcgTolerance) -> bool {{
    if expected.len() != actual.len() {{ return false; }}
    let mut used = vec![false; actual.len()];
    for expected_item in expected {{
        let mut matched = false;
        for (index, actual_item) in actual.iter().enumerate() {{
            if !used[index] && bcg_equal(expected_item, actual_item, tolerance) {{
                used[index] = true;
                matched = true;
                break;
            }}
        }}
        if !matched {{ return false; }}
    }}
    true
}}

fn bcg_equal_pairs(expected: &[(BcgValue, BcgValue)], actual: &[(BcgValue, BcgValue)], tolerance: BcgTolerance) -> bool {{
    if expected.len() != actual.len() {{ return false; }}
    let exact = BcgTolerance {{ abs: 0.0, rel: 0.0, strict: false }};
    let mut used = vec![false; actual.len()];
    for (expected_key, expected_value) in expected {{
        let mut matched = false;
        for (index, (actual_key, actual_value)) in actual.iter().enumerate() {{
            if !used[index] && bcg_equal(expected_key, actual_key, exact) && bcg_equal(expected_value, actual_value, tolerance) {{
                used[index] = true;
                matched = true;
                break;
            }}
        }}
        if !matched {{ return false; }}
    }}
    true
}}

fn bcg_contains<T: BcgNormalize>(container: &[T], needle: &T, tolerance: BcgTolerance) -> bool {{
    let needle = needle.bcg_normalize();
    container.iter().any(|item| bcg_equal(&item.bcg_normalize(), &needle, tolerance))
}}

fn bcg_sorted<T: Ord>(mut value: Vec<T>) -> Vec<T> {{
    value.sort();
    value
}}

fn bcg_panic_message(error: &(dyn std::any::Any + Send)) -> String {{
    if let Some(value) = error.downcast_ref::<&str>() {{ return (*value).to_string(); }}
    if let Some(value) = error.downcast_ref::<String>() {{ return value.clone(); }}
    String::new()
}}

fn main() {{
    let mut passed: Vec<&'static str> = Vec::new();
    let mut failed: Vec<&'static str> = Vec::new();
{test_blocks}
    print!("{{\\"status\\":\\"{{}}\\",\\"passed\\":[", if failed.is_empty() {{ "pass" }} else {{ "fail" }});
    for (index, id) in passed.iter().enumerate() {{
        if index > 0 {{ print!(","); }}
        print!("\\"{{}}\\\"", id);
    }}
    print!("],\\"failed\\":[");
    for (index, id) in failed.iter().enumerate() {{
        if index > 0 {{ print!(","); }}
        print!("\\"{{}}\\\"", id);
    }}
    println!("]}}");
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
        raise RuntimeError("unsupported language")

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
        match = re.search(r"BCG_PAYLOAD_BEGIN\s*\n//\s*(\{.*?\})\s*\n//\s*BCG_PAYLOAD_END", source, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise DiscoveryError("tester payload not found")


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


def run_compiled_tester(
    lang: str, tester: Path, solution_path: Path, env: dict[str, str], timeout_seconds: float | None = None
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="babel-code-goat-") as build_dir:
        executable = Path(build_dir) / ("tester.exe" if lang == "cpp" else "tester")
        if lang == "cpp":
            compile_command = [
                "g++",
                "-std=c++17",
                f'-DBCG_SOLUTION_PATH="{solution_path.resolve().as_posix()}"',
                str(tester),
                "-o",
                str(executable),
            ]
            compile_env = env
        elif lang == "rust":
            compile_command = ["rustc", "--edition=2021", str(tester), "-o", str(executable)]
            compile_env = env.copy()
            compile_env["BCG_SOLUTION_PATH"] = str(solution_path.resolve())
        else:
            raise RuntimeError("unsupported compiled language")
        compiled = subprocess.run(compile_command, text=True, capture_output=True, check=False, env=compile_env)
        if compiled.returncode != 0:
            raise RuntimeError("compiled tester build failed")
        return subprocess.run([str(executable)], text=True, capture_output=True, check=False, env=env, timeout=timeout_seconds)


def run_tester_process(
    lang: str,
    tester: Path,
    solution_path: Path,
    env: dict[str, str],
    timeout_seconds: float | None,
) -> subprocess.CompletedProcess[str]:
    if lang == "python":
        command = [sys.executable, str(tester), str(solution_path)]
        return subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout_seconds)
    if lang in {"javascript", "typescript"}:
        command = ["node", str(tester), str(solution_path)]
        return subprocess.run(command, text=True, capture_output=True, check=False, env=env, timeout=timeout_seconds)
    completed = run_compiled_tester(lang, tester, solution_path, env, timeout_seconds)
    return completed


def parse_tester_stdout(stdout: str) -> dict[str, Any] | None:
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


def timeout_seconds_from_ms(value: int | None) -> float | None:
    if value is None:
        return None
    return max(value, 0) / 1000.0


def make_timeout_fail_result(selected_ids: list[str]) -> dict[str, Any]:
    return make_result("fail", [], selected_ids)


def command_test(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED_LANGS:
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
    if args.run is not None and args.run not in set(discovered_ids):
        return print_result(RESULT_ERROR)
    selected_ids = [args.run] if args.run is not None else discovered_ids
    if args.list_tests:
        return print_result(make_result("pass", discovered_ids, []))

    try:
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent)
        env["BABEL_CODE_GOAT_ROOT"] = root
        env["BABEL_CODE_GOAT_TOL"] = str(args.tol)
        env[TIMEOUT_MS_ENV] = "" if args.timeout_ms is None else str(args.timeout_ms)
        env[TOTAL_TIMEOUT_MS_ENV] = "" if args.total_timeout_ms is None else str(args.total_timeout_ms)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        solution_path = Path(args.solution_path)
        total_timeout = timeout_seconds_from_ms(args.total_timeout_ms)
        per_test_timeout = timeout_seconds_from_ms(args.timeout_ms)
        if per_test_timeout is not None:
            passed: list[str] = []
            failed: list[str] = []
            deadline = None if total_timeout is None else time.monotonic() + total_timeout
            for index, test_id in enumerate(selected_ids):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    failed.extend(selected_ids[index:])
                    break
                run_timeout = per_test_timeout if remaining is None else min(per_test_timeout, remaining)
                env[SELECTED_IDS_ENV] = json.dumps([test_id], separators=(",", ":"))
                try:
                    completed = run_tester_process(args.lang, tester, solution_path, env, run_timeout)
                except subprocess.TimeoutExpired:
                    failed.append(test_id)
                    continue
                result = parse_tester_stdout(completed.stdout)
                if result is None or result["status"] == "error":
                    return print_result(RESULT_ERROR)
                passed.extend([item for item in result["passed"] if item == test_id])
                if test_id not in passed:
                    failed.append(test_id)
                elif test_id in result["failed"]:
                    failed.append(test_id)
                    passed = [item for item in passed if item != test_id]
            return print_result(make_result("pass" if not failed else "fail", passed, failed))

        env[SELECTED_IDS_ENV] = json.dumps(selected_ids, separators=(",", ":"))
        try:
            completed = run_tester_process(args.lang, tester, solution_path, env, total_timeout)
        except subprocess.TimeoutExpired:
            return print_result(make_timeout_fail_result(selected_ids))
    except Exception:
        return print_result(RESULT_ERROR)

    result = parse_tester_stdout(completed.stdout)
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
    test.add_argument("--run")
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
