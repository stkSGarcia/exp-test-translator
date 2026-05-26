#!/usr/bin/env python3
"""babel_code_goat.py — test-harness translation engine and runner.

Requires Python 3.9+.

Commands:
  generate <tests_dir> --entrypoint <name> --lang <python|javascript|typescript>
  test     <solution>  <tests_dir> --lang <python|javascript|typescript>
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: str                          # temporary: raw line number; final: "tests.py:<n>[#k]"
    kind: Literal["eq", "ne", "truthy", "falsy", "raises", "in", "loop_pass", "loop_fail"]
    args: list[Any]
    expected: Any = None
    expect_stdout: str | None = None
    expect_stderr: str | None = None
    tol_abs: float | None = None
    tol_rel: float | None = None
    tol_strict: bool = True          # True = strict (<), False = non-strict (<=)
    exc_type: str | None = None      # e.g. "ValueError" for typed raises
    msg_contains: str | None = None
    msg_regex: str | None = None
    transform: str | None = None


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _ast_to_value(node: ast.expr, bindings: dict | None = None) -> Any:
    """Evaluate a constant-valued AST node to a Python value."""
    if bindings and isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_ast_to_value(e, bindings) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return ("__tuple__", [_ast_to_value(e, bindings) for e in node.elts])
    if isinstance(node, ast.Set):
        return ("__set__", [_ast_to_value(e, bindings) for e in node.elts])
    if isinstance(node, ast.Dict):
        keys = [_ast_to_value(k, bindings) for k in node.keys]
        vals = [_ast_to_value(v, bindings) for v in node.values]
        return ("__dict__", keys, vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _ast_to_value(node.operand, bindings)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and bindings is not None:
        left = _ast_to_value(node.left, bindings)
        right = _ast_to_value(node.right, bindings)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.FloorDiv): return left // right
        if isinstance(node.op, ast.Mod): return left % right
    if isinstance(node, ast.Subscript) and bindings is not None:
        obj = _ast_to_value(node.value, bindings)
        idx = _ast_to_value(node.slice, bindings)
        if isinstance(obj, list):
            return obj[int(idx)]
        if isinstance(obj, tuple) and obj and obj[0] == "__tuple__":
            return obj[1][int(idx)]
    # Call nodes: frozenset({...}), Counter(...), deque(...), defaultdict(...), Decimal(...)
    if isinstance(node, ast.Call):
        return _ast_call_to_value(node, bindings)
    raise ValueError(f"Unsupported value in tests.py: {ast.dump(node)}")


def _ast_call_to_value(node: ast.Call, bindings: dict | None = None) -> Any:
    """Handle recognised stdlib call patterns as values."""
    func = node.func
    name = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        name = func.attr  # e.g. collections.Counter → "Counter"

    if name == "frozenset":
        inner = node.args[0] if node.args else ast.Set(elts=[])
        elts = _ast_to_value(inner, bindings)
        # inner may be a set literal → ("__set__", [...]) or a list
        items = elts[1] if isinstance(elts, tuple) and elts[0] == "__set__" else elts
        return ("__frozenset__", items)
    if name == "Counter":
        if node.args:
            arg = _ast_to_value(node.args[0], bindings)
        elif node.keywords:
            arg = ("__dict__",
                   [kw.arg for kw in node.keywords],
                   [_ast_to_value(kw.value, bindings) for kw in node.keywords])
        else:
            arg = ("__dict__", [], [])
        return ("__counter__", arg)
    if name == "deque":
        inner = _ast_to_value(node.args[0], bindings) if node.args else []
        return ("__deque__", inner)
    if name == "defaultdict":
        # defaultdict(factory, {...}) — we ignore factory
        if len(node.args) >= 2:
            inner = _ast_to_value(node.args[1], bindings)
        elif node.keywords:
            inner = ("__dict__",
                     [kw.arg for kw in node.keywords],
                     [_ast_to_value(kw.value, bindings) for kw in node.keywords])
        else:
            inner = ("__dict__", [], [])
        return ("__defaultdict__", inner)
    if name == "Decimal":
        raw = _ast_to_value(node.args[0], bindings) if node.args else "0"
        return ("__decimal__", str(raw))
    if name == "len" and node.args:
        v = _ast_to_value(node.args[0], bindings)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, str):
            return len(v)
        if isinstance(v, tuple) and v and v[0] in (
            "__tuple__", "__set__", "__frozenset__", "__deque__"
        ):
            return len(v[1])
    if name == "range" and node.args and bindings is not None:
        r_args = [_ast_to_value(a, bindings) for a in node.args]
        if all(isinstance(a, int) for a in r_args):
            return list(range(*r_args))
    raise ValueError(f"Unsupported call in tests.py: {ast.dump(node)}")


def _collect_ep_args(call: ast.Call, bindings: dict | None) -> list[Any]:
    """Collect positional args from an entrypoint call, expanding *name starred args."""
    result = []
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            val = _ast_to_value(arg.value, bindings or {})
            if isinstance(val, list):
                result.extend(val)
            elif isinstance(val, tuple) and val and val[0] == "__tuple__":
                result.extend(val[1])
            elif isinstance(val, tuple):
                result.extend(val)
            else:
                raise ValueError(f"Cannot expand starred: {val!r}")
        else:
            result.append(_ast_to_value(arg, bindings))
    return result


def _to_json_value(v: Any) -> Any:
    """Recursively normalise to JSON-safe tagged form."""
    if isinstance(v, tuple):
        tag = v[0]
        if tag == "__tuple__":
            return {"__type__": "tuple", "value": [_to_json_value(x) for x in v[1]]}
        if tag == "__set__":
            return {"__type__": "set", "value": [_to_json_value(x) for x in v[1]]}
        if tag == "__frozenset__":
            return {"__type__": "frozenset", "value": [_to_json_value(x) for x in v[1]]}
        if tag == "__dict__":
            keys, vals = v[1], v[2]
            return {"__type__": "dict",
                    "keys": [_to_json_value(k) for k in keys],
                    "values": [_to_json_value(vv) for vv in vals]}
        if tag == "__counter__":
            return {"__type__": "counter", "value": _to_json_value(v[1])}
        if tag == "__deque__":
            return {"__type__": "deque", "value": _to_json_value(v[1])}
        if tag == "__defaultdict__":
            return {"__type__": "defaultdict", "value": _to_json_value(v[1])}
        if tag == "__decimal__":
            return {"__type__": "decimal", "value": v[1]}
        # plain tuple shouldn't reach here after _ast_to_value refactor
        return [_to_json_value(x) for x in v]
    if isinstance(v, list):
        return [_to_json_value(x) for x in v]
    if isinstance(v, dict):
        # plain Python dicts only have string keys from ast.Constant
        return {k: _to_json_value(vv) for k, vv in v.items()}
    return v


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_ANNO_RE = re.compile(r"#\s*expect_(stdout|stderr):\s*(.+)")

_SUPPORTED_PRIMITIVES = frozenset({
    "sorted", "len", "list", "set", "tuple", "str", "int", "float", "abs", "sum", "min", "max"
})


def parse_tests(source: str, entrypoint: str) -> list[TestCase]:
    """Parse tests.py source and return a list of TestCase objects."""
    tree = ast.parse(source)
    lines = source.splitlines()
    raw: list[TestCase] = []
    _collect_stmts(tree.body, lines, entrypoint, raw)

    # Assign final IDs.  Raw IDs use three formats:
    #   "loop:<n>"      → loop-as-test (loop_pass / loop_fail)
    #   "iter:<n>:<k>"  → loop body assertion at iteration k
    #   str(lineno)     → unlooped assertion; dedup with #N suffix on collision
    loop_tests = [tc for tc in raw if tc.id.startswith("loop:")]
    iter_assertions = [tc for tc in raw if tc.id.startswith("iter:")]
    plain_assertions = [tc for tc in raw
                        if not tc.id.startswith("loop:") and not tc.id.startswith("iter:")]

    line_counts: dict[int, int] = {}
    for tc in plain_assertions:
        n = int(tc.id)
        line_counts[n] = line_counts.get(n, 0) + 1
    line_seen: dict[int, int] = {}
    for tc in plain_assertions:
        n = int(tc.id)
        if line_counts[n] == 1:
            tc.id = f"tests.py:{n}"
        else:
            idx = line_seen.get(n, 0)
            tc.id = f"tests.py:{n}#{idx}"
            line_seen[n] = idx + 1

    for tc in loop_tests:
        n = int(tc.id[5:])  # strip "loop:"
        tc.id = f"tests.py:{n}"

    for tc in iter_assertions:
        _, n_str, k_str = tc.id.split(":", 2)
        tc.id = f"tests.py:{n_str}:{k_str}"

    return raw


def _handle_loop(
    stmt: ast.stmt, lines: list[str], ep: str, out: list[TestCase], bindings: dict
) -> None:
    # ID tagging convention:
    #   loop-as-test uses id "loop:<lineno>"
    #   loop body assertions use id "iter:<lineno>:<iteration_index>"
    loop_lineno = stmt.lineno
    iterations = _eval_loop_iterations(stmt, bindings)

    if not iterations:
        out.append(TestCase(id=f"loop:{loop_lineno}", kind="loop_fail", args=[]))
        return

    out.append(TestCase(id=f"loop:{loop_lineno}", kind="loop_pass", args=[]))

    for k, iter_bindings in enumerate(iterations):
        loop_bindings = {**bindings, **iter_bindings}
        iter_out: list[TestCase] = []
        _collect_stmts(stmt.body, lines, ep, iter_out, loop_bindings)

        for tc in iter_out:
            # Rewrite plain lineno IDs to iteration-indexed form; leave loop:/iter: prefixed
            # IDs from nested loops unchanged — they carry their own independent IDs.
            if not tc.id.startswith("loop:") and not tc.id.startswith("iter:"):
                tc.id = f"iter:{tc.id}:{k}"

        out.extend(iter_out)


def _collect_stmts(
    stmts: list[ast.stmt], lines: list[str], ep: str, out: list[TestCase],
    bindings: dict | None = None,
) -> None:
    if bindings is None:
        bindings = {}
    for stmt in stmts:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            try:
                val = _ast_to_value(stmt.value, bindings)
                target = stmt.targets[0]
                if isinstance(target, ast.Name):
                    bindings[target.id] = val
                elif isinstance(target, (ast.Tuple, ast.List)):
                    _bind_target(target, val, bindings)
            except Exception:
                pass
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_stmts(stmt.body, lines, ep, out, {})
        elif isinstance(stmt, ast.ClassDef):
            _collect_stmts(stmt.body, lines, ep, out, {})
        elif isinstance(stmt, ast.If):
            _collect_stmts(stmt.body + stmt.orelse, lines, ep, out, dict(bindings))
        elif isinstance(stmt, (ast.For, ast.While)):
            _handle_loop(stmt, lines, ep, out, bindings)
        elif isinstance(stmt, ast.With):
            _collect_stmts(stmt.body, lines, ep, out, dict(bindings))
        elif isinstance(stmt, ast.Try):
            tc = _match_raises(stmt, ep, bindings)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)
            else:
                _collect_stmts(stmt.body, lines, ep, out, dict(bindings))
                for h in stmt.handlers:
                    _collect_stmts(h.body, lines, ep, out, dict(bindings))
        elif isinstance(stmt, ast.Assert):
            tc = _match_assert(stmt, ep, bindings)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)


def _is_ep_call(node: ast.expr, ep: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == ep
    )


def _match_raises(node: ast.Try, ep: str, bindings: dict | None = None) -> TestCase | None:
    """Match typed and untyped raises blocks."""
    if len(node.body) != 2 or len(node.handlers) != 1:
        return None
    h = node.handlers[0]
    if not isinstance(h.type, ast.Name):
        return None
    exc_name = h.type.id  # e.g. "Exception", "ValueError"
    s0, s1 = node.body
    if not (isinstance(s0, ast.Expr) and _is_ep_call(s0.value, ep)):
        return None
    if not (
        isinstance(s1, ast.Assert)
        and isinstance(s1.test, ast.Constant)
        and s1.test.value is False
    ):
        return None
    args = _collect_ep_args(s0.value, bindings)
    exc_type = None if exc_name == "Exception" else exc_name

    # Handler body: pass (no message check) or single assert with message check
    if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
        return TestCase(id=str(node.lineno), kind="raises", args=args, exc_type=exc_type)

    if len(h.body) == 1 and isinstance(h.body[0], ast.Assert):
        msg_contains, msg_regex = _parse_msg_assert(h.body[0], h.name)
        if msg_contains is not None or msg_regex is not None:
            return TestCase(
                id=str(node.lineno), kind="raises", args=args,
                exc_type=exc_type, msg_contains=msg_contains, msg_regex=msg_regex,
            )
    return None


def _parse_msg_assert(node: ast.Assert, exc_var: str | None) -> tuple[str | None, str | None]:
    """Extract (msg_contains, msg_regex) from `assert "x" in str(e)` or `assert re.search(...)`."""
    test = node.test

    def _is_str_e(n: ast.expr) -> bool:
        return (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "str"
            and len(n.args) == 1
            and isinstance(n.args[0], ast.Name)
            and (exc_var is None or n.args[0].id == exc_var)
        )

    # "substr" in str(e)
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1 and isinstance(test.ops[0], ast.In)
        and isinstance(test.left, ast.Constant) and isinstance(test.left.value, str)
        and _is_str_e(test.comparators[0])
    ):
        return test.left.value, None

    # re.search(r"pattern", str(e))
    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Attribute)
        and test.func.attr == "search"
        and isinstance(test.func.value, ast.Name) and test.func.value.id == "re"
        and len(test.args) >= 2
        and isinstance(test.args[0], ast.Constant) and isinstance(test.args[0].value, str)
        and _is_str_e(test.args[1])
    ):
        return None, test.args[0].value

    return None, None


def _match_assert(node: ast.Assert, ep: str, bindings: dict | None = None) -> TestCase | None:
    test = node.test

    # assert math.isclose(EP(args), expected, abs_tol=..., rel_tol=...)
    tc = _match_isclose(test, ep, node.lineno, bindings)
    if tc is not None:
        return tc

    # assert abs(EP(args) - expected) < tol  /  <= tol
    tc = _match_abs_tol(test, ep, node.lineno, bindings)
    if tc is not None:
        return tc

    # assert prim(EP(args)) == expected  /  != expected
    tc = _match_primitive_wrapped(test, ep, node.lineno, bindings)
    if tc is not None:
        return tc

    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
    ):
        op = test.ops[0]
        # assert EP(args) == expected  /  != expected  (LHS call, RHS is not also EP call)
        if (_is_ep_call(test.left, ep)
                and not _is_ep_call(test.comparators[0], ep)
                and isinstance(op, (ast.Eq, ast.NotEq))):
            args = _collect_ep_args(test.left, bindings)
            exp = _ast_to_value(test.comparators[0], bindings)
            kind: str = "eq" if isinstance(op, ast.Eq) else "ne"
            return TestCase(id=str(node.lineno), kind=kind, args=args, expected=exp)
        # assert expected == EP(args)  /  expected != EP(args)  (RHS call, LHS is not also EP call)
        if (_is_ep_call(test.comparators[0], ep)
                and not _is_ep_call(test.left, ep)
                and isinstance(op, (ast.Eq, ast.NotEq))):
            args = _collect_ep_args(test.comparators[0], bindings)
            exp = _ast_to_value(test.left, bindings)
            kind = "eq" if isinstance(op, ast.Eq) else "ne"
            return TestCase(id=str(node.lineno), kind=kind, args=args, expected=exp)
        # assert EP(args) in container
        if _is_ep_call(test.left, ep) and isinstance(op, ast.In):
            args = _collect_ep_args(test.left, bindings)
            container = _ast_to_value(test.comparators[0], bindings)
            return TestCase(id=str(node.lineno), kind="in", args=args, expected=container)

    # assert EP(args)
    if _is_ep_call(test, ep):
        return TestCase(
            id=str(node.lineno), kind="truthy",
            args=_collect_ep_args(test, bindings),
        )
    # assert not EP(args)
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and _is_ep_call(test.operand, ep)
    ):
        return TestCase(
            id=str(node.lineno), kind="falsy",
            args=_collect_ep_args(test.operand, bindings),
        )
    return None


def _match_isclose(test: ast.expr, ep: str, lineno: int, bindings: dict | None = None) -> TestCase | None:
    """Match assert math.isclose(EP(args), expected, abs_tol=..., rel_tol=...)."""
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Attribute)
        and test.func.attr == "isclose"
        and isinstance(test.func.value, ast.Name) and test.func.value.id == "math"
        and len(test.args) >= 2
        and _is_ep_call(test.args[0], ep)
    ):
        return None
    args = _collect_ep_args(test.args[0], bindings)
    exp = _ast_to_value(test.args[1], bindings)
    tol_abs: float | None = None
    tol_rel: float | None = None
    for kw in test.keywords:
        if kw.arg == "abs_tol":
            tol_abs = float(_ast_to_value(kw.value, bindings))
        elif kw.arg == "rel_tol":
            tol_rel = float(_ast_to_value(kw.value, bindings))
    return TestCase(id=str(lineno), kind="eq", args=args, expected=exp,
                    tol_abs=tol_abs, tol_rel=tol_rel)


def _match_abs_tol(test: ast.expr, ep: str, lineno: int, bindings: dict | None = None) -> TestCase | None:
    """Match assert abs(EP(args) - expected) < tol  or  <= tol."""
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1 and len(test.comparators) == 1
        and isinstance(test.ops[0], (ast.Lt, ast.LtE))
    ):
        return None
    lhs = test.left
    # lhs must be abs(EP(args) - expected)
    if not (
        isinstance(lhs, ast.Call)
        and isinstance(lhs.func, ast.Name) and lhs.func.id == "abs"
        and len(lhs.args) == 1
    ):
        return None
    inner = lhs.args[0]
    if not (
        isinstance(inner, ast.BinOp)
        and isinstance(inner.op, ast.Sub)
        and _is_ep_call(inner.left, ep)
    ):
        return None
    args = _collect_ep_args(inner.left, bindings)
    exp = _ast_to_value(inner.right, bindings)
    tol_abs = float(_ast_to_value(test.comparators[0], bindings))
    strict = isinstance(test.ops[0], ast.Lt)
    return TestCase(id=str(lineno), kind="eq", args=args, expected=exp,
                    tol_abs=tol_abs, tol_strict=strict)


def _match_primitive_wrapped(test: ast.expr, ep: str, lineno: int, bindings: dict | None = None) -> TestCase | None:
    """Match assert prim(EP(args)) == expected  or  != expected."""
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
        and isinstance(test.ops[0], (ast.Eq, ast.NotEq))
    ):
        return None
    lhs = test.left
    if not (
        isinstance(lhs, ast.Call)
        and isinstance(lhs.func, ast.Name)
        and lhs.func.id in _SUPPORTED_PRIMITIVES
        and len(lhs.args) == 1
        and not lhs.keywords
        and _is_ep_call(lhs.args[0], ep)
    ):
        return None
    transform = lhs.func.id
    args = _collect_ep_args(lhs.args[0], bindings)
    exp = _ast_to_value(test.comparators[0], bindings)
    kind: str = "eq" if isinstance(test.ops[0], ast.Eq) else "ne"
    return TestCase(id=str(lineno), kind=kind, args=args, expected=exp, transform=transform)


def _attach_annotations(tc: TestCase, lineno: int, lines: list[str]) -> None:
    """Scan backwards from the line before lineno for expect_stdout/stderr annotations."""
    i = lineno - 2  # 0-indexed line immediately before the test
    while i >= 0:
        m = _ANNO_RE.match(lines[i].strip())
        if not m:
            break
        kind, raw_val = m.group(1), m.group(2).strip()
        parsed: str = ast.literal_eval(raw_val)
        if kind == "stdout" and tc.expect_stdout is None:
            tc.expect_stdout = parsed
        elif kind == "stderr" and tc.expect_stderr is None:
            tc.expect_stderr = parsed
        i -= 1


# ---------------------------------------------------------------------------
# Loop evaluation helpers
# ---------------------------------------------------------------------------

def _eval_expr(node: ast.expr, bindings: dict) -> Any:
    """Evaluate expression to a plain Python value (used for while-loop simulation)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in bindings:
            raise ValueError(f"Unknown variable: {node.id!r}")
        return bindings[node.id]
    if isinstance(node, ast.List):
        return [_eval_expr(e, bindings) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_expr(e, bindings) for e in node.elts)
    if isinstance(node, ast.Subscript):
        obj = _eval_expr(node.value, bindings)
        idx = _eval_expr(node.slice, bindings)
        return obj[int(idx)]
    if isinstance(node, ast.UnaryOp):
        v = _eval_expr(node.operand, bindings)
        if isinstance(node.op, ast.USub): return -v
        if isinstance(node.op, ast.Not): return not v
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _eval_expr(node.left, bindings)
        right = _eval_expr(node.right, bindings)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.FloorDiv): return left // right
        if isinstance(node.op, ast.Mod): return left % right
        raise ValueError(f"Unsupported binary op: {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval_expr(node.left, bindings)
        for op, comp_node in zip(node.ops, node.comparators):
            right = _eval_expr(comp_node, bindings)
            if isinstance(op, ast.Lt): cmp = left < right
            elif isinstance(op, ast.LtE): cmp = left <= right
            elif isinstance(op, ast.Gt): cmp = left > right
            elif isinstance(op, ast.GtE): cmp = left >= right
            elif isinstance(op, ast.Eq): cmp = left == right
            elif isinstance(op, ast.NotEq): cmp = left != right
            else: raise ValueError(f"Unsupported compare op: {type(op).__name__}")
            if not cmp: return False
            left = right
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn_name = node.func.id
        if fn_name == "len":
            return len(_eval_expr(node.args[0], bindings))
        if fn_name == "range":
            r_args = [int(_eval_expr(a, bindings)) for a in node.args]
            return list(range(*r_args))
    raise ValueError(f"Cannot evaluate: {ast.dump(node)}")


def _bind_target(target: ast.expr, val: Any, bindings: dict) -> None:
    """Bind loop target variable(s), handling tuple/list destructuring."""
    if isinstance(target, ast.Name):
        bindings[target.id] = val
    elif isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(val, tuple) and val and val[0] == "__tuple__":
            items: list = val[1]
        elif isinstance(val, (list, tuple)):
            items = list(val)
        else:
            raise ValueError(f"Cannot unpack {val!r} into {ast.dump(target)}")
        if len(target.elts) != len(items):
            raise ValueError(
                f"Unpack mismatch: {len(items)} values for {len(target.elts)} targets"
            )
        for sub_t, sub_v in zip(target.elts, items):
            _bind_target(sub_t, sub_v, bindings)


def _eval_iterable_items(node: ast.expr, bindings: dict) -> list:
    """Evaluate an iterable AST node to a list of internally-encoded items."""
    val = _ast_to_value(node, bindings)
    if isinstance(val, list):
        return val
    if isinstance(val, tuple) and val and val[0] == "__tuple__":
        return val[1]
    raise ValueError(f"Not iterable: {val!r}")


def _eval_for_iterations(stmt: ast.For, bindings: dict) -> list[dict]:
    """Return one binding-dict per for-loop iteration."""
    iter_node = stmt.iter

    # enumerate(iterable) or enumerate(iterable, start)
    if (
        isinstance(iter_node, ast.Call)
        and isinstance(iter_node.func, ast.Name)
        and iter_node.func.id == "enumerate"
    ):
        inner_items = _eval_iterable_items(iter_node.args[0], bindings)
        start_node = iter_node.args[1] if len(iter_node.args) > 1 else ast.Constant(value=0)
        start = _ast_to_value(start_node, bindings)
        if not isinstance(start, int):
            raise ValueError("enumerate start must be int")
        items: list = [("__tuple__", [start + i, item]) for i, item in enumerate(inner_items)]
    else:
        items = _eval_iterable_items(iter_node, bindings)

    result = []
    for item in items:
        iter_bindings: dict = {}
        _bind_target(stmt.target, item, iter_bindings)
        result.append(iter_bindings)
    return result


def _eval_while_iterations(stmt: ast.While, outer_bindings: dict) -> list[dict]:
    """Simulate a simple while loop; return one binding-dict per iteration.

    Assign statements update both sim_bindings and the per-iteration snapshot.
    AugAssign statements (typically loop counters) update only sim_bindings so
    that the snapshot reflects pre-increment state when assertions run.
    """
    _MAX_ITER = 1000
    sim_bindings = dict(outer_bindings)
    iterations = []

    for _ in range(_MAX_ITER):
        if not _eval_expr(stmt.test, sim_bindings):
            break

        # Snapshot starts from current state; updated by Assign but not AugAssign.
        iter_snapshot: dict = dict(sim_bindings)

        for body_stmt in stmt.body:
            if isinstance(body_stmt, ast.Assign) and len(body_stmt.targets) == 1:
                val = _eval_expr(body_stmt.value, sim_bindings)
                target = body_stmt.targets[0]
                if isinstance(target, ast.Name):
                    sim_bindings[target.id] = val
                    iter_snapshot[target.id] = val
                elif isinstance(target, (ast.Tuple, ast.List)):
                    _bind_target(target, val, sim_bindings)
                    _bind_target(target, val, iter_snapshot)
                else:
                    raise ValueError(f"Unsupported assign target: {ast.dump(target)}")
            elif isinstance(body_stmt, ast.AugAssign) and isinstance(body_stmt.target, ast.Name):
                old = sim_bindings.get(body_stmt.target.id)
                delta = _eval_expr(body_stmt.value, sim_bindings)
                op = body_stmt.op
                if isinstance(op, ast.Add): sim_bindings[body_stmt.target.id] = old + delta
                elif isinstance(op, ast.Sub): sim_bindings[body_stmt.target.id] = old - delta
                elif isinstance(op, ast.Mult): sim_bindings[body_stmt.target.id] = old * delta
                else: raise ValueError(f"Unsupported augassign: {type(op).__name__}")
                # AugAssign intentionally NOT applied to iter_snapshot (loop counter)
            elif isinstance(body_stmt, ast.Assert):
                pass  # skip during simulation
            else:
                raise ValueError(f"Cannot simulate: {type(body_stmt).__name__}")

        iterations.append(iter_snapshot)

    return iterations


def _eval_loop_iterations(stmt: ast.stmt, bindings: dict) -> list[dict]:
    """Dispatch to for/while iteration evaluator; return [] on any failure."""
    try:
        if isinstance(stmt, ast.For):
            return _eval_for_iterations(stmt, bindings)
        if isinstance(stmt, ast.While):
            return _eval_while_iterations(stmt, bindings)
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Code generators
# ---------------------------------------------------------------------------

def emit_python(cases: list[TestCase], entrypoint: str) -> str:
    cases_data = [
        {"id": tc.id, "kind": tc.kind,
         "args": _to_json_value(tc.args), "expected": _to_json_value(tc.expected),
         "expOut": tc.expect_stdout, "expErr": tc.expect_stderr,
         "tolAbs": tc.tol_abs, "tolRel": tc.tol_rel, "tolStrict": tc.tol_strict,
         "excType": tc.exc_type, "msgContains": tc.msg_contains, "msgRegex": tc.msg_regex,
         "transform": tc.transform}
        for tc in cases
    ]
    cases_repr = repr(json.dumps(cases_data))
    ep_repr = json.dumps(entrypoint)

    return f"""\
#!/usr/bin/env python3
import sys, json, os, io, re, contextlib, importlib.util
from decimal import Decimal
from collections import Counter, deque, defaultdict

ENTRYPOINT = {ep_repr}
CASES = json.loads({cases_repr})

def _decode(v):
    if not isinstance(v, dict) or "__type__" not in v:
        if isinstance(v, list):
            return [_decode(x) for x in v]
        return v
    t = v["__type__"]
    if t == "tuple":
        return tuple(_decode(x) for x in v["value"])
    if t == "set":
        return set(_decode(x) for x in v["value"])
    if t == "frozenset":
        return frozenset(_decode(x) for x in v["value"])
    if t == "dict":
        return {{_decode(k): _decode(val) for k, val in zip(v["keys"], v["values"])}}
    if t == "counter":
        return Counter(_decode(v["value"]))
    if t == "deque":
        return deque(_decode(x) for x in v["value"])
    if t == "defaultdict":
        d = defaultdict(None)
        d.update(_decode(v["value"]))
        return d
    if t == "decimal":
        return Decimal(v["value"])
    return v

def _near(a, b, tol_abs, tol_rel, strict):
    try:
        diff = abs(float(a) - float(b))
        limit = tol_abs if tol_abs is not None else 0.0
        if tol_rel is not None:
            limit = max(limit, tol_rel * max(abs(float(a)), abs(float(b))))
        return diff < limit if strict else diff <= limit
    except (TypeError, ValueError):
        return False

def _deep_eq(a, b, tol_abs=None, tol_rel=None, strict=True):
    if tol_abs is not None or tol_rel is not None:
        if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
            return _near(a, b, tol_abs, tol_rel, strict)
    if isinstance(a, set) and isinstance(b, set):
        return (len(a) == len(b) and
                all(any(_deep_eq(x, y, tol_abs, tol_rel, strict) for y in b) for x in a))
    if isinstance(a, (frozenset, set)) and isinstance(b, (frozenset, set)):
        return (len(a) == len(b) and
                all(any(_deep_eq(x, y, tol_abs, tol_rel, strict) for y in b) for x in a))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_eq(x, y, tol_abs, tol_rel, strict) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_eq(a[k], b[k], tol_abs, tol_rel, strict) for k in a)
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b

_TRANSFORMS = {{"sorted": sorted, "len": len, "list": list, "set": set, "tuple": tuple,
                "str": str, "int": int, "float": float, "abs": abs, "sum": sum,
                "min": min, "max": max}}

def _load_fn(sol_path, name):
    spec = importlib.util.spec_from_file_location("_sol", sol_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    obj = getattr(mod, name)
    if isinstance(obj, type):
        return getattr(obj(), name)
    return obj

def _run():
    sol_path = sys.argv[1]
    results_path = os.environ["_BCG_RESULTS_FILE"]
    global_tol = float(os.environ["_BCG_TOL"]) if "_BCG_TOL" in os.environ else None
    try:
        fn = _load_fn(sol_path, ENTRYPOINT)
    except Exception:
        with open(results_path, "w") as f:
            json.dump({{"passed": [], "failed": [c["id"] for c in CASES]}}, f)
        return
    passed, failed = [], []
    for c in CASES:
        tid = c["id"]
        kind = c["kind"]
        if kind == "loop_pass":
            passed.append(tid)
            continue
        if kind == "loop_fail":
            failed.append(tid)
            continue
        args = [_decode(a) for a in c["args"]]
        expected = _decode(c["expected"])
        exp_out, exp_err = c["expOut"], c["expErr"]
        tol_abs = c["tolAbs"] if c["tolAbs"] is not None else global_tol
        tol_rel = c["tolRel"]
        tol_strict = c["tolStrict"]
        exc_type = c["excType"]
        msg_contains = c["msgContains"]
        msg_regex = c["msgRegex"]
        transform = c["transform"]
        try:
            if kind == "raises":
                caught = None
                try:
                    fn(*args)
                    failed.append(tid)
                    continue
                except Exception as _e:
                    caught = _e
                ok = True
                if exc_type is not None:
                    ok = type(caught).__name__ == exc_type
                if ok and msg_contains is not None:
                    ok = msg_contains in str(caught)
                if ok and msg_regex is not None:
                    ok = bool(re.search(msg_regex, str(caught)))
                (passed if ok else failed).append(tid)
                continue
            out_buf, err_buf = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                result = fn(*args)
            if transform is not None:
                result = _TRANSFORMS[transform](result)
            ok = True
            if kind == "eq":
                ok = _deep_eq(result, expected, tol_abs, tol_rel, tol_strict)
            elif kind == "ne":
                ok = not _deep_eq(result, expected, tol_abs, tol_rel, tol_strict)
            elif kind == "truthy":
                ok = bool(result)
            elif kind == "falsy":
                ok = not bool(result)
            elif kind == "in":
                ok = any(_deep_eq(result, x) for x in expected)
            if ok and exp_out is not None:
                ok = out_buf.getvalue() == exp_out
            if ok and exp_err is not None:
                ok = err_buf.getvalue() == exp_err
            (passed if ok else failed).append(tid)
        except Exception:
            failed.append(tid)
    with open(results_path, "w") as f:
        json.dump({{"passed": passed, "failed": failed}}, f)

_run()
"""


def emit_javascript(cases: list[TestCase], entrypoint: str) -> str:
    cases_json = json.dumps(
        [{"id": tc.id, "kind": tc.kind,
          "args": _to_json_value(tc.args), "expected": _to_json_value(tc.expected),
          "expectStdout": tc.expect_stdout, "expectStderr": tc.expect_stderr,
          "tolAbs": tc.tol_abs, "tolRel": tc.tol_rel, "tolStrict": tc.tol_strict,
          "excType": tc.exc_type, "msgContains": tc.msg_contains, "msgRegex": tc.msg_regex,
          "transform": tc.transform}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)

    return f"""\
'use strict';
const fs = require('fs');
const path = require('path');

const ENTRYPOINT = {ep_json};
const CASES = {cases_json};

function decode(v) {{
  if (Array.isArray(v)) return v.map(decode);
  if (v !== null && typeof v === 'object' && v.__type__) {{
    const t = v.__type__;
    if (t === 'tuple' || t === 'deque') return v.value.map(decode);
    if (t === 'set' || t === 'frozenset') return {{ __isSet: true, items: v.value.map(decode) }};
    if (t === 'dict') {{
      const o = {{}};
      for (let i = 0; i < v.keys.length; i++) o[JSON.stringify(decode(v.keys[i]))] = {{ k: decode(v.keys[i]), v: decode(v.values[i]) }};
      return {{ __isDict: true, entries: o }};
    }}
    if (t === 'counter' || t === 'defaultdict') return decode(v.value);
    if (t === 'decimal') return parseFloat(v.value);
    return v;
  }}
  return v;
}}

const _TRANSFORMS = {{
  sorted: v => {{ const a = Array.isArray(v) ? [...v] : Array.from(v); return a.sort((a, b) => typeof a === 'number' ? a - b : String(a) < String(b) ? -1 : 1); }},
  len: v => Array.isArray(v) ? v.length : (typeof v === 'string' ? v.length : Object.keys(v).length),
  list: v => Array.isArray(v) ? [...v] : Array.from(v),
  set: v => ({{ __isSet: true, items: [...new Set(v)] }}),
  tuple: v => Array.isArray(v) ? [...v] : Array.from(v),
  str: v => String(v),
  int: v => Math.trunc(Number(v)),
  float: v => Number(v),
  abs: v => Math.abs(v),
  sum: v => v.reduce((a, b) => a + b, 0),
  min: v => Math.min(...v),
  max: v => Math.max(...v),
}};

function setEq(a, b) {{
  if (a.items.length !== b.items.length) return false;
  return a.items.every(x => b.items.some(y => deepEq(x, y)));
}}

function dictEq(a, b) {{
  const ka = Object.keys(a.entries).sort(), kb = Object.keys(b.entries).sort();
  if (ka.join('\\0') !== kb.join('\\0')) return false;
  return ka.every(k => deepEq(a.entries[k].v, b.entries[k].v));
}}

function near(a, b, tolAbs, tolRel, strict) {{
  if (typeof a !== 'number' || typeof b !== 'number') return false;
  const diff = Math.abs(a - b);
  let limit = tolAbs !== null ? tolAbs : 0;
  if (tolRel !== null) limit = Math.max(limit, tolRel * Math.max(Math.abs(a), Math.abs(b)));
  return strict ? diff < limit : diff <= limit;
}}

function deepEq(a, b, tolAbs, tolRel, strict) {{
  if (tolAbs !== undefined && tolAbs !== null && typeof a === 'number' && typeof b === 'number') {{
    return near(a, b, tolAbs, tolRel !== undefined ? tolRel : null, strict !== undefined ? strict : true);
  }}
  if (a && a.__isSet && b && b.__isSet) return setEq(a, b);
  if (a && a.__isDict && b && b.__isDict) return dictEq(a, b);
  if (Array.isArray(a) && Array.isArray(b)) {{
    return a.length === b.length && a.every((x, i) => deepEq(x, b[i], tolAbs, tolRel, strict));
  }}
  if (a !== null && b !== null && typeof a === 'object' && !Array.isArray(a) &&
      typeof b === 'object' && !Array.isArray(b)) {{
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return ka.join('\\0') === kb.join('\\0') && ka.every(k => deepEq(a[k], b[k], tolAbs, tolRel, strict));
  }}
  return a === b;
}}

function loadFn(sol, name) {{
  if (sol && typeof sol[name] === 'function') {{
    try {{
      const inst = new sol[name]();
      if (typeof inst[name] === 'function') return (...a) => inst[name](...a);
    }} catch (e) {{}}
    return (...a) => sol[name](...a);
  }}
  if (typeof sol === 'function') return (...a) => sol(...a);
  throw new Error('Cannot resolve entrypoint: ' + name);
}}

function captureCall(fn, args) {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  process.stdout.write = c => {{ stdout += c; return true; }};
  process.stderr.write = c => {{ stderr += c; return true; }};
  let result, threw = false, thrownErr = null;
  try {{ result = fn(...args); }} catch (e) {{ threw = true; thrownErr = e; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw, thrownErr }};
}}

function run() {{
  const solPath = process.argv[2];
  const resultsPath = process.env._BCG_RESULTS_FILE;
  const globalTol = process.env._BCG_TOL !== undefined ? parseFloat(process.env._BCG_TOL) : null;
  const allIds = CASES.map(c => c.id);
  let fn;
  try {{
    const sol = require(path.resolve(solPath));
    fn = loadFn(sol, ENTRYPOINT);
  }} catch (e) {{
    fs.writeFileSync(resultsPath, JSON.stringify({{passed: [], failed: allIds}}));
    return;
  }}
  const passed = [], failed = [];
  for (const c of CASES) {{
    if (c.kind === 'loop_pass') {{ passed.push(c.id); continue; }}
    if (c.kind === 'loop_fail') {{ failed.push(c.id); continue; }}
    const args = c.args.map(decode);
    const expected = decode(c.expected);
    const tolAbs = c.tolAbs !== null ? c.tolAbs : globalTol;
    const tolRel = c.tolRel;
    const tolStrict = c.tolStrict;
    try {{
      if (c.kind === 'raises') {{
        let thrownErr = null;
        try {{ fn(...args); }} catch (e) {{ thrownErr = e; }}
        if (thrownErr === null) {{ failed.push(c.id); continue; }}
        let ok = true;
        if (c.excType !== null) ok = (thrownErr && thrownErr.constructor && thrownErr.constructor.name === c.excType) || (thrownErr && thrownErr.name === c.excType);
        if (ok && c.msgContains !== null) ok = String(thrownErr && thrownErr.message || thrownErr).includes(c.msgContains);
        if (ok && c.msgRegex !== null) ok = new RegExp(c.msgRegex).test(String(thrownErr && thrownErr.message || thrownErr));
        (ok ? passed : failed).push(c.id);
        continue;
      }}
      const {{ result: _raw, stdout, stderr, threw }} = captureCall(fn, args);
      if (threw) {{ failed.push(c.id); continue; }}
      const result = c.transform !== null ? _TRANSFORMS[c.transform](_raw) : _raw;
      let ok = true;
      if (c.kind === 'eq') ok = deepEq(result, expected, tolAbs, tolRel, tolStrict);
      else if (c.kind === 'ne') ok = !deepEq(result, expected, tolAbs, tolRel, tolStrict);
      else if (c.kind === 'truthy') ok = !!result;
      else if (c.kind === 'falsy') ok = !result;
      else if (c.kind === 'in') ok = Array.isArray(expected) ? expected.some(x => deepEq(x, result)) : (expected && expected.__isSet ? expected.items.some(x => deepEq(x, result)) : false);
      if (ok && c.expectStdout !== null) ok = stdout === c.expectStdout;
      if (ok && c.expectStderr !== null) ok = stderr === c.expectStderr;
      (ok ? passed : failed).push(c.id);
    }} catch (e) {{
      failed.push(c.id);
    }}
  }}
  fs.writeFileSync(resultsPath, JSON.stringify({{passed, failed}}));
}}

run();
"""


def emit_typescript(cases: list[TestCase], entrypoint: str) -> str:
    cases_json = json.dumps(
        [{"id": tc.id, "kind": tc.kind,
          "args": _to_json_value(tc.args), "expected": _to_json_value(tc.expected),
          "expectStdout": tc.expect_stdout, "expectStderr": tc.expect_stderr,
          "tolAbs": tc.tol_abs, "tolRel": tc.tol_rel, "tolStrict": tc.tol_strict,
          "excType": tc.exc_type, "msgContains": tc.msg_contains, "msgRegex": tc.msg_regex,
          "transform": tc.transform}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)

    return f"""\
import * as fs from 'fs';
import * as path from 'path';

const ENTRYPOINT: string = {ep_json};
interface Case {{
  id: string; kind: string; args: any[]; expected: any;
  expectStdout: string | null; expectStderr: string | null;
  tolAbs: number | null; tolRel: number | null; tolStrict: boolean;
  excType: string | null; msgContains: string | null; msgRegex: string | null;
  transform: string | null;
}}
const CASES: Case[] = {cases_json};

function decode(v: any): any {{
  if (Array.isArray(v)) return v.map(decode);
  if (v !== null && typeof v === 'object' && v.__type__) {{
    const t: string = v.__type__;
    if (t === 'tuple' || t === 'deque') return (v.value as any[]).map(decode);
    if (t === 'set' || t === 'frozenset') return {{ __isSet: true, items: (v.value as any[]).map(decode) }};
    if (t === 'dict') {{
      const o: any = {{}};
      for (let i = 0; i < v.keys.length; i++) o[JSON.stringify(decode(v.keys[i]))] = {{ k: decode(v.keys[i]), v: decode(v.values[i]) }};
      return {{ __isDict: true, entries: o }};
    }}
    if (t === 'counter' || t === 'defaultdict') return decode(v.value);
    if (t === 'decimal') return parseFloat(v.value);
    return v;
  }}
  return v;
}}

const _TRANSFORMS: Record<string, (v: any) => any> = {{
  sorted: (v: any) => {{ const a: any[] = Array.isArray(v) ? [...v] : Array.from(v); return a.sort((a: any, b: any) => typeof a === 'number' ? a - b : String(a) < String(b) ? -1 : 1); }},
  len: (v: any) => Array.isArray(v) ? v.length : (typeof v === 'string' ? v.length : Object.keys(v).length),
  list: (v: any) => Array.isArray(v) ? [...v] : Array.from(v),
  set: (v: any) => ({{ __isSet: true, items: [...new Set(v as any[])] }}),
  tuple: (v: any) => Array.isArray(v) ? [...v] : Array.from(v),
  str: (v: any) => String(v),
  int: (v: any) => Math.trunc(Number(v)),
  float: (v: any) => Number(v),
  abs: (v: any) => Math.abs(v),
  sum: (v: any) => (v as any[]).reduce((a: any, b: any) => a + b, 0),
  min: (v: any) => Math.min(...(v as number[])),
  max: (v: any) => Math.max(...(v as number[])),
}};

function near(a: number, b: number, tolAbs: number | null, tolRel: number | null, strict: boolean): boolean {{
  const diff = Math.abs(a - b);
  let limit = tolAbs !== null ? tolAbs : 0;
  if (tolRel !== null) limit = Math.max(limit, tolRel * Math.max(Math.abs(a), Math.abs(b)));
  return strict ? diff < limit : diff <= limit;
}}

function setEq(a: any, b: any): boolean {{
  if (a.items.length !== b.items.length) return false;
  return (a.items as any[]).every((x: any) => (b.items as any[]).some((y: any) => deepEq(x, y)));
}}

function dictEq(a: any, b: any): boolean {{
  const ka: string[] = Object.keys(a.entries).sort(), kb: string[] = Object.keys(b.entries).sort();
  if (ka.join('\\0') !== kb.join('\\0')) return false;
  return ka.every((k: string) => deepEq(a.entries[k].v, b.entries[k].v));
}}

function deepEq(a: any, b: any, tolAbs?: number | null, tolRel?: number | null, strict?: boolean): boolean {{
  if (tolAbs != null && typeof a === 'number' && typeof b === 'number') {{
    return near(a, b, tolAbs, tolRel !== undefined ? tolRel : null, strict !== undefined ? strict : true);
  }}
  if (a && a.__isSet && b && b.__isSet) return setEq(a, b);
  if (a && a.__isDict && b && b.__isDict) return dictEq(a, b);
  if (Array.isArray(a) && Array.isArray(b)) {{
    return a.length === b.length && (a as any[]).every((x: any, i: number) => deepEq(x, b[i], tolAbs, tolRel, strict));
  }}
  if (a !== null && b !== null && typeof a === 'object' && !Array.isArray(a) &&
      typeof b === 'object' && !Array.isArray(b)) {{
    const ka: string[] = Object.keys(a).sort(), kb: string[] = Object.keys(b).sort();
    return ka.join('\\0') === kb.join('\\0') && ka.every((k: string) => deepEq(a[k], b[k], tolAbs, tolRel, strict));
  }}
  return a === b;
}}

function loadFn(sol: any, name: string): (...args: any[]) => any {{
  if (sol && typeof sol[name] === 'function') {{
    try {{
      const inst: any = new sol[name]();
      if (typeof inst[name] === 'function') return (...a: any[]) => inst[name](...a);
    }} catch (e) {{}}
    return (...a: any[]) => sol[name](...a);
  }}
  if (typeof sol === 'function') return (...a: any[]) => sol(...a);
  throw new Error('Cannot resolve entrypoint: ' + name);
}}

function captureCall(
  fn: (...a: any[]) => any, args: any[]
): {{ result: any; stdout: string; stderr: string; threw: boolean; thrownErr: any }} {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  (process.stdout as any).write = (c: any) => {{ stdout += c; return true; }};
  (process.stderr as any).write = (c: any) => {{ stderr += c; return true; }};
  let result: any, threw = false, thrownErr: any = null;
  try {{ result = fn(...args); }} catch (e) {{ threw = true; thrownErr = e; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw, thrownErr }};
}}

function run(): void {{
  const solPath: string = process.argv[2];
  const resultsPath: string = process.env['_BCG_RESULTS_FILE']!;
  const globalTol: number | null = process.env['_BCG_TOL'] !== undefined ? parseFloat(process.env['_BCG_TOL']!) : null;
  const allIds: string[] = CASES.map((c: Case) => c.id);
  let fn: (...a: any[]) => any;
  try {{
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const sol = require(path.resolve(solPath));
    fn = loadFn(sol, ENTRYPOINT);
  }} catch (e) {{
    fs.writeFileSync(resultsPath, JSON.stringify({{passed: [], failed: allIds}}));
    return;
  }}
  const passed: string[] = [], failed: string[] = [];
  for (const c of CASES) {{
    if (c.kind === 'loop_pass') {{ passed.push(c.id); continue; }}
    if (c.kind === 'loop_fail') {{ failed.push(c.id); continue; }}
    const args: any[] = c.args.map(decode);
    const expected: any = decode(c.expected);
    const tolAbs: number | null = c.tolAbs !== null ? c.tolAbs : globalTol;
    const tolRel: number | null = c.tolRel;
    const tolStrict: boolean = c.tolStrict;
    try {{
      if (c.kind === 'raises') {{
        let thrownErr: any = null;
        try {{ fn(...args); }} catch (e) {{ thrownErr = e; }}
        if (thrownErr === null) {{ failed.push(c.id); continue; }}
        let ok = true;
        if (c.excType !== null) ok = (thrownErr && thrownErr.constructor && thrownErr.constructor.name === c.excType) || (thrownErr && thrownErr.name === c.excType);
        if (ok && c.msgContains !== null) ok = String(thrownErr && thrownErr.message !== undefined ? thrownErr.message : thrownErr).includes(c.msgContains);
        if (ok && c.msgRegex !== null) ok = new RegExp(c.msgRegex).test(String(thrownErr && thrownErr.message !== undefined ? thrownErr.message : thrownErr));
        (ok ? passed : failed).push(c.id);
        continue;
      }}
      const {{ result: _raw, stdout, stderr, threw }} = captureCall(fn, args);
      if (threw) {{ failed.push(c.id); continue; }}
      const result: any = c.transform !== null ? _TRANSFORMS[c.transform](_raw) : _raw;
      let ok = true;
      if (c.kind === 'eq') ok = deepEq(result, expected, tolAbs, tolRel, tolStrict);
      else if (c.kind === 'ne') ok = !deepEq(result, expected, tolAbs, tolRel, tolStrict);
      else if (c.kind === 'truthy') ok = !!result;
      else if (c.kind === 'falsy') ok = !result;
      else if (c.kind === 'in') ok = Array.isArray(expected) ? (expected as any[]).some((x: any) => deepEq(x, result)) : (expected && (expected as any).__isSet ? ((expected as any).items as any[]).some((x: any) => deepEq(x, result)) : false);
      if (ok && c.expectStdout !== null) ok = stdout === c.expectStdout;
      if (ok && c.expectStderr !== null) ok = stderr === c.expectStderr;
      (ok ? passed : failed).push(c.id);
    }} catch (e) {{
      failed.push(c.id);
    }}
  }}
  fs.writeFileSync(resultsPath, JSON.stringify({{passed, failed}}));
}}

run();
"""


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

_TESTER_NAMES = {
    "python": "tester.py",
    "javascript": "tester.js",
    "typescript": "tester.ts",
}

_EMITTERS = {
    "python": emit_python,
    "javascript": emit_javascript,
    "typescript": emit_typescript,
}


def cmd_generate(args: argparse.Namespace) -> int:
    tests_dir = Path(args.tests_dir)
    tests_py = tests_dir / "tests.py"
    if not tests_py.exists():
        print(f"error: {tests_py} not found", file=sys.stderr)
        return 1

    try:
        source = tests_py.read_text()
        cases = parse_tests(source, args.entrypoint)
    except Exception as e:
        print(f"error: failed to parse tests.py: {e}", file=sys.stderr)
        return 1

    code = _EMITTERS[args.lang](cases, args.entrypoint)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    tmp_path = tester_path.with_suffix(tester_path.suffix + ".tmp")
    try:
        tmp_path.write_text(code)
        tmp_path.replace(tester_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        print(f"error: failed to write tester: {e}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# test command
# ---------------------------------------------------------------------------

_ERROR_RESULT = json.dumps({"status": "error", "passed": [], "failed": []})

_SUBPROC = {
    "python": lambda tester, sol: [sys.executable, str(tester), str(sol)],
    "javascript": lambda tester, sol: ["node", str(tester), str(sol)],
    "typescript": lambda tester, sol: ["npx", "tsx", str(tester), str(sol)],
}


def _error_exit() -> int:
    print(_ERROR_RESULT)
    return 2


def cmd_test(args: argparse.Namespace) -> int:
    if args.lang not in _TESTER_NAMES:
        return _error_exit()

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    if not tester_path.exists():
        return _error_exit()

    sol_path = Path(args.solution_path)
    fd, results_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = _SUBPROC[args.lang](tester_path, sol_path)
        env = {**os.environ, "_BCG_RESULTS_FILE": results_file}
        if args.tol is not None:
            env["_BCG_TOL"] = str(args.tol)
        try:
            subprocess.run(cmd, env=env, check=False)
        except FileNotFoundError as e:
            print(f"error: subprocess not found: {e}", file=sys.stderr)
            return _error_exit()

        try:
            with open(results_file) as f:
                data = json.load(f)
            passed: list[str] = data["passed"]
            failed: list[str] = data["failed"]
        except Exception:
            return _error_exit()

        status = "fail" if failed else "pass"
        print(json.dumps({"status": status, "passed": passed, "failed": failed}))
        return 0 if status == "pass" else 1
    finally:
        try:
            os.unlink(results_file)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_VALID_LANGS = frozenset(_TESTER_NAMES)


def _lang_type(value: str) -> str:
    if value not in _VALID_LANGS:
        raise argparse.ArgumentTypeError(
            f"lang must be python/javascript/typescript, got: {value!r}"
        )
    return value


def main() -> int:
    parser = argparse.ArgumentParser(prog="babel_code_goat")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate")
    gen.add_argument("tests_dir")
    gen.add_argument("--entrypoint", required=True)
    gen.add_argument("--lang", required=True, type=_lang_type)

    tst = sub.add_parser("test")
    tst.add_argument("solution_path")
    tst.add_argument("tests_dir")
    # lang validated manually inside cmd_test so we can emit error JSON
    tst.add_argument("--lang", required=True)
    tst.add_argument("--tol", type=float, default=None)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 1
    if args.command == "generate":
        return cmd_generate(args)
    return cmd_test(args)


if __name__ == "__main__":
    sys.exit(main())
