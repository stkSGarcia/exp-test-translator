#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict, deque
import contextlib
from decimal import Decimal, InvalidOperation
from fnmatch import fnmatchcase
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
GENERATED_TESTERS = {config["tester"] for config in SUPPORTED_LANGS.values()}
TEST_LIKE_PATTERNS = ("test*.*", "*_test.*", "tests.*", "*_tests.*")


class DiscoveryError(Exception):
    pass


@dataclass(frozen=True)
class TestCase:
    id: str
    line: int
    kind: str
    args: list[Any]
    expected: Any = None
    tolerance: dict[str, Any] | None = None
    expected_exception: str | None = None
    message_match: dict[str, str] | None = None
    expression: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
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
            "variables": self.variables,
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


def is_entrypoint_call(node: ast.AST, entrypoint: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint


def referenced_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}


def direct_name_arguments(call: ast.Call) -> dict[str, dict[str, Any]]:
    variables: dict[str, dict[str, Any]] = {}
    for index, arg in enumerate(call.args):
        if isinstance(arg, ast.Name):
            variables[arg.id] = {"source": "arg", "index": index}
    return variables


def mutation_entrypoint(
    stmt: ast.stmt, entrypoint: str, context: DiscoveryContext
) -> tuple[list[Any], dict[str, dict[str, Any]]] | None:
    if isinstance(stmt, ast.Expr) and is_entrypoint_call(stmt.value, entrypoint):
        return parse_entrypoint_call(stmt.value, entrypoint, context), direct_name_arguments(stmt.value)
    if (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and is_entrypoint_call(stmt.value, entrypoint)
    ):
        variables = direct_name_arguments(stmt.value)
        variables[stmt.targets[0].id] = {"source": "return"}
        return parse_entrypoint_call(stmt.value, entrypoint, context), variables
    return None


def references_variable(node: ast.AST, variables: dict[str, dict[str, Any]]) -> bool:
    return bool(referenced_names(node) & set(variables))


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
    node: ast.AST, entrypoint: str, context: DiscoveryContext, variable_names: set[str] | None = None
) -> ExpressionBuild:
    variable_names = variable_names or set()
    if isinstance(node, ast.Name) and node.id in variable_names:
        return ExpressionBuild({"op": "var", "name": node.id}, None, 0)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == entrypoint:
        return ExpressionBuild({"op": "actual"}, parse_entrypoint_call(node, entrypoint, context), 1)

    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
        if callee in {"sorted", "abs"}:
            if node.keywords or len(node.args) != 1:
                raise DiscoveryError("unsupported primitive helper call")
            operand = expression_from_node(node.args[0], entrypoint, context, variable_names)
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
        operand = expression_from_node(node.operand, entrypoint, context, variable_names)
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
        left = expression_from_node(node.left, entrypoint, context, variable_names)
        right = expression_from_node(node.right, entrypoint, context, variable_names)
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
        values = [expression_from_node(value, entrypoint, context, variable_names) for value in node.values]
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
        left = expression_from_node(node.left, entrypoint, context, variable_names)
        right = expression_from_node(node.comparators[0], entrypoint, context, variable_names)
        args, call_count = merge_expression_args([left, right])
        return ExpressionBuild(
            {"op": "compare", "operator": operator, "left": left.expression, "right": right.expression},
            args,
            call_count,
        )

    if isinstance(node, ast.Subscript):
        if entrypoint_call_count(node, entrypoint) == 0 and not (referenced_names(node) & variable_names):
            return const_expression(node, context)
        if isinstance(node.slice, ast.Slice):
            raise DiscoveryError("unsupported slice expression")
        value = expression_from_node(node.value, entrypoint, context, variable_names)
        index = expression_from_node(node.slice, entrypoint, context, variable_names)
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


