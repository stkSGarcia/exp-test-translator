#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any


SUPPORTED_LANGS = {
    "python": {"tester": "tester.py", "runner": "python"},
    "javascript": {"tester": "tester.js", "runner": "node"},
    "typescript": {"tester": "tester.ts", "runner": "node"},
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
    expected: Any = None
    tolerance: dict[str, Any] | None = None
    expected_exception: str | None = None
    message_match: dict[str, str] | None = None
    expression: dict[str, Any] | None = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None

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
        }


@dataclass
class DiscoveryContext:
    names: dict[str, str]


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


def value_from_node(node: ast.AST, context: DiscoveryContext) -> Any:
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
    if isinstance(node, ast.Call):
        callee = resolve_callee(node.func, context)
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
    return [value_from_node(arg, context) for arg in node.args]


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

    if isinstance(node, ast.Constant | ast.List | ast.Tuple | ast.Set | ast.Dict):
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


def discover_in_body(
    body: list[ast.stmt], entrypoint: str, lines: list[str], context: DiscoveryContext
) -> list[TestCase]:
    discovered: list[TestCase] = []
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef):
            discovered.extend(discover_in_body(stmt.body, entrypoint, lines, context))
        elif isinstance(stmt, ast.Assert):
            discovered.append(parse_assert(stmt, entrypoint, lines, context))
        elif isinstance(stmt, ast.Try):
            discovered.append(parse_raise_any(stmt, entrypoint, lines, context))
        elif isinstance(stmt, ast.Pass):
            continue
        elif handle_import(stmt, context):
            continue
        else:
            raise DiscoveryError(f"unsupported code at line {getattr(stmt, 'lineno', '?')}")
    return discovered


def assign_ids(test_cases: list[TestCase]) -> list[TestCase]:
    counts: dict[int, int] = {}
    for test_case in test_cases:
        counts[test_case.line] = counts.get(test_case.line, 0) + 1

    seen: dict[int, int] = {}
    assigned: list[TestCase] = []
    for test_case in test_cases:
        line_seen = seen.get(test_case.line, 0)
        seen[test_case.line] = line_seen + 1
        test_id = f"tests.py:{test_case.line}"
        if counts[test_case.line] > 1:
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
                expect_stdout=test_case.expect_stdout,
                expect_stderr=test_case.expect_stderr,
            )
        )
    return assigned


def discover_tests(tests_dir: Path, entrypoint: str) -> list[TestCase]:
    tests_path = tests_dir / "tests.py"
    try:
        source = tests_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryError("could not read tests.py") from exc
    try:
        tree = ast.parse(source, filename="tests.py")
    except SyntaxError as exc:
        raise DiscoveryError("could not parse tests.py") from exc
    lines = source.splitlines()
    context = DiscoveryContext(names={})
    return assign_ids(discover_in_body(tree.body, entrypoint, lines, context))


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


def execute_python_tests(
    solution_path: Path, entrypoint: str, tests: list[dict[str, Any]], default_tol: float = 0.0
) -> dict[str, Any]:
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
                raised = False
                raised_exc = None
                try:
                    actual = callable_under_test(*[decode_arg(arg) for arg in test["args"]])
                except Exception as exc:
                    raised = True
                    raised_exc = exc
                    actual = None
                if test["kind"] == "raises":
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
  let fn;
  try {{
    fn = findCallable(await loadSolution(solutionPath), payload.entrypoint);
  }} catch (error) {{
    console.log(JSON.stringify({{status: "fail", passed: [], failed: payload.tests.map(test => test.id)}}));
    return 1;
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
      try {{
        actual = fn(...test.args.map(decodeArg));
        if (actual && typeof actual.then === "function") actual = await actual;
      }} catch (error) {{
        raised = true;
        raisedError = error;
      }}
      if (test.kind === "raises") ok = raised && exceptionMatches(raisedError, test.expected_exception) && messageMatches(raisedError, test.message_match);
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


def generate_tester(lang: str, entrypoint: str, tests_dir: Path) -> None:
    tests = discover_tests(tests_dir, entrypoint)
    filename = SUPPORTED_LANGS[lang]["tester"]
    if lang == "python":
        source = python_tester_source(entrypoint, tests)
    else:
        source = javascript_tester_source(entrypoint, tests)

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
    if args.lang == "python":
        command = [sys.executable, str(tester), str(Path(args.solution_path))]
    else:
        command = ["node", str(tester), str(Path(args.solution_path))]
    try:
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent)
        env["BABEL_CODE_GOAT_ROOT"] = root
        env["BABEL_CODE_GOAT_TOL"] = str(args.tol)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
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