def parse_mutation_assert(
    node: ast.Assert,
    entrypoint: str,
    lines: list[str],
    context: DiscoveryContext,
    args: list[Any],
    variables: dict[str, dict[str, Any]],
) -> TestCase:
    if entrypoint_call_count(node.test, entrypoint):
        raise DiscoveryError("mutation assert must not call entrypoint")
    if not references_variable(node.test, variables):
        raise DiscoveryError("mutation assert must reference mutated variable")
    parsed = expression_from_node(node.test, entrypoint, context, set(variables))
    if parsed.call_count != 0:
        raise DiscoveryError("mutation assert must not call entrypoint")
    expect_stdout, expect_stderr = parse_expectations(lines, node.lineno)
    return TestCase(
        id="",
        line=node.lineno,
        kind="mutation",
        args=args,
        expression=parsed.expression,
        variables=variables,
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
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context.child(), in_loop))
            index += 1
        elif mutation := mutation_entrypoint(stmt, entrypoint, context):
            args, variables = mutation
            assert_index = index + 1
            if assert_index >= len(body) or not isinstance(body[assert_index], ast.Assert):
                raise DiscoveryError("mutation entrypoint call must be followed by assert")
            while assert_index < len(body) and isinstance(body[assert_index], ast.Assert):
                test_case = parse_mutation_assert(body[assert_index], entrypoint, lines, context, args, variables)
                discovered.append(
                    TestCase(
                        id=test_case.id,
                        line=test_case.line,
                        kind=test_case.kind,
                        args=test_case.args,
                        expected=test_case.expected,
                        tolerance=test_case.tolerance,
                        expected_exception=test_case.expected_exception,
                        message_match=test_case.message_match,
                        expression=test_case.expression,
                        variables=test_case.variables,
                        expect_stdout=test_case.expect_stdout,
                        expect_stderr=test_case.expect_stderr,
                        in_loop=in_loop,
                    )
                )
                assert_index += 1
            index = assert_index
        elif isinstance(stmt, ast.Assert):
            test_case = parse_assert(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    variables=test_case.variables,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
            index += 1
        elif isinstance(stmt, ast.Try):
            test_case = parse_raise_any(stmt, entrypoint, lines, context)
            discovered.append(
                TestCase(
                    id=test_case.id,
                    line=test_case.line,
                    kind=test_case.kind,
                    args=test_case.args,
                    expected=test_case.expected,
                    tolerance=test_case.tolerance,
                    expected_exception=test_case.expected_exception,
                    message_match=test_case.message_match,
                    expression=test_case.expression,
                    variables=test_case.variables,
                    expect_stdout=test_case.expect_stdout,
                    expect_stderr=test_case.expect_stderr,
                    in_loop=in_loop,
                )
            )
            index += 1
        elif isinstance(stmt, ast.For):
            discovered.extend(discover_for_loop(stmt, entrypoint, lines, context, in_loop))
            index += 1
        elif isinstance(stmt, ast.While):
            discovered.extend(discover_while_loop(stmt, entrypoint, lines, context, in_loop))
            index += 1
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


def assign_ids(test_cases: list[TestCase], source_path: str = "tests.py") -> list[TestCase]:
    counts: dict[int, int] = {}
    for test_case in test_cases:
        if not test_case.in_loop:
            counts[test_case.line] = counts.get(test_case.line, 0) + 1

    seen: dict[int, int] = {}
    loop_seen: dict[int, int] = {}
    assigned: list[TestCase] = []
    for test_case in test_cases:
        if test_case.in_loop:
            line_seen = loop_seen.get(test_case.line, 0)
            loop_seen[test_case.line] = line_seen + 1
            test_id = f"{source_path}:{test_case.line}:{line_seen}"
        else:
            line_seen = seen.get(test_case.line, 0)
            seen[test_case.line] = line_seen + 1
            test_id = f"{source_path}:{test_case.line}"
            if counts.get(test_case.line, 0) > 1:
                test_id = f"{test_id}#{line_seen}"
        assigned.append(
            TestCase(
                id=test_id,
                line=test_case.line,
                kind=test_case.kind,
                args=test_case.args,
                expected=test_case.expected,
                tolerance=test_case.tolerance,
                expected_exception=test_case.expected_exception,
                message_match=test_case.message_match,
                expression=test_case.expression,
                variables=test_case.variables,
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
                in_loop=test_case.in_loop,
            )
        )
    return assigned


def normalized_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_test_like_non_python(path: Path) -> bool:
    if path.suffix == ".py" or path.name in GENERATED_TESTERS:
        return False
    return any(fnmatchcase(path.name, pattern) for pattern in TEST_LIKE_PATTERNS)


def discover_test_files(tests_dir: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    try:
        paths = list(tests_dir.rglob("*"))
    except OSError as exc:
        raise DiscoveryError("could not read tests directory") from exc
    for path in paths:
        if not path.is_file():
            continue
        if path.name in GENERATED_TESTERS:
            continue
        if is_test_like_non_python(path):
            raise DiscoveryError(f"test-like non-Python file: {normalized_relative_path(path, tests_dir)}")
        if path.suffix == ".py":
            files.append((normalized_relative_path(path, tests_dir), path))
    return sorted(files, key=lambda item: item[0])


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    discovered: list[TestCase] = []
    for source_path, tests_path in discover_test_files(tests_dir):
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
        discovered.extend(assign_ids(discover_in_body(tree.body, entrypoint, lines, context), source_path))
    if not discovered:
        raise DiscoveryError("no tests discovered")
    return discovered


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


def evaluate_expression(
    expression: dict[str, Any], actual: Any, tolerance: dict[str, Any], variables: dict[str, Any] | None = None
) -> Any:
    op = expression.get("op")
    if op == "const":
        return expression.get("value")
    if op == "actual":
        return actual
    if op == "var":
        if variables is None or expression["name"] not in variables:
            raise RuntimeError("missing variable")
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


def build_mutation_variables(test: dict[str, Any], decoded_args: list[Any], actual: Any) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for name, source in (test.get("variables") or {}).items():
        if source.get("source") == "arg":
            variables[name] = decoded_args[source["index"]]
        elif source.get("source") == "return":
            variables[name] = actual
    return variables


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
                else:
                    raised = False
                    raised_exc = None
                    decoded_args = [decode_arg(arg) for arg in test["args"]]
                    try:
                        actual = callable_under_test(*decoded_args)
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
                elif test["kind"] == "mutation":
                    variables = build_mutation_variables(test, decoded_args, actual)
                    ok = bool(
                        evaluate_expression(
                            test["expression"], actual, tolerance_policy(test, default_tol), variables
                        )
                    )
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

function evaluateExpression(expression, actual, tolerance, variables = {{}}) {{
  if (expression.op === "const") return expression.value;
  if (expression.op === "actual") return actual;
  if (expression.op === "var") {{
    if (!Object.prototype.hasOwnProperty.call(variables, expression.name)) throw new Error("missing variable");
    return variables[expression.name];
  }}
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

function buildMutationVariables(test, decodedArgs, actual) {{
  const variables = {{}};
  for (const [name, source] of Object.entries(test.variables || {{}})) {{
    if (source.source === "arg") variables[name] = decodedArgs[source.index];
    if (source.source === "return") variables[name] = actual;
  }}
  return variables;
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
      let decodedArgs = [];
      if (test.kind === "loop") {{
        ok = !!test.expected;
      }} else {{
        try {{
          decodedArgs = test.args.map(decodeArg);
          actual = fn(...decodedArgs);
          if (actual && typeof actual.then === "function") actual = await actual;
        }} catch (error) {{
          raised = true;
          raisedError = error;
        }}
      }}
      if (test.kind === "loop") {{}}
      else if (test.kind === "raises") ok = raised && exceptionMatches(raisedError, test.expected_exception) && messageMatches(raisedError, test.message_match);
      else if (raised) ok = false;
      else if (test.kind === "mutation") ok = !!evaluateExpression(test.expression, actual, tolerancePolicy(test), buildMutationVariables(test, decodedArgs, actual));
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
class TargetType:
    kind: str
    args: tuple["TargetType", ...] = ()


TYPE_BOOL = TargetType("bool")
TYPE_INT = TargetType("int")
TYPE_FLOAT = TargetType("float")
TYPE_STRING = TargetType("string")


def optional_type(inner: TargetType) -> TargetType:
    return TargetType("optional", (inner,))


def vector_type(inner: TargetType) -> TargetType:
    return TargetType("vector", (inner,))


def map_type(key: TargetType, value: TargetType) -> TargetType:
    return TargetType("map", (key, value))


def set_type(inner: TargetType) -> TargetType:
    return TargetType("set", (inner,))


def contains_tagged_type(value: Any, type_name: str) -> bool:
    if is_tagged(value, type_name):
        return True
    if isinstance(value, dict):
        return any(contains_tagged_type(item, type_name) for item in value.values())
    if isinstance(value, list):
        return any(contains_tagged_type(item, type_name) for item in value)
    return False


def rust_supported_tests(tests: list[TestCase]) -> list[TestCase]:
    return [test for test in tests if not contains_tagged_type(test.to_jsonable(), "deque")]


def compiled_payload(entrypoint: str, tests: list[TestCase]) -> str:
    return json.dumps(
        {"entrypoint": entrypoint, "tests": [test.to_jsonable() for test in tests]},
        separators=(",", ":"),
    )


def unify_target_types(types: list[TargetType]) -> TargetType:
    concrete = [type_ for type_ in types if type_.kind != "null"]
    if not concrete:
        return optional_type(TYPE_INT)
    if len(concrete) != len(types):
        return optional_type(unify_target_types(concrete))
    if all(type_ == concrete[0] for type_ in concrete):
        return concrete[0]
    if all(type_.kind in {"int", "float"} for type_ in concrete):
        return TYPE_FLOAT
    if all(type_.kind == "optional" for type_ in concrete):
        return optional_type(unify_target_types([type_.args[0] for type_ in concrete]))
    if all(type_.kind == "vector" for type_ in concrete):
        return vector_type(unify_target_types([type_.args[0] for type_ in concrete]))
    if all(type_.kind == "set" for type_ in concrete):
        return set_type(unify_target_types([type_.args[0] for type_ in concrete]))
    if all(type_.kind == "map" for type_ in concrete):
        return map_type(
            unify_target_types([type_.args[0] for type_ in concrete]),
            unify_target_types([type_.args[1] for type_ in concrete]),
        )
    raise DiscoveryError("unsupported heterogeneous compiled value")


def infer_target_type(value: Any, *, rust: bool = False) -> TargetType:
    if value is None:
        return TargetType("null")
    if isinstance(value, bool):
        return TYPE_BOOL
    if isinstance(value, int):
        return TYPE_INT
    if isinstance(value, float):
        return TYPE_FLOAT
    if isinstance(value, str):
        return TYPE_STRING
    if isinstance(value, list):
        return vector_type(unify_target_types([infer_target_type(item, rust=rust) for item in value]))
    if is_tagged(value, "decimal"):
        return TYPE_FLOAT
    if is_tagged(value, "deque"):
        if rust:
            raise DiscoveryError("Rust deque cases must be filtered before rendering")
        return vector_type(unify_target_types([infer_target_type(item, rust=rust) for item in value["items"]]))
    if is_tagged(value, "set"):
        return set_type(unify_target_types([infer_target_type(item, rust=rust) for item in value["items"]]))
    if is_tagged(value, "counter"):
        key_type = unify_target_types([infer_target_type(key, rust=rust) for key, _ in value["items"]])
        return map_type(key_type, TYPE_INT)
    if is_tagged(value, "dict"):
        key_type = unify_target_types([infer_target_type(key, rust=rust) for key, _ in value["items"]])
        item_type = unify_target_types([infer_target_type(item, rust=rust) for _, item in value["items"]])
        return map_type(key_type, item_type)
    raise DiscoveryError(f"unsupported compiled value: {value!r}")


def cpp_type(type_: TargetType) -> str:
    if type_.kind == "bool":
        return "bool"
    if type_.kind == "int":
        return "int"
    if type_.kind == "float":
        return "long double"
    if type_.kind == "string":
        return "std::string"
    if type_.kind == "optional":
        return f"std::optional<{cpp_type(type_.args[0])}>"
    if type_.kind == "vector":
        return f"std::vector<{cpp_type(type_.args[0])}>"
    if type_.kind == "set":
        return f"std::set<{cpp_type(type_.args[0])}>"
    if type_.kind == "map":
        return f"std::map<{cpp_type(type_.args[0])}, {cpp_type(type_.args[1])}>"
    raise DiscoveryError("unsupported C++ type")


def rust_type(type_: TargetType) -> str:
    if type_.kind == "bool":
        return "bool"
    if type_.kind == "int":
        return "i32"
    if type_.kind == "float":
        return "f64"
    if type_.kind == "string":
        return "String"
    if type_.kind == "optional":
        return f"Option<{rust_type(type_.args[0])}>"
    if type_.kind == "vector":
        return f"Vec<{rust_type(type_.args[0])}>"
    if type_.kind == "set":
        return f"HashSet<{rust_type(type_.args[0])}>"
    if type_.kind == "map":
        return f"HashMap<{rust_type(type_.args[0])}, {rust_type(type_.args[1])}>"
    raise DiscoveryError("unsupported Rust type")


def cpp_literal(value: Any, type_: TargetType | None = None) -> str:
    if type_ is None:
        type_ = infer_target_type(value)
        if type_.kind == "null":
            type_ = optional_type(TYPE_INT)
    if type_.kind == "optional":
        inner = type_.args[0]
        if value is None:
            return f"{cpp_type(type_)}{{std::nullopt}}"
        return f"{cpp_type(type_)}{{{cpp_literal(value, inner)}}}"
    if value is None:
        raise DiscoveryError("null requires optional compiled type")
    if type_.kind == "bool":
        return "true" if value else "false"
    if type_.kind == "int":
        return str(int(value))
    if type_.kind == "float":
        raw = value["value"] if is_tagged(value, "decimal") else repr(float(value))
        return f"{raw}L"
    if type_.kind == "string":
        return f"std::string({json.dumps(str(value))})"
    if type_.kind == "vector":
        items = value["items"] if is_tagged(value, "deque") else value
        inner = type_.args[0]
        return f"{cpp_type(type_)}{{{', '.join(cpp_literal(item, inner) for item in items)}}}"
    if type_.kind == "set":
        inner = type_.args[0]
        return f"{cpp_type(type_)}{{{', '.join(cpp_literal(item, inner) for item in value['items'])}}}"
    if type_.kind == "map":
        key_type, item_type = type_.args
        items = value["items"]
        if is_tagged(value, "counter"):
            items = [[key, count] for key, count in value["items"]]
        return (
            f"{cpp_type(type_)}{{"
            + ", ".join(
                f"{{{cpp_literal(key, key_type)}, {cpp_literal(item, item_type)}}}" for key, item in items
            )
            + "}"
        )
    raise DiscoveryError("unsupported C++ literal")


def rust_literal(value: Any, type_: TargetType | None = None) -> str:
    if type_ is None:
        type_ = infer_target_type(value, rust=True)
        if type_.kind == "null":
            type_ = optional_type(TYPE_INT)
    if type_.kind == "optional":
        inner = type_.args[0]
        if value is None:
            return f"Option::<{rust_type(inner)}>::None"
        return f"Some({rust_literal(value, inner)})"
    if value is None:
        raise DiscoveryError("null requires optional compiled type")
    if type_.kind == "bool":
        return "true" if value else "false"
    if type_.kind == "int":
        return f"{int(value)}i32"
    if type_.kind == "float":
        raw = value["value"] if is_tagged(value, "decimal") else repr(float(value))
        return f"{raw}f64"
    if type_.kind == "string":
        return f"String::from({json.dumps(str(value))})"
    if type_.kind == "vector":
        inner = type_.args[0]
        return f"vec![{', '.join(rust_literal(item, inner) for item in value)}]"
    if type_.kind == "set":
        inner = type_.args[0]
        return f"bcg_hashset(vec![{', '.join(rust_literal(item, inner) for item in value['items'])}])"
    if type_.kind == "map":
        key_type, item_type = type_.args
        items = value["items"]
        if is_tagged(value, "counter"):
            items = [[key, count] for key, count in value["items"]]
        return (
            "bcg_hashmap(vec!["
            + ", ".join(
                f"({rust_literal(key, key_type)}, {rust_literal(item, item_type)})" for key, item in items
            )
            + "])"
        )
    raise DiscoveryError("unsupported Rust literal")


def cpp_condition_for_test(test: dict[str, Any], entrypoint: str) -> str:
    args = test.get("args") or []
    arg_types = [infer_target_type(arg) for arg in args]
    arg_exprs = [cpp_literal(arg, type_) for arg, type_ in zip(args, arg_types, strict=True)]
    call = f"{entrypoint}({', '.join(arg_exprs)})"
    tolerance = test.get("tolerance") or {"abs": "BCG_DEFAULT_TOL", "rel": 0.0, "strict": False}
    abs_tol = "BCG_DEFAULT_TOL" if tolerance.get("abs") == "BCG_DEFAULT_TOL" else repr(float(tolerance.get("abs", 0.0))) + "L"
    rel_tol = repr(float(tolerance.get("rel", 0.0))) + "L"
    strict = "true" if tolerance.get("strict") else "false"
    tol_decl = f"BcgTol tol{{{abs_tol}, {rel_tol}, {strict}}};"

    kind = test["kind"]
    if kind == "loop":
        return f"{tol_decl}\n  return {'true' if test.get('expected') else 'false'};"
    if kind == "raises":
        message = test.get("message_match") or {}
        contains = json.dumps(message.get("pattern", "")) if message.get("mode") == "contains" else '""'
        regex = json.dumps(message.get("pattern", "")) if message.get("mode") == "regex" else '""'
        return f"""{tol_decl}
  try {{
    (void){call};
    return false;
  }} catch (const std::exception& e) {{
    return bcg_message_matches(e.what(), {contains}, {regex});
  }} catch (...) {{
    return true;
  }}"""
    if kind == "truthy":
        return f"{tol_decl}\n  auto actual = {call};\n  return bcg_truthy(actual);"
    if kind == "falsy":
        return f"{tol_decl}\n  auto actual = {call};\n  return !bcg_truthy(actual);"
    if kind in {"eq", "neq"}:
        expected_type = infer_target_type(test["expected"])
        expected = cpp_literal(test["expected"], expected_type)
        comparison = f"bcg_equal(actual, {expected}, tol)"
        if kind == "neq":
            comparison = f"!({comparison})"
        return f"{tol_decl}\n  auto actual = {call};\n  return {comparison};"
    if kind in {"expr", "mutation"}:
        prefix: list[str] = [tol_decl]
        variables: dict[str, str] = {}
        call_args: list[str] = []
        if kind == "mutation":
            for index, (arg, type_) in enumerate(zip(args, arg_types, strict=True)):
                name = f"arg{index}"
                prefix.append(f"  auto {name} = {cpp_literal(arg, type_)};")
                call_args.append(name)
            for name, source in (test.get("variables") or {}).items():
                if source.get("source") == "arg":
                    variables[name] = f"arg{source['index']}"
                elif source.get("source") == "return":
                    variables[name] = "actual"
            call = f"{entrypoint}({', '.join(call_args)})"
            prefix.append(f"  auto actual = {call};")
        else:
            variables = {}
            prefix.append(f"  auto actual = {call};")
        condition = cpp_render_expression(test["expression"], variables)
        return "\n".join(prefix) + f"\n  return bcg_truthy({condition});"
    return f"{tol_decl}\n  return false;"


def cpp_render_expression(expression: dict[str, Any], variables: dict[str, str]) -> str:
    op = expression.get("op")
    if op == "const":
        return cpp_literal(expression.get("value"))
    if op == "actual":
        return "actual"
    if op == "var":
        return variables[expression["name"]]
    if op == "unary":
        operand = cpp_render_expression(expression["operand"], variables)
        return f"(!({operand}))" if expression["operator"] == "not" else f"({expression['operator']}{operand})"
    if op == "binary":
        left = cpp_render_expression(expression["left"], variables)
        right = cpp_render_expression(expression["right"], variables)
        ops = {"add": "+", "sub": "-", "mul": "*", "div": "/", "floordiv": "/", "mod": "%"}
        return f"(({left}) {ops[expression['operator']]} ({right}))"
    if op == "compare":
        left = cpp_render_expression(expression["left"], variables)
        right = cpp_render_expression(expression["right"], variables)
        operator = expression["operator"]
        if operator == "eq":
            return f"bcg_equal({left}, {right}, tol)"
        if operator == "neq":
            return f"!bcg_equal({left}, {right}, tol)"
        if operator == "in":
            return f"bcg_contains({right}, {left}, tol)"
        if operator == "not_in":
            return f"!bcg_contains({right}, {left}, tol)"
        return f"(({left}) { {'lt':'<','lte':'<=','gt':'>','gte':'>='}[operator] } ({right}))"
    if op == "index":
        value = cpp_render_expression(expression["value"], variables)
        index = cpp_render_expression(expression["index"], variables)
        return f"bcg_index({value}, {index})"
    if op == "call":
        args = [cpp_render_expression(arg, variables) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return f"bcg_sorted({args[0]})"
        if expression.get("function") == "abs":
            return f"std::abs({args[0]})"
    raise DiscoveryError("unsupported C++ expression")


def cpp_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    payload = compiled_payload(entrypoint, tests)
    test_blocks: list[str] = []
    table_entries: list[str] = []
    for index, test_case in enumerate(tests):
        test = test_case.to_jsonable()
        test_blocks.append(
            f"""bool bcg_test_{index}() {{
  try {{
  {cpp_condition_for_test(test, entrypoint)}
  }} catch (...) {{
    return false;
  }}
}}"""
        )
        table_entries.append(f'  {{"{test["id"]}", bcg_test_{index}}}')

    source = r"""/*
BCG_PAYLOAD_BEGIN
__PAYLOAD__
BCG_PAYLOAD_END
*/
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <exception>
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
#include <vector>

#ifndef BCG_SOLUTION_PATH
#error "BCG_SOLUTION_PATH must be defined"
#endif
#include BCG_SOLUTION_PATH

struct BcgTol {
  long double abs;
  long double rel;
  bool strict;
};

long double BCG_DEFAULT_TOL = []() {
  const char* raw = std::getenv("BABEL_CODE_GOAT_TOL");
  return raw ? std::strtold(raw, nullptr) : 0.0L;
}();

template <typename T> struct is_optional : std::false_type {};
template <typename T> struct is_optional<std::optional<T>> : std::true_type {};
template <typename T> struct is_vector : std::false_type {};
template <typename T, typename A> struct is_vector<std::vector<T, A>> : std::true_type {};
template <typename T> struct is_set_like : std::false_type {};
template <typename K, typename C, typename A> struct is_set_like<std::set<K, C, A>> : std::true_type {};
template <typename T> struct is_map_like : std::false_type {};
template <typename K, typename V, typename C, typename A> struct is_map_like<std::map<K, V, C, A>> : std::true_type {};
template <typename K, typename V, typename H, typename E, typename A> struct is_map_like<std::unordered_map<K, V, H, E, A>> : std::true_type {};
template <typename T> constexpr bool is_optional_v = is_optional<std::decay_t<T>>::value;
template <typename T> constexpr bool is_vector_v = is_vector<std::decay_t<T>>::value;
template <typename T> constexpr bool is_set_like_v = is_set_like<std::decay_t<T>>::value;
template <typename T> constexpr bool is_map_like_v = is_map_like<std::decay_t<T>>::value;
template <typename T> constexpr bool is_numeric_v = std::is_arithmetic_v<std::decay_t<T>> && !std::is_same_v<std::decay_t<T>, bool>;

template <typename A, typename B>
bool bcg_equal(const A& actual, const B& expected, BcgTol tol);

template <typename A, typename B>
bool bcg_numeric_equal(const A& actual, const B& expected, BcgTol tol) {
  long double left = static_cast<long double>(actual);
  long double right = static_cast<long double>(expected);
  long double diff = std::fabs(left - right);
  if (tol.strict) return diff < tol.abs;
  return diff <= std::max(tol.abs, tol.rel * std::max(std::fabs(left), std::fabs(right)));
}

template <typename A, typename B>
bool bcg_equal(const A& actual, const B& expected, BcgTol tol) {
  if constexpr (is_optional_v<A> || is_optional_v<B>) {
    if constexpr (is_optional_v<A> && is_optional_v<B>) {
      if (actual.has_value() != expected.has_value()) return false;
      return !actual.has_value() || bcg_equal(*actual, *expected, tol);
    } else {
      return false;
    }
  } else if constexpr (is_numeric_v<A> && is_numeric_v<B>) {
    return bcg_numeric_equal(actual, expected, tol);
  } else if constexpr (is_vector_v<A> && is_vector_v<B>) {
    if (actual.size() != expected.size()) return false;
    for (size_t i = 0; i < actual.size(); ++i) {
      if (!bcg_equal(actual[i], expected[i], tol)) return false;
    }
    return true;
  } else if constexpr (is_set_like_v<A> && is_set_like_v<B>) {
    if (actual.size() != expected.size()) return false;
    std::vector<bool> used(expected.size(), false);
    for (const auto& item : actual) {
      bool found = false;
      size_t index = 0;
      for (const auto& expected_item : expected) {
        if (!used[index] && bcg_equal(item, expected_item, tol)) {
          used[index] = true;
          found = true;
          break;
        }
        ++index;
      }
      if (!found) return false;
    }
    return true;
  } else if constexpr (is_map_like_v<A> && is_map_like_v<B>) {
    if (actual.size() != expected.size()) return false;
    for (const auto& [key, value] : expected) {
      bool found = false;
      for (const auto& [actual_key, actual_value] : actual) {
        if (bcg_equal(actual_key, key, BcgTol{0.0L, 0.0L, false}) && bcg_equal(actual_value, value, tol)) {
          found = true;
          break;
        }
      }
      if (!found) return false;
    }
    return true;
  } else {
    return actual == expected;
  }
}

template <typename T>
bool bcg_truthy(const T& value) {
  if constexpr (std::is_same_v<std::decay_t<T>, bool>) return value;
  else if constexpr (is_optional_v<T>) return value.has_value();
  else if constexpr (is_numeric_v<T>) return value != 0;
  else return !value.empty();
}

template <typename Container, typename Needle>
bool bcg_contains(const Container& container, const Needle& needle, BcgTol tol) {
  for (const auto& item : container) {
    if (bcg_equal(item, needle, tol)) return true;
  }
  return false;
}

template <typename K, typename V, typename Needle>
bool bcg_contains(const std::map<K, V>& container, const Needle& needle, BcgTol tol) {
  for (const auto& [key, _] : container) {
    if (bcg_equal(key, needle, tol)) return true;
  }
  return false;
}

template <typename Container, typename Index>
auto bcg_index(const Container& container, const Index& index) -> decltype(container[index]) {
  return container[index];
}

template <typename K, typename V, typename Index>
const V& bcg_index(const std::map<K, V>& container, const Index& index) {
  return container.at(index);
}

template <typename Container>
Container bcg_sorted(Container value) {
  std::sort(value.begin(), value.end());
  return value;
}

bool bcg_message_matches(const std::string& message, const std::string& contains, const std::string& regex) {
  if (!contains.empty() && message.find(contains) == std::string::npos) return false;
  if (!regex.empty() && !std::regex_search(message, std::regex(regex))) return false;
  return true;
}

__TEST_BLOCKS__

int main() {
  std::vector<std::pair<std::string, bool (*)()>> tests = {
__TABLE_ENTRIES__
  };
  std::vector<std::string> passed;
  std::vector<std::string> failed;
  for (const auto& [id, fn] : tests) {
    (fn() ? passed : failed).push_back(id);
  }
  std::cout << "{\"status\":\"" << (failed.empty() ? "pass" : "fail") << "\",\"passed\":[";
  for (size_t i = 0; i < passed.size(); ++i) {
    if (i) std::cout << ",";
    std::cout << "\"" << passed[i] << "\"";
  }
  std::cout << "],\"failed\":[";
  for (size_t i = 0; i < failed.size(); ++i) {
    if (i) std::cout << ",";
    std::cout << "\"" << failed[i] << "\"";
  }
  std::cout << "]}" << std::endl;
  return failed.empty() ? 0 : 1;
}
"""
    return (
        source.replace("__PAYLOAD__", payload)
        .replace("__TEST_BLOCKS__", "\n\n".join(test_blocks))
        .replace("__TABLE_ENTRIES__", ",\n".join(table_entries))
    )


def rust_condition_for_test(test: dict[str, Any], entrypoint: str) -> str:
    args = test.get("args") or []
    arg_types = [infer_target_type(arg, rust=True) for arg in args]
    arg_exprs = [rust_literal(arg, type_) for arg, type_ in zip(args, arg_types, strict=True)]
    tolerance = test.get("tolerance") or {}
    abs_tol = "bcg_default_tol()" if not tolerance else repr(float(tolerance.get("abs", 0.0)))
    kind = test["kind"]
    if kind == "loop":
        return f"return {'true' if test.get('expected') else 'false'};"
    if kind == "raises":
        message = test.get("message_match") or {}
        pattern = json.dumps(message.get("pattern", ""))
        mode = json.dumps(message.get("mode", ""))
        return f"""let result = std::panic::catch_unwind(|| {{ {entrypoint}({', '.join(arg_exprs)}); }});
    match result {{
        Ok(_) => false,
        Err(error) => bcg_panic_message_matches(error, {mode}, {pattern}),
    }}"""
    call = f"{entrypoint}({', '.join(arg_exprs)})"
    if kind == "truthy":
        return f"let actual = {call};\n    return bcg_truthy(&actual);"
    if kind == "falsy":
        return f"let actual = {call};\n    return !bcg_truthy(&actual);"
    if kind in {"eq", "neq"}:
        expected_type = infer_target_type(test["expected"], rust=True)
        expected = rust_literal(test["expected"], expected_type)
        if expected_type.kind in {"int", "float"}:
            comparison = f"bcg_float_equal(actual as f64, {expected} as f64, {abs_tol})"
        else:
            comparison = "actual == expected"
        if kind == "neq":
            comparison = f"!({comparison})"
        return f"let actual = {call};\n    let expected = {expected};\n    return {comparison};"
    if kind in {"expr", "mutation"}:
        lines: list[str] = []
        variables: dict[str, str] = {}
        if kind == "mutation":
            call_args: list[str] = []
            for index, (arg, type_) in enumerate(zip(args, arg_types, strict=True)):
                name = f"arg{index}"
                lines.append(f"let mut {name} = {rust_literal(arg, type_)};")
                call_args.append(f"&mut {name}")
            for name, source in (test.get("variables") or {}).items():
                if source.get("source") == "arg":
                    variables[name] = f"arg{source['index']}.clone()"
                elif source.get("source") == "return":
                    variables[name] = "actual.clone()"
            lines.append(f"let actual = {entrypoint}({', '.join(call_args)});")
        else:
            lines.append(f"let actual = {call};")
        condition = rust_render_expression(test["expression"], variables)
        return "\n    ".join(lines) + f"\n    return bcg_truthy(&({condition}));"
    return "return false;"


def rust_render_expression(expression: dict[str, Any], variables: dict[str, str]) -> str:
    op = expression.get("op")
    if op == "const":
        return rust_literal(expression.get("value"))
    if op == "actual":
        return "actual.clone()"
    if op == "var":
        return variables[expression["name"]]
    if op == "binary":
        left = rust_render_expression(expression["left"], variables)
        right = rust_render_expression(expression["right"], variables)
        ops = {"add": "+", "sub": "-", "mul": "*", "div": "/", "floordiv": "/", "mod": "%"}
        return f"(({left}) {ops[expression['operator']]} ({right}))"
    if op == "compare":
        left = rust_render_expression(expression["left"], variables)
        right = rust_render_expression(expression["right"], variables)
        operator = expression["operator"]
        if operator == "eq":
            return f"(({left}) == ({right}))"
        if operator == "neq":
            return f"(({left}) != ({right}))"
        if operator == "in":
            return f"bcg_contains(&({right}), &({left}))"
        if operator == "not_in":
            return f"!bcg_contains(&({right}), &({left}))"
        return f"(({left}) { {'lt':'<','lte':'<=','gt':'>','gte':'>='}[operator] } ({right}))"
    if op == "index":
        value = rust_render_expression(expression["value"], variables)
        index = rust_render_expression(expression["index"], variables)
        return f"({value})[{index} as usize].clone()"
    if op == "call":
        args = [rust_render_expression(arg, variables) for arg in expression["args"]]
        if expression.get("function") == "sorted":
            return f"bcg_sorted({args[0]})"
        if expression.get("function") == "abs":
            return f"({args[0]}).abs()"
    if op == "unary":
        operand = rust_render_expression(expression["operand"], variables)
        return f"!({operand})" if expression["operator"] == "not" else f"-({operand})"
    raise DiscoveryError("unsupported Rust expression")


def rust_tester_source(entrypoint: str, tests: list[TestCase]) -> str:
    tests = rust_supported_tests(tests)
    payload = compiled_payload(entrypoint, tests)
    test_blocks: list[str] = []
    table_entries: list[str] = []
    for index, test_case in enumerate(tests):
        test = test_case.to_jsonable()
        test_blocks.append(
            f"""fn bcg_test_{index}() -> bool {{
    let result = std::panic::catch_unwind(|| {{
    {rust_condition_for_test(test, entrypoint)}
    }});
    result.unwrap_or(false)
}}"""
        )
        table_entries.append(f'    ("{test["id"]}", bcg_test_{index} as fn() -> bool)')

    source = r"""/*
BCG_PAYLOAD_BEGIN
__PAYLOAD__
BCG_PAYLOAD_END
*/
use std::collections::{HashMap, HashSet};
use std::hash::Hash;

include!(env!("BCG_SOLUTION_PATH"));

fn bcg_default_tol() -> f64 {
    std::env::var("BABEL_CODE_GOAT_TOL").ok().and_then(|raw| raw.parse().ok()).unwrap_or(0.0)
}

fn bcg_float_equal(actual: f64, expected: f64, tol: f64) -> bool {
    (actual - expected).abs() <= tol
}

fn bcg_hashmap<K: Eq + Hash, V>(items: Vec<(K, V)>) -> HashMap<K, V> {
    items.into_iter().collect()
}

fn bcg_hashset<T: Eq + Hash>(items: Vec<T>) -> HashSet<T> {
    items.into_iter().collect()
}

trait BcgTruthy {
    fn bcg_truthy(&self) -> bool;
}
impl BcgTruthy for bool { fn bcg_truthy(&self) -> bool { *self } }
impl BcgTruthy for i32 { fn bcg_truthy(&self) -> bool { *self != 0 } }
impl BcgTruthy for f64 { fn bcg_truthy(&self) -> bool { *self != 0.0 } }
impl BcgTruthy for String { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T> BcgTruthy for Vec<T> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T> BcgTruthy for Option<T> { fn bcg_truthy(&self) -> bool { self.is_some() } }
impl<K, V> BcgTruthy for HashMap<K, V> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
impl<T> BcgTruthy for HashSet<T> { fn bcg_truthy(&self) -> bool { !self.is_empty() } }
fn bcg_truthy<T: BcgTruthy>(value: &T) -> bool { value.bcg_truthy() }

fn bcg_contains<T: PartialEq>(container: &Vec<T>, needle: &T) -> bool {
    container.iter().any(|item| item == needle)
}

fn bcg_sorted<T: Ord>(mut value: Vec<T>) -> Vec<T> {
    value.sort();
    value
}

fn bcg_panic_message_matches(error: Box<dyn std::any::Any + Send>, mode: &str, pattern: &str) -> bool {
    let message = if let Some(value) = error.downcast_ref::<&str>() {
        value.to_string()
    } else if let Some(value) = error.downcast_ref::<String>() {
        value.clone()
    } else {
        String::new()
    };
    if mode == "contains" {
        message.contains(pattern)
    } else if mode == "regex" {
        message.contains(pattern)
    } else {
        true
    }
}

__TEST_BLOCKS__

fn main() {
    let tests: Vec<(&str, fn() -> bool)> = vec![
__TABLE_ENTRIES__
    ];
    let mut passed: Vec<&str> = Vec::new();
    let mut failed: Vec<&str> = Vec::new();
    for (id, test_fn) in tests {
        if test_fn() {
            passed.push(id);
        } else {
            failed.push(id);
        }
    }
    let passed_json = passed.iter().map(|id| format!("\"{}\"", id)).collect::<Vec<_>>().join(",");
    let failed_json = failed.iter().map(|id| format!("\"{}\"", id)).collect::<Vec<_>>().join(",");
    let status = if failed.is_empty() { "pass" } else { "fail" };
    println!("{{\"status\":\"{}\",\"passed\":[{}],\"failed\":[{}]}}", status, passed_json, failed_json);
    std::process::exit(if failed.is_empty() { 0 } else { 1 });
}
"""
    return (
        source.replace("__PAYLOAD__", payload)
        .replace("__TEST_BLOCKS__", "\n\n".join(test_blocks))
        .replace("__TABLE_ENTRIES__", ",\n".join(table_entries))
    )


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
    marker = re.search(r"BCG_PAYLOAD_BEGIN\n(.*?)\nBCG_PAYLOAD_END", source, re.DOTALL)
    if marker:
        return json.loads(marker.group(1))
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
    raise DiscoveryError("tester payload not found")


def compiled_test_command(lang: str, tester: Path, solution_path: Path, build_dir: Path) -> list[str] | None:
    if lang == "cpp":
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            return None
        output = build_dir / "bcg_cpp_test"
        include_arg = f'-DBCG_SOLUTION_PATH="{solution_path}"'
        return [compiler, "-std=c++17", include_arg, str(tester), "-o", str(output)]
    if lang == "rust":
        compiler = shutil.which("rustc")
        if compiler is None:
            return None
        output = build_dir / "bcg_rust_test"
        return [compiler, "--edition=2021", str(tester), "-o", str(output)]
    return None


def run_compiled_tester(lang: str, tester: Path, solution_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str] | None:
    with tempfile.TemporaryDirectory(prefix="babel-code-goat-") as build_name:
        build_dir = Path(build_name)
        command = compiled_test_command(lang, tester, solution_path, build_dir)
        if command is None:
            return None
        compile_env = env.copy()
        compile_env["BCG_SOLUTION_PATH"] = str(solution_path)
        compile_result = subprocess.run(command, text=True, capture_output=True, check=False, env=compile_env)
        if compile_result.returncode != 0:
            return None
        executable = build_dir / ("bcg_cpp_test" if lang == "cpp" else "bcg_rust_test")
        return subprocess.run([str(executable)], text=True, capture_output=True, check=False, env=env)


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
    if args.lang not in SUPPORTED_LANGS:
        return print_result(RESULT_ERROR)
    tests_dir = Path(args.tests_dir)
    tester = tests_dir / SUPPORTED_LANGS[args.lang]["tester"]
    if not tester.exists():
        return print_result(RESULT_ERROR)
    try:
        payload = extract_tester_payload(tester, args.lang)
        discovered = [test.to_jsonable() for test in discover_tests(tests_dir, payload["entrypoint"])]
        if args.lang == "rust":
            discovered = [test.to_jsonable() for test in rust_supported_tests(discover_tests(tests_dir, payload["entrypoint"]))]
        if discovered != payload["tests"]:
            return print_result(RESULT_ERROR)
    except Exception:
        return print_result(RESULT_ERROR)
    try:
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent)
        env["BABEL_CODE_GOAT_ROOT"] = root
        env["BABEL_CODE_GOAT_TOL"] = str(args.tol)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        if args.lang == "python":
            command = [sys.executable, str(tester), str(Path(args.solution_path))]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
        elif args.lang in {"javascript", "typescript"}:
            command = ["node", str(tester), str(Path(args.solution_path))]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
        else:
            completed = run_compiled_tester(args.lang, tester, Path(args.solution_path), env)
            if completed is None:
                return print_result(RESULT_ERROR)
    except Exception:
        return print_result(RESULT_ERROR)

    stdout = completed.stdout
    if stdout.count("\n") != 1:
        return print_result(RESULT_ERROR)
    line = stdout.rstrip("\n")
    try:
        result = json.loads(line)
    except json.JSONDecodeError:
        return print_result(RESULT_ERROR)
    if (
        not isinstance(result, dict)
        or list(result.keys()) != ["status", "passed", "failed"]
        or result.get("status") not in {"pass", "fail", "error"}
        or not isinstance(result.get("passed"), list)
        or not isinstance(result.get("failed"), list)
    ):
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
    test.set_defaults(func=command_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
