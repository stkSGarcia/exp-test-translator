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
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:
    import resource as _resource
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DiscoveryError(Exception):
    """Raised when test discovery constraints are violated."""


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
    mutation_check: int | None = None  # index into args to compare post-call


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


def parse_tests(source: str, entrypoint: str, file_prefix: str = "tests.py") -> list[TestCase]:
    """Parse a test source file and return a list of TestCase objects."""
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
            tc.id = f"{file_prefix}:{n}"
        else:
            idx = line_seen.get(n, 0)
            tc.id = f"{file_prefix}:{n}#{idx}"
            line_seen[n] = idx + 1

    for tc in loop_tests:
        n = int(tc.id[5:])  # strip "loop:"
        tc.id = f"{file_prefix}:{n}"

    for tc in iter_assertions:
        _, n_str, k_str = tc.id.split(":", 2)
        tc.id = f"{file_prefix}:{n_str}:{k_str}"

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


def _collect_names(node: ast.expr) -> set[str]:
    """Recursively collect all Name identifiers referenced in an AST expression."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _match_mutation_assert(
    node: ast.Assert,
    mut_names: set[str],
    arg_vals: list[Any],
    bindings: dict,
    mutation_check: int | None,
) -> TestCase | None:
    """Parse an assertion in a mutation group into a TestCase.

    mutation_check: index into arg_vals of the variable being checked post-call,
                    or None to check the return value.
    """
    test = node.test
    lineno = node.lineno

    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
        and isinstance(test.ops[0], (ast.Eq, ast.NotEq))
    ):
        op = test.ops[0]
        kind: str = "eq" if isinstance(op, ast.Eq) else "ne"
        left_is_mut = isinstance(test.left, ast.Name) and test.left.id in mut_names
        right_is_mut = (
            isinstance(test.comparators[0], ast.Name)
            and test.comparators[0].id in mut_names
        )
        if left_is_mut and not right_is_mut:
            try:
                expected = _ast_to_value(test.comparators[0], bindings)
            except Exception:
                return None
            return TestCase(id=str(lineno), kind=kind, args=arg_vals,
                            expected=expected, mutation_check=mutation_check)
        if right_is_mut and not left_is_mut:
            try:
                expected = _ast_to_value(test.left, bindings)
            except Exception:
                return None
            return TestCase(id=str(lineno), kind=kind, args=arg_vals,
                            expected=expected, mutation_check=mutation_check)

    if isinstance(test, ast.Name) and test.id in mut_names:
        return TestCase(id=str(lineno), kind="truthy", args=arg_vals,
                        mutation_check=mutation_check)

    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
        and test.operand.id in mut_names
    ):
        return TestCase(id=str(lineno), kind="falsy", args=arg_vals,
                        mutation_check=mutation_check)

    return None


def _consume_mutation_group(
    call: ast.Call,
    assigned_name: str | None,
    stmts: list[ast.stmt],
    start_idx: int,
    lines: list[str],
    out: list[TestCase],
    bindings: dict,
) -> int:
    """Process a mutation call and the immediately following assert statements.

    Returns the index of the next statement to process after the mutation group.
    Raises DiscoveryError if an assertion in the group violates mutation constraints.
    """
    arg_names: list[str | None] = []
    arg_vals: list[Any] = []
    resolvable = True
    for arg in call.args:
        if isinstance(arg, ast.Name):
            if arg.id in bindings:
                arg_names.append(arg.id)
                arg_vals.append(bindings[arg.id])
            else:
                arg_names.append(arg.id)
                arg_vals.append(None)
                resolvable = False
        else:
            try:
                arg_vals.append(_ast_to_value(arg, bindings))
            except Exception:
                arg_vals.append(None)
                resolvable = False
            arg_names.append(None)

    mut_arg_index: dict[str, int] = {
        name: idx for idx, name in enumerate(arg_names) if name is not None
    }
    all_mut_names: set[str] = set(mut_arg_index.keys())
    if assigned_name is not None:
        all_mut_names.add(assigned_name)

    # No trackable names → treat as a plain statement, not a mutation group.
    if not all_mut_names:
        return start_idx + 1

    i = start_idx + 1
    while i < len(stmts) and isinstance(stmts[i], ast.Assert):
        assert_stmt = stmts[i]
        names_in_assert = _collect_names(assert_stmt.test)

        if not names_in_assert & all_mut_names:
            raise DiscoveryError(
                f"line {assert_stmt.lineno}: assertion after mutation call does not "
                f"reference any mutation-tracked variable (tracked: {sorted(all_mut_names)})"
            )

        # Prefer an arg variable over the assigned name for mutation_check.
        mutation_check: int | None = None
        for name in names_in_assert:
            if name in mut_arg_index:
                mutation_check = mut_arg_index[name]
                break
        # If only assigned_name referenced → mutation_check stays None (check return value).

        if resolvable:
            tc = _match_mutation_assert(
                assert_stmt, all_mut_names, arg_vals, bindings, mutation_check
            )
            if tc is not None:
                _attach_annotations(tc, assert_stmt.lineno, lines)
                out.append(tc)

        i += 1

    return i


def _collect_stmts(
    stmts: list[ast.stmt], lines: list[str], ep: str, out: list[TestCase],
    bindings: dict | None = None,
) -> None:
    if bindings is None:
        bindings = {}
    i = 0
    while i < len(stmts):
        stmt = stmts[i]
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            if isinstance(stmt.targets[0], ast.Name) and _is_ep_call(stmt.value, ep):
                assigned_name = stmt.targets[0].id
                i = _consume_mutation_group(
                    stmt.value, assigned_name, stmts, i, lines, out, bindings
                )
            else:
                try:
                    val = _ast_to_value(stmt.value, bindings)
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name):
                        bindings[target.id] = val
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        _bind_target(target, val, bindings)
                except Exception:
                    pass
                i += 1
        elif isinstance(stmt, ast.Expr) and _is_ep_call(stmt.value, ep):
            i = _consume_mutation_group(
                stmt.value, None, stmts, i, lines, out, bindings
            )
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_stmts(stmt.body, lines, ep, out, {})
            i += 1
        elif isinstance(stmt, ast.ClassDef):
            _collect_stmts(stmt.body, lines, ep, out, {})
            i += 1
        elif isinstance(stmt, ast.If):
            _collect_stmts(stmt.body + stmt.orelse, lines, ep, out, dict(bindings))
            i += 1
        elif isinstance(stmt, (ast.For, ast.While)):
            _handle_loop(stmt, lines, ep, out, bindings)
            i += 1
        elif isinstance(stmt, ast.With):
            _collect_stmts(stmt.body, lines, ep, out, dict(bindings))
            i += 1
        elif isinstance(stmt, ast.Try):
            tc = _match_raises(stmt, ep, bindings)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)
            else:
                _collect_stmts(stmt.body, lines, ep, out, dict(bindings))
                for h in stmt.handlers:
                    _collect_stmts(h.body, lines, ep, out, dict(bindings))
            i += 1
        elif isinstance(stmt, ast.Assert):
            tc = _match_assert(stmt, ep, bindings)
            if tc is not None:
                _attach_annotations(tc, stmt.lineno, lines)
                out.append(tc)
            i += 1
        else:
            i += 1


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
         "transform": tc.transform, "mutationCheck": tc.mutation_check}
        for tc in cases
    ]
    cases_repr = repr(json.dumps(cases_data))
    ep_repr = json.dumps(entrypoint)
    ids_json = json.dumps([tc.id for tc in cases])

    return f"""\
#!/usr/bin/env python3
# _BCG_IDS: {ids_json}
import sys, json, os, io, re, contextlib, importlib.util, asyncio
import signal as _signal
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
        fn = getattr(obj(), name)
    else:
        fn = obj
    return fn, asyncio.iscoroutinefunction(fn)

def _call(fn, is_async, args):
    if is_async:
        return asyncio.run(fn(*args))
    return fn(*args)

def _run():
    sol_path = sys.argv[1]
    results_path = os.environ["_BCG_RESULTS_FILE"]
    global_tol = float(os.environ["_BCG_TOL"]) if "_BCG_TOL" in os.environ else None
    run_id = os.environ.get("_BCG_RUN_ID")
    cases = [c for c in CASES if c["id"] == run_id] if run_id is not None else CASES
    timeout_ms_env = os.environ.get("_BCG_TIMEOUT_MS")
    timeout_sec = float(timeout_ms_env) / 1000.0 if timeout_ms_env else None
    _has_sigalrm = hasattr(_signal, "SIGALRM")
    if timeout_sec is not None and _has_sigalrm:
        def _sigalrm_handler(signum, frame):
            raise TimeoutError("per-test timeout")
        _signal.signal(_signal.SIGALRM, _sigalrm_handler)
    def _arm():
        if timeout_sec is not None and _has_sigalrm:
            _signal.setitimer(_signal.ITIMER_REAL, timeout_sec)
    def _disarm():
        if timeout_sec is not None and _has_sigalrm:
            _signal.setitimer(_signal.ITIMER_REAL, 0)
    try:
        fn, is_async = _load_fn(sol_path, ENTRYPOINT)
    except Exception:
        with open(results_path, "w") as f:
            json.dump({{"passed": [], "failed": [c["id"] for c in cases]}}, f)
        return
    passed, failed = [], []
    for c in cases:
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
        mutation_check = c["mutationCheck"]
        try:
            if kind == "raises":
                caught = None
                _arm()
                try:
                    _call(fn, is_async, args)
                    _disarm()
                    failed.append(tid)
                    continue
                except TimeoutError:
                    failed.append(tid)
                    continue
                except Exception as _e:
                    _disarm()
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
                _arm()
                try:
                    if mutation_check is None:
                        result = _call(fn, is_async, args)
                    else:
                        _call(fn, is_async, args)
                        result = args[mutation_check]
                    _disarm()
                except TimeoutError:
                    failed.append(tid)
                    continue
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
          "transform": tc.transform, "mutationCheck": tc.mutation_check}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)
    ids_json = json.dumps([tc.id for tc in cases])

    return f"""\
'use strict';
// _BCG_IDS: {ids_json}
const fs = require('fs');
const path = require('path');

const ENTRYPOINT = {ep_json};
const CASES = {cases_json};

const _TIMEOUT_SENTINEL = Symbol('timeout');

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

async function captureCall(fn, args) {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  process.stdout.write = c => {{ stdout += c; return true; }};
  process.stderr.write = c => {{ stderr += c; return true; }};
  let result, threw = false, thrownErr = null;
  try {{ result = await fn(...args); }} catch (e) {{ threw = true; thrownErr = e; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw, thrownErr }};
}}

function withTimeout(promise, ms) {{
  if (ms === null) return promise;
  const tout = new Promise(r => setTimeout(() => r(_TIMEOUT_SENTINEL), ms));
  return Promise.race([promise, tout]);
}}

async function run() {{
  const solPath = process.argv[2];
  const resultsPath = process.env._BCG_RESULTS_FILE;
  const globalTol = process.env._BCG_TOL !== undefined ? parseFloat(process.env._BCG_TOL) : null;
  const runId = process.env._BCG_RUN_ID || null;
  const timeoutMs = process.env._BCG_TIMEOUT_MS ? parseInt(process.env._BCG_TIMEOUT_MS) : null;
  const cases = runId ? CASES.filter(c => c.id === runId) : CASES;
  const allIds = cases.map(c => c.id);
  let fn;
  try {{
    const sol = require(path.resolve(solPath));
    fn = loadFn(sol, ENTRYPOINT);
  }} catch (e) {{
    fs.writeFileSync(resultsPath, JSON.stringify({{passed: [], failed: allIds}}));
    return;
  }}
  const passed = [], failed = [];
  for (const c of cases) {{
    if (c.kind === 'loop_pass') {{ passed.push(c.id); continue; }}
    if (c.kind === 'loop_fail') {{ failed.push(c.id); continue; }}
    const args = c.args.map(decode);
    const expected = decode(c.expected);
    const tolAbs = c.tolAbs !== null ? c.tolAbs : globalTol;
    const tolRel = c.tolRel;
    const tolStrict = c.tolStrict;
    try {{
      if (c.kind === 'raises') {{
        const raiseP = (async () => {{
          try {{ await fn(...args); return null; }}
          catch (e) {{ return e; }}
        }})();
        const raiseResult = await withTimeout(raiseP, timeoutMs);
        if (raiseResult === _TIMEOUT_SENTINEL) {{ failed.push(c.id); continue; }}
        if (raiseResult === null) {{ failed.push(c.id); continue; }}
        const thrownErr = raiseResult;
        let ok = true;
        if (c.excType !== null) ok = (thrownErr && thrownErr.constructor && thrownErr.constructor.name === c.excType) || (thrownErr && thrownErr.name === c.excType);
        if (ok && c.msgContains !== null) ok = String(thrownErr && thrownErr.message || thrownErr).includes(c.msgContains);
        if (ok && c.msgRegex !== null) ok = new RegExp(c.msgRegex).test(String(thrownErr && thrownErr.message || thrownErr));
        (ok ? passed : failed).push(c.id);
        continue;
      }}
      const mutationCheck = c.mutationCheck;
      const captureResult = await withTimeout(captureCall(fn, args), timeoutMs);
      if (captureResult === _TIMEOUT_SENTINEL) {{ failed.push(c.id); continue; }}
      const {{ result: _raw, stdout, stderr, threw }} = captureResult;
      if (threw) {{ failed.push(c.id); continue; }}
      const _result = mutationCheck !== null ? args[mutationCheck] : _raw;
      const result = c.transform !== null ? _TRANSFORMS[c.transform](_result) : _result;
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

run().catch(() => process.exit(2));
"""


def emit_typescript(cases: list[TestCase], entrypoint: str) -> str:
    cases_json = json.dumps(
        [{"id": tc.id, "kind": tc.kind,
          "args": _to_json_value(tc.args), "expected": _to_json_value(tc.expected),
          "expectStdout": tc.expect_stdout, "expectStderr": tc.expect_stderr,
          "tolAbs": tc.tol_abs, "tolRel": tc.tol_rel, "tolStrict": tc.tol_strict,
          "excType": tc.exc_type, "msgContains": tc.msg_contains, "msgRegex": tc.msg_regex,
          "transform": tc.transform, "mutationCheck": tc.mutation_check}
         for tc in cases],
        indent=2,
    )
    ep_json = json.dumps(entrypoint)
    ids_json = json.dumps([tc.id for tc in cases])

    return f"""\
// _BCG_IDS: {ids_json}
import * as fs from 'fs';
import * as path from 'path';

const ENTRYPOINT: string = {ep_json};
interface Case {{
  id: string; kind: string; args: any[]; expected: any;
  expectStdout: string | null; expectStderr: string | null;
  tolAbs: number | null; tolRel: number | null; tolStrict: boolean;
  excType: string | null; msgContains: string | null; msgRegex: string | null;
  transform: string | null; mutationCheck: number | null;
}}
const CASES: Case[] = {cases_json};

const _TIMEOUT_SENTINEL: unique symbol = Symbol('timeout');

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

async function captureCall(
  fn: (...a: any[]) => any, args: any[]
): Promise<{{ result: any; stdout: string; stderr: string; threw: boolean; thrownErr: any }}> {{
  let stdout = '', stderr = '';
  const ow = process.stdout.write.bind(process.stdout);
  const ew = process.stderr.write.bind(process.stderr);
  (process.stdout as any).write = (c: any) => {{ stdout += c; return true; }};
  (process.stderr as any).write = (c: any) => {{ stderr += c; return true; }};
  let result: any, threw = false, thrownErr: any = null;
  try {{ result = await fn(...args); }} catch (e) {{ threw = true; thrownErr = e; }}
  finally {{ process.stdout.write = ow; process.stderr.write = ew; }}
  return {{ result, stdout, stderr, threw, thrownErr }};
}}

function withTimeout<T>(promise: Promise<T>, ms: number | null): Promise<T | typeof _TIMEOUT_SENTINEL> {{
  if (ms === null) return promise;
  const tout = new Promise<typeof _TIMEOUT_SENTINEL>(r => setTimeout(() => r(_TIMEOUT_SENTINEL), ms));
  return Promise.race([promise, tout]);
}}

async function run(): Promise<void> {{
  const solPath: string = process.argv[2];
  const resultsPath: string = process.env['_BCG_RESULTS_FILE']!;
  const globalTol: number | null = process.env['_BCG_TOL'] !== undefined ? parseFloat(process.env['_BCG_TOL']!) : null;
  const runId: string | null = process.env['_BCG_RUN_ID'] || null;
  const timeoutMs: number | null = process.env['_BCG_TIMEOUT_MS'] ? parseInt(process.env['_BCG_TIMEOUT_MS']!) : null;
  const cases: Case[] = runId ? CASES.filter((c: Case) => c.id === runId) : CASES;
  const allIds: string[] = cases.map((c: Case) => c.id);
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
  for (const c of cases) {{
    if (c.kind === 'loop_pass') {{ passed.push(c.id); continue; }}
    if (c.kind === 'loop_fail') {{ failed.push(c.id); continue; }}
    const args: any[] = c.args.map(decode);
    const expected: any = decode(c.expected);
    const tolAbs: number | null = c.tolAbs !== null ? c.tolAbs : globalTol;
    const tolRel: number | null = c.tolRel;
    const tolStrict: boolean = c.tolStrict;
    try {{
      if (c.kind === 'raises') {{
        const raiseP: Promise<any> = (async () => {{
          try {{ await fn(...args); return null; }}
          catch (e) {{ return e; }}
        }})();
        const raiseResult = await withTimeout(raiseP, timeoutMs);
        if (raiseResult === _TIMEOUT_SENTINEL) {{ failed.push(c.id); continue; }}
        if (raiseResult === null) {{ failed.push(c.id); continue; }}
        const thrownErr: any = raiseResult;
        let ok = true;
        if (c.excType !== null) ok = (thrownErr && thrownErr.constructor && thrownErr.constructor.name === c.excType) || (thrownErr && thrownErr.name === c.excType);
        if (ok && c.msgContains !== null) ok = String(thrownErr && thrownErr.message !== undefined ? thrownErr.message : thrownErr).includes(c.msgContains!);
        if (ok && c.msgRegex !== null) ok = new RegExp(c.msgRegex!).test(String(thrownErr && thrownErr.message !== undefined ? thrownErr.message : thrownErr));
        (ok ? passed : failed).push(c.id);
        continue;
      }}
      const captureResult = await withTimeout(captureCall(fn, args), timeoutMs);
      if (captureResult === _TIMEOUT_SENTINEL) {{ failed.push(c.id); continue; }}
      const {{ result: _raw, stdout, stderr, threw }} = captureResult as Awaited<ReturnType<typeof captureCall>>;
      if (threw) {{ failed.push(c.id); continue; }}
      const _result: any = c.mutationCheck !== null ? args[c.mutationCheck] : _raw;
      const result: any = c.transform !== null ? _TRANSFORMS[c.transform](_result) : _result;
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

run().catch(() => process.exit(2));
"""


# ---------------------------------------------------------------------------
# C++ helpers & emitter
# ---------------------------------------------------------------------------

def _cpp_str_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == '\\': out.append('\\\\')
        elif ch == '"': out.append('\\"')
        elif ch == '\n': out.append('\\n')
        elif ch == '\r': out.append('\\r')
        elif ch == '\t': out.append('\\t')
        elif ch == '\0': out.append('\\0')
        else: out.append(ch)
    return ''.join(out)


def _cpp_type(v: Any) -> str:
    if v is None:
        return "std::nullopt_t"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "long long"
    if isinstance(v, float):
        return "long double"
    if isinstance(v, str):
        return "std::string"
    if isinstance(v, list):
        return f"std::vector<{_cpp_type(v[0]) if v else 'long long'}>"
    if isinstance(v, tuple):
        tag = v[0]
        if tag == "__decimal__":
            return "long double"
        if tag in ("__tuple__", "__deque__"):
            inner = v[1]
            return f"std::vector<{_cpp_type(inner[0]) if inner else 'long long'}>"
        if tag in ("__set__", "__frozenset__"):
            inner = v[1]
            return f"std::set<{_cpp_type(inner[0]) if inner else 'long long'}>"
        if tag == "__dict__":
            keys, vals = v[1], v[2]
            if not keys:
                return "std::map<std::string, long long>"
            return f"std::map<{_cpp_type(keys[0])}, {_cpp_type(vals[0])}>"
        if tag in ("__counter__", "__defaultdict__"):
            inner = v[1]
            if isinstance(inner, tuple) and inner[0] == "__dict__" and inner[1]:
                return f"std::map<{_cpp_type(inner[1][0])}, long long>"
            return "std::map<std::string, long long>"
    return "long long"


def _cpp_val(v: Any) -> str:
    if v is None:
        return "std::nullopt"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}LL"
    if isinstance(v, float):
        if v != v:
            return "std::numeric_limits<long double>::quiet_NaN()"
        if v == float('inf'):
            return "std::numeric_limits<long double>::infinity()"
        if v == float('-inf'):
            return "-std::numeric_limits<long double>::infinity()"
        return repr(v) + "L"
    if isinstance(v, str):
        return f'std::string("{_cpp_str_escape(v)}")'
    if isinstance(v, list):
        if not v:
            return "{}"
        et = _cpp_type(v[0])
        return f"std::vector<{et}>{{{', '.join(_cpp_val(x) for x in v)}}}"
    if isinstance(v, tuple):
        tag = v[0]
        if tag == "__decimal__":
            return repr(float(v[1])) + "L"
        if tag == "__tuple__":
            items = v[1]
            if not items:
                return "std::vector<long long>{}"
            et = _cpp_type(items[0])
            return f"std::vector<{et}>{{{', '.join(_cpp_val(x) for x in items)}}}"
        if tag == "__deque__":
            items = v[1]
            if not items:
                return "std::deque<long long>{}"
            et = _cpp_type(items[0])
            return f"std::deque<{et}>{{{', '.join(_cpp_val(x) for x in items)}}}"
        if tag in ("__set__", "__frozenset__"):
            items = v[1]
            if not items:
                return "std::set<long long>{}"
            et = _cpp_type(items[0])
            return f"std::set<{et}>{{{', '.join(_cpp_val(x) for x in items)}}}"
        if tag == "__dict__":
            keys, vals = v[1], v[2]
            if not keys:
                return "std::map<std::string, long long>{}"
            kt = _cpp_type(keys[0])
            vt = _cpp_type(vals[0])
            pairs = ", ".join(
                f"{{{_cpp_val(k)}, {_cpp_val(val)}}}"
                for k, val in zip(keys, vals)
            )
            return f"std::map<{kt}, {vt}>{{{pairs}}}"
        if tag in ("__counter__", "__defaultdict__"):
            inner = v[1]
            if isinstance(inner, tuple) and inner[0] == "__dict__":
                keys, vals = inner[1], inner[2]
                if not keys:
                    return "std::map<std::string, long long>{}"
                kt = _cpp_type(keys[0])
                pairs = ", ".join(
                    f"{{{_cpp_val(k)}, {_cpp_val(val)}}}"
                    for k, val in zip(keys, vals)
                )
                return f"std::map<{kt}, long long>{{{pairs}}}"
            return "std::map<std::string, long long>{}"
    raise ValueError(f"Cannot encode C++ value: {v!r}")


def _cpp_is_numeric(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, tuple) and v and v[0] == "__decimal__":
        return True
    return False


def _cpp_tc_block(tc: TestCase, ep: str) -> str:
    tid = tc.id.replace('\\', '\\\\').replace('"', '\\"')
    args_code = ", ".join(_cpp_val(a) for a in tc.args)
    I = "    "
    II = I + "    "
    III = II + "    "
    open_block = f'{I}if (_run_id == nullptr || std::string(_run_id) == "{tid}") {{'
    L = [f"{I}// {tc.id}", open_block]

    if tc.kind == "loop_pass":
        L += [f'{II}_passed.push_back("{tid}");', f"{I}}}"]
        return "\n".join(L)
    if tc.kind == "loop_fail":
        L += [f'{II}_failed.push_back("{tid}");', f"{I}}}"]
        return "\n".join(L)
    if tc.expect_stdout is not None or tc.expect_stderr is not None:
        L += [f'{II}_failed.push_back("{tid}"); // stdout/stderr not supported', f"{I}}}"]
        return "\n".join(L)

    call = f"{ep}({args_code})"
    call_u = f"_bcg_unwrap({call})"

    # ---- raises ----
    if tc.kind == "raises":
        L += [
            f"{II}auto _bcg_raises_ = [&]() -> bool {{",
            f"{III}try {{ {call_u}; return false; }}",
            f"{III}catch (...) {{ return true; }}",
            f"{II}}};",
            f"{II}if (_timeout_ms > 0) {{",
            f"{II}    auto _f_ = std::async(std::launch::async, _bcg_raises_);",
            f"{II}    if (_f_.wait_for(std::chrono::milliseconds(_timeout_ms)) != std::future_status::ready) {{",
            f'{II}        _failed.push_back("{tid}"); }}',
            f"{II}    else {{ (_f_.get() ? _passed : _failed).push_back(\"{tid}\"); }}",
            f"{II}}} else {{",
            f'{II}    (_bcg_raises_() ? _passed : _failed).push_back("{tid}");',
            f"{II}}}",
            f"{I}}}",
        ]
        return "\n".join(L)

    # ---- transforms ----
    transforms_cpp = {
        "sorted": f"[&](){{ auto _t = {call_u}; std::sort(_t.begin(), _t.end()); return _t; }}()",
        "len":    f"(long long)({call_u}).size()",
        "list":   call_u,
        "tuple":  call_u,
        "set":    f"[&](){{ auto _t = {call_u}; return std::set<typename decltype(_t)::value_type>(_t.begin(), _t.end()); }}()",
        "str":    f"std::to_string({call_u})",
        "int":    f"(long long)({call_u})",
        "float":  f"(long double)({call_u})",
        "abs":    f"[&](){{ auto _v = {call_u}; return _v < 0 ? -_v : _v; }}()",
        "sum":    f"[&](){{ auto _t = {call_u}; return std::accumulate(_t.begin(), _t.end(), decltype(*_t.begin()){{}}); }}()",
        "min":    f"[&](){{ auto _t = {call_u}; return *std::min_element(_t.begin(), _t.end()); }}()",
        "max":    f"[&](){{ auto _t = {call_u}; return *std::max_element(_t.begin(), _t.end()); }}()",
    }
    result_expr = transforms_cpp.get(tc.transform, call_u) if tc.transform else call_u

    # ---- mutation_check (no timeout support) ----
    if tc.mutation_check is not None:
        L += [
            f"{II}try {{",
            f"{III}auto _result = {result_expr};",
            f"{III}// mutation_check not supported in C++ tester",
            f'{III}_failed.push_back("{tid}");',
            f'{II}}} catch (...) {{ _failed.push_back("{tid}"); }}',
            f"{I}}}",
        ]
        return "\n".join(L)

    # ---- build comparison lines for _bcg_cmp_ lambda ----
    cmp_lines: list[str] = []
    if tc.kind in ("truthy", "falsy"):
        neg = "!" if tc.kind == "falsy" else ""
        cmp_lines += [
            f"bool _ok = {neg}(bool)_result;",
            f'(_ok ? _passed : _failed).push_back("{tid}");',
        ]
    elif tc.kind == "in":
        exp_t = _cpp_type(tc.expected)
        cmp_lines.append(f"auto _expected = {_cpp_val(tc.expected)};")
        if "set" in exp_t:
            cmp_lines.append("bool _ok = _expected.count(_result) > 0;")
        else:
            cmp_lines.append("bool _ok = std::find(_expected.begin(), _expected.end(), _result) != _expected.end();")
        cmp_lines.append(f'(_ok ? _passed : _failed).push_back("{tid}");')
    else:
        # eq / ne
        cmp_lines.append(f"auto _expected = {_cpp_val(tc.expected)};")
        use_tol = tc.tol_abs is not None or tc.tol_rel is not None
        is_num = _cpp_is_numeric(tc.expected)
        ta = f"{tc.tol_abs}L" if tc.tol_abs is not None else "-1.0L"
        tr_val = f"{tc.tol_rel}L" if tc.tol_rel is not None else "-1.0L"
        ts = "true" if tc.tol_strict else "false"
        if use_tol:
            cmp_lines.append(f"bool _ok = _bcg_eq_num(_result, _expected, {ta}, {tr_val}, {ts});")
        elif is_num:
            cmp_lines += [
                "bool _ok = (_global_tol >= 0.0L)",
                f"    ? _bcg_eq_num(_result, _expected, _global_tol, -1.0L, true)",
                "    : (_result == _expected);",
            ]
        else:
            cmp_lines.append("bool _ok = (_result == _expected);")
        if tc.kind == "ne":
            cmp_lines.append("_ok = !_ok;")
        cmp_lines.append(f'(_ok ? _passed : _failed).push_back("{tid}");')

    # ---- emit the timeout-aware block ----
    L.append(f"{II}auto _bcg_cmp_ = [&](auto&& _result) {{")
    for line in cmp_lines:
        L.append(f"{III}{line}")
    L.append(f"{II}}};")
    L.append(f"{II}auto _bcg_fn_ = [&]{{ return {result_expr}; }};")
    L.append(f"{II}if (_timeout_ms > 0) {{")
    L.append(f"{II}    auto _f_ = std::async(std::launch::async, _bcg_fn_);")
    L.append(f"{II}    if (_f_.wait_for(std::chrono::milliseconds(_timeout_ms)) != std::future_status::ready) {{")
    L.append(f'{II}        _failed.push_back("{tid}"); }}')
    L.append(f'{II}    else {{ try {{ _bcg_cmp_(_f_.get()); }} catch (...) {{ _failed.push_back("{tid}"); }} }}')
    L.append(f"{II}}} else {{")
    L.append(f'{II}    try {{ _bcg_cmp_(_bcg_fn_()); }} catch (...) {{ _failed.push_back("{tid}"); }}')
    L.append(f"{II}}}")
    L.append(f"{I}}}")
    return "\n".join(L)


def emit_cpp(cases: list[TestCase], entrypoint: str) -> str:
    ids_json = json.dumps([tc.id for tc in cases])
    preamble = f"""\
// Auto-generated by babel_code_goat -- do not edit
// _BCG_IDS: {ids_json}
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <functional>
#include <future>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

static long double _global_tol = -1.0L;

template<typename T, typename U>
bool _bcg_eq_num(const T& a, const U& b, long double tol_abs, long double tol_rel, bool strict) {{
    if (tol_abs < 0.0L && tol_rel < 0.0L) return (long double)a == (long double)b;
    long double da = (long double)a, db = (long double)b;
    long double diff = fabsl(da - db);
    long double lim = tol_abs >= 0.0L ? tol_abs : 0.0L;
    if (tol_rel >= 0.0L) lim = std::max(lim, tol_rel * std::max(fabsl(da), fabsl(db)));
    return strict ? diff < lim : diff <= lim;
}}

template<typename T> struct _BCGIsFuture : std::false_type {{}};
template<typename T> struct _BCGIsFuture<std::future<T>> : std::true_type {{}};
template<typename T> struct _BCGIsFuture<std::shared_future<T>> : std::true_type {{}};

template<typename T>
auto _bcg_unwrap(T&& v) -> decltype(std::forward<T>(v)) {{
    return std::forward<T>(v);
}}
template<typename T>
auto _bcg_unwrap(std::future<T>& v) -> T {{ return v.get(); }}
template<typename T>
auto _bcg_unwrap(std::future<T>&& v) -> T {{ return v.get(); }}
template<typename T>
auto _bcg_unwrap(std::shared_future<T>& v) -> T {{ return v.get(); }}
template<typename T>
auto _bcg_unwrap(std::shared_future<T>&& v) -> T {{ return v.get(); }}

static std::string _json_esc(const std::string& s) {{
    std::string r; r.reserve(s.size() + 4);
    for (unsigned char c : s) {{
        if (c == 34) {{ r += (char)92; r += (char)34; }}
        else if (c == 92) {{ r += (char)92; r += (char)92; }}
        else r += (char)c;
    }}
    return r;
}}

int main() {{
    const char* _tol_env = std::getenv("_BCG_TOL");
    if (_tol_env) _global_tol = std::stold(std::string(_tol_env));
    const char* _res_env = std::getenv("_BCG_RESULTS_FILE");
    if (!_res_env) return 1;
    const char* _run_id = std::getenv("_BCG_RUN_ID");
    const char* _timeout_env = std::getenv("_BCG_TIMEOUT_MS");
    long long _timeout_ms = _timeout_env ? std::stoll(std::string(_timeout_env)) : -1LL;
    std::vector<std::string> _passed, _failed;

"""
    test_blocks = "\n".join(_cpp_tc_block(tc, entrypoint) for tc in cases)
    epilogue = """
    std::ofstream _out(_res_env);
    _out << R"({"passed":[)";
    for (size_t i = 0; i < _passed.size(); i++) {
        if (i) _out << (char)44;
        _out << (char)34 << _json_esc(_passed[i]) << (char)34;
    }
    _out << R"(],"failed":[)";
    for (size_t i = 0; i < _failed.size(); i++) {
        if (i) _out << (char)44;
        _out << (char)34 << _json_esc(_failed[i]) << (char)34;
    }
    _out << "]}";
    return 0;
}
"""
    return preamble + test_blocks + epilogue


# ---------------------------------------------------------------------------
# Rust helpers & emitter
# ---------------------------------------------------------------------------

def _rust_str_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == '\\': out.append('\\\\')
        elif ch == '"': out.append('\\"')
        elif ch == '\n': out.append('\\n')
        elif ch == '\r': out.append('\\r')
        elif ch == '\t': out.append('\\t')
        elif ch == '\0': out.append('\\0')
        else: out.append(ch)
    return ''.join(out)


def _has_deque(v: Any) -> bool:
    if isinstance(v, tuple) and v:
        if v[0] == "__deque__":
            return True
        if v[0] in ("__tuple__", "__set__", "__frozenset__"):
            return any(_has_deque(x) for x in v[1])
        if v[0] == "__dict__":
            return any(_has_deque(x) for x in v[1]) or any(_has_deque(x) for x in v[2])
        if v[0] in ("__counter__", "__defaultdict__"):
            return _has_deque(v[1])
    if isinstance(v, list):
        return any(_has_deque(x) for x in v)
    return False


def _rust_val(v: Any) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}_i64"
    if isinstance(v, float):
        if v != v:
            return "f64::NAN"
        if v == float('inf'):
            return "f64::INFINITY"
        if v == float('-inf'):
            return "f64::NEG_INFINITY"
        return repr(v) + "_f64"
    if isinstance(v, str):
        return f'String::from("{_rust_str_escape(v)}")'
    if isinstance(v, list):
        if not v:
            return "Vec::<i64>::new()"
        items = ", ".join(_rust_val(x) for x in v)
        return f"vec![{items}]"
    if isinstance(v, tuple):
        tag = v[0]
        if tag == "__decimal__":
            return repr(float(v[1])) + "_f64"
        if tag == "__tuple__":
            items = v[1]
            if not items:
                return "Vec::<i64>::new()"
            return f"vec![{', '.join(_rust_val(x) for x in items)}]"
        if tag == "__deque__":
            return "/* deque */"
        if tag in ("__set__", "__frozenset__"):
            items = v[1]
            if not items:
                return "BTreeSet::<i64>::new()"
            inserts = " ".join(f"_s.insert({_rust_val(x)});" for x in items)
            return f"{{ let mut _s = BTreeSet::new(); {inserts} _s }}"
        if tag == "__dict__":
            keys, vals = v[1], v[2]
            if not keys:
                return "BTreeMap::<String, i64>::new()"
            inserts = " ".join(
                f"_m.insert({_rust_val(k)}, {_rust_val(val)});"
                for k, val in zip(keys, vals)
            )
            return f"{{ let mut _m = BTreeMap::new(); {inserts} _m }}"
        if tag in ("__counter__", "__defaultdict__"):
            inner = v[1]
            if isinstance(inner, tuple) and inner[0] == "__dict__":
                keys, vals = inner[1], inner[2]
                if not keys:
                    return "BTreeMap::<String, i64>::new()"
                inserts = " ".join(
                    f"_m.insert({_rust_val(k)}, {_rust_val(val)});"
                    for k, val in zip(keys, vals)
                )
                return f"{{ let mut _m = BTreeMap::new(); {inserts} _m }}"
            return "BTreeMap::<String, i64>::new()"
    raise ValueError(f"Cannot encode Rust value: {v!r}")


def _rust_is_numeric(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, tuple) and v and v[0] == "__decimal__":
        return True
    return False


def _rust_cmp_lines(tc: TestCase, tid_safe: str, result_var: str, indent: str) -> list[str]:
    """Generate comparison + push lines for a Rust test block."""
    I = indent
    is_num = _rust_is_numeric(tc.expected)
    expected_is_none = tc.expected is None

    if tc.kind in ("truthy", "falsy"):
        neg = "!" if tc.kind == "falsy" else ""
        return [
            f"{I}let _ok = {neg}{result_var};",
            f'{I}if _ok {{ _passed.push(String::from("{tid_safe}")); }}',
            f'{I}else {{ _failed.push(String::from("{tid_safe}")); }}',
        ]

    if tc.kind == "in":
        return [
            f"{I}let _container = {_rust_val(tc.expected)};",
            f"{I}let _ok = _container.iter().any(|x| x == &{result_var});",
            f'{I}if _ok {{ _passed.push(String::from("{tid_safe}")); }}',
            f'{I}else {{ _failed.push(String::from("{tid_safe}")); }}',
        ]

    # eq / ne
    if expected_is_none:
        ok_expr = f"{result_var}.is_none()" if tc.kind == "eq" else f"{result_var}.is_some()"
        return [
            f"{I}let _ok = {ok_expr};",
            f'{I}if _ok {{ _passed.push(String::from("{tid_safe}")); }}',
            f'{I}else {{ _failed.push(String::from("{tid_safe}")); }}',
        ]

    use_tol = tc.tol_abs is not None or tc.tol_rel is not None
    if use_tol:
        ta = f"{tc.tol_abs}_f64"
        tr_val = tc.tol_rel
        ts = tc.tol_strict
        if tr_val is not None:
            lim = f"({ta}).max({tr_val}_f64 * ({result_var} as f64).abs().max((_expected as f64).abs()))"
            cmp = "<" if ts else "<="
            ok_inner = f"({result_var} as f64 - _expected as f64).abs() {cmp} {lim}"
        else:
            cmp = "<" if ts else "<="
            ok_inner = f"({result_var} as f64 - _expected as f64).abs() {cmp} {ta}"
        ok_expr = ok_inner if tc.kind == "eq" else f"!({ok_inner})"
    elif is_num:
        ok_inner = f"if _global_tol >= 0.0_f64 {{ ({result_var} as f64 - _expected as f64).abs() <= _global_tol }} else {{ {result_var} == _expected }}"
        ok_expr = ok_inner if tc.kind == "eq" else f"!({{ {ok_inner} }})"
    else:
        ok_expr = f"{result_var} == _expected" if tc.kind == "eq" else f"{result_var} != _expected"

    return [
        f"{I}let _expected = {_rust_val(tc.expected)};",
        f"{I}let _ok = {ok_expr};",
        f'{I}if _ok {{ _passed.push(String::from("{tid_safe}")); }}',
        f'{I}else {{ _failed.push(String::from("{tid_safe}")); }}',
    ]


def _rust_async_transform(transform: str | None, raw_var: str) -> str:
    """Build Rust transform expression applied to an already-awaited variable."""
    if not transform:
        return raw_var
    t = {
        "sorted": f"{{ let mut _t = {raw_var}; _t.sort(); _t }}",
        "len":    f"({raw_var}).len() as i64",
        "list":   raw_var,
        "tuple":  raw_var,
        "set":    f"({raw_var}).into_iter().collect::<BTreeSet<_>>()",
        "str":    f"({raw_var}).to_string()",
        "int":    f"({raw_var}) as i64",
        "float":  f"({raw_var}) as f64",
        "abs":    f"{{ let _v = {raw_var}; if _v < Default::default() {{ -_v }} else {{ _v }} }}",
        "sum":    f"({raw_var}).iter().copied().sum::<_>()",
        "min":    f"*({raw_var}).iter().min().unwrap()",
        "max":    f"*({raw_var}).iter().max().unwrap()",
    }
    return t.get(transform, raw_var)


def _rust_tc_block(tc: TestCase, ep: str) -> str:
    tid_safe = tc.id.replace('\\', '\\\\').replace('"', '\\"')
    args_code = ", ".join(_rust_val(a) for a in tc.args)
    I = "    "
    II = I + "    "
    III = II + "    "
    open_block = f'{I}if _run_id.as_deref().map_or(true, |id| id == "{tid_safe}") {{'
    L = [f"{I}// {tc.id}", open_block]

    if tc.kind == "loop_pass":
        L += [f'{II}_passed.push(String::from("{tid_safe}"));', f"{I}}}"]
        return "\n".join(L)
    if tc.kind == "loop_fail":
        L += [f'{I}    _failed.push(String::from("{tid_safe}"));', f"{I}}}"]
        return "\n".join(L)

    has_dq = any(_has_deque(a) for a in tc.args) or _has_deque(tc.expected)
    if has_dq:
        L += [f'{II}_failed.push(String::from("{tid_safe}")); // deque not supported in Rust', f"{I}}}"]
        return "\n".join(L)

    if tc.expect_stdout is not None or tc.expect_stderr is not None:
        L += [f'{II}_failed.push(String::from("{tid_safe}")); // stdout/stderr not supported', f"{I}}}"]
        return "\n".join(L)

    call = f"{ep}({args_code})"

    if tc.kind == "raises":
        L += [
            f"{II}let _threw = std::panic::catch_unwind(",
            f"{II}    std::panic::AssertUnwindSafe(|| {{ {call}; }})",
            f"{II}).is_err();",
            f'{II}if _threw {{ _passed.push(String::from("{tid_safe}")); }}',
            f'{II}else {{ _failed.push(String::from("{tid_safe}")); }}',
            f"{I}}}",
        ]
        return "\n".join(L)

    if tc.mutation_check is not None:
        L += [
            f"{II}let _ = {{ {call}; }};",
            f"{II}// mutation_check not supported in Rust tester",
            f'{II}_failed.push(String::from("{tid_safe}"));',
            f"{I}}}",
        ]
        return "\n".join(L)

    # Sync result expression (for #[cfg(not(bcg_async))])
    sync_transforms = {
        "sorted": f"{{ let mut _t = {call}; _t.sort(); _t }}",
        "len":    f"({call}).len() as i64",
        "list":   call,
        "tuple":  call,
        "set":    f"({call}).into_iter().collect::<BTreeSet<_>>()",
        "str":    f"({call}).to_string()",
        "int":    f"({call}) as i64",
        "float":  f"({call}) as f64",
        "abs":    f"{{ let _v = {call}; if _v < Default::default() {{ -_v }} else {{ _v }} }}",
        "sum":    f"({call}).iter().copied().sum::<_>()",
        "min":    f"*({call}).iter().min().unwrap()",
        "max":    f"*({call}).iter().max().unwrap()",
    }
    sync_result_expr = sync_transforms.get(tc.transform, call) if tc.transform else call
    async_result_expr = _rust_async_transform(tc.transform, "_raw")

    IIII = III + "    "

    cmp_lines = _rust_cmp_lines(tc, tid_safe, "_result", IIII)

    # Use loop{} for early-exit-on-timeout via break
    L += [
        f"{II}loop {{",
        # ---- async branch ----
        f"{III}#[cfg(bcg_async)] {{",
        f"{IIII}let _raw = if _timeout_ms > 0 {{",
        f"{IIII}    match _rt.block_on(tokio::time::timeout(",
        f"{IIII}        std::time::Duration::from_millis(_timeout_ms),",
        f"{IIII}        {call}",
        f"{IIII}    )) {{",
        f"{IIII}        Ok(r) => r,",
        f'{IIII}        Err(_) => {{ _failed.push(String::from("{tid_safe}")); break; }}',
        f"{IIII}    }}",
        f"{IIII}}} else {{",
        f"{IIII}    _rt.block_on({call})",
        f"{IIII}}};",
        f"{IIII}let _result = {async_result_expr};",
        *cmp_lines,
        f"{III}}}",
        # ---- sync branch ----
        f"{III}#[cfg(not(bcg_async))] {{",
        f"{IIII}let _result = {sync_result_expr};",
        *cmp_lines,
        f"{III}}}",
        f"{III}break;",
        f"{II}}}",  # end loop
        f"{I}}}",   # end if _run_id
    ]
    return "\n".join(L)


def emit_rust(cases: list[TestCase], entrypoint: str) -> str:
    ids_json = json.dumps([tc.id for tc in cases])
    ep_repr = json.dumps(entrypoint)
    preamble = f"""\
// Auto-generated by babel_code_goat -- do not edit
// _BCG_IDS: {ids_json}
// _BCG_EP: {ep_repr}
#![allow(unused_imports, dead_code, unused_variables, unused_mut, non_snake_case)]
use std::collections::{{BTreeMap, BTreeSet}};
#[cfg(bcg_async)] use tokio;

fn main() {{
    let _global_tol: f64 = std::env::var("_BCG_TOL")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(-1.0_f64);
    let _results_path = match std::env::var("_BCG_RESULTS_FILE") {{
        Ok(p) => p,
        Err(_) => return,
    }};
    let _run_id: Option<String> = std::env::var("_BCG_RUN_ID").ok();
    let _timeout_ms: u64 = std::env::var("_BCG_TIMEOUT_MS")
        .ok().and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
    #[cfg(bcg_async)]
    let _rt = tokio::runtime::Builder::new_current_thread()
        .enable_all().build().unwrap();
    let mut _passed: Vec<String> = Vec::new();
    let mut _failed: Vec<String> = Vec::new();

"""
    test_blocks = "\n".join(_rust_tc_block(tc, entrypoint) for tc in cases)
    epilogue = """
    let mut _out = String::new();
    _out.push_str(r#"{"passed":["#);
    for (i, id) in _passed.iter().enumerate() {
        if i > 0 { _out.push(char::from(44u8)); }
        _out.push(char::from(34u8));
        _out.push_str(id);
        _out.push(char::from(34u8));
    }
    _out.push_str(r#"],"failed":["#);
    for (i, id) in _failed.iter().enumerate() {
        if i > 0 { _out.push(char::from(44u8)); }
        _out.push(char::from(34u8));
        _out.push_str(id);
        _out.push(char::from(34u8));
    }
    _out.push_str("]}");
    std::fs::write(&_results_path, _out).unwrap();
}
"""
    return preamble + test_blocks + epilogue


# ---------------------------------------------------------------------------
# Compile functions for compiled targets
# ---------------------------------------------------------------------------

def _cpp_compile(tester: Path, sol: Path, out: Path) -> int:
    try:
        result = subprocess.run(
            ["g++", "-std=c++17", f"-include{sol}", str(tester), "-o", str(out)],
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stderr.decode(errors="replace"), file=sys.stderr)
        return result.returncode
    except FileNotFoundError as e:
        print(f"error: compiler not found: {e}", file=sys.stderr)
        return 1


def _rust_read_ep(tester: Path) -> str:
    """Extract the entrypoint name from the _BCG_EP comment in a generated Rust tester."""
    try:
        with open(tester) as f:
            for line in f:
                if "_BCG_EP:" in line:
                    idx = line.index("_BCG_EP:") + len("_BCG_EP:")
                    return json.loads(line[idx:].strip())
    except Exception:
        pass
    return ""


def _rust_compile(tester: Path, sol: Path, out: Path) -> int:
    sol_text = sol.read_text()
    ep_name = _rust_read_ep(tester)
    # Detect async entrypoint in the solution
    is_async = bool(ep_name and re.search(rf'\basync\s+fn\s+{re.escape(ep_name)}\b', sol_text))
    return _rust_compile_cargo(tester, sol, out, async_ep=is_async) if is_async \
        else _rust_compile_rustc(tester, sol, out)


def _rust_compile_rustc(tester: Path, sol: Path, out: Path) -> int:
    """Plain rustc compilation for sync solutions (no tokio)."""
    fd, combined = tempfile.mkstemp(suffix=".rs")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(sol.read_text())
            f.write("\n")
            f.write(tester.read_text())
        result = subprocess.run(
            ["rustc", "--edition", "2021", combined, "-o", str(out)],
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stderr.decode(errors="replace"), file=sys.stderr)
        return result.returncode
    except FileNotFoundError as e:
        print(f"error: compiler not found: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            os.unlink(combined)
        except OSError:
            pass


def _rust_compile_cargo(tester: Path, sol: Path, out: Path, async_ep: bool) -> int:
    """Cargo-based compilation supporting tokio for async solutions."""
    import shutil
    cargo_dir = Path(tempfile.mkdtemp(prefix="bcg_rust_"))
    try:
        # Write Cargo.toml
        (cargo_dir / "Cargo.toml").write_text(
            '[package]\nname = "bcg_tester"\nversion = "0.1.0"\nedition = "2021"\n\n'
            '[dependencies]\ntokio = { version = "1", features = ["full"] }\n'
        )
        src_dir = cargo_dir / "src"
        src_dir.mkdir()
        with open(src_dir / "main.rs", "w") as f:
            f.write(sol.read_text())
            f.write("\n")
            f.write(tester.read_text())
        cfg_flags = ["--cfg", "bcg_async"] if async_ep else []
        try:
            result = subprocess.run(
                ["cargo", "rustc", "--release", "--", *cfg_flags],
                capture_output=True,
                cwd=str(cargo_dir),
            )
        except FileNotFoundError as e:
            print(f"error: cargo not found: {e}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(result.stderr.decode(errors="replace"), file=sys.stderr)
            return result.returncode
        built = cargo_dir / "target" / "release" / "bcg_tester"
        if not built.exists():
            print("error: cargo build succeeded but binary not found", file=sys.stderr)
            return 1
        shutil.copy2(str(built), str(out))
        return 0
    except Exception as e:
        print(f"error: cargo compilation failed: {e}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(str(cargo_dir), ignore_errors=True)


_COMPILE: dict[str, Any] = {
    "cpp": _cpp_compile,
    "rust": _rust_compile,
}


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

_TESTER_NAMES = {
    "python": "tester.py",
    "javascript": "tester.js",
    "typescript": "tester.ts",
    "cpp": "tester.cpp",
    "rust": "tester.rs",
}

_EMITTERS = {
    "python": emit_python,
    "javascript": emit_javascript,
    "typescript": emit_typescript,
    "cpp": emit_cpp,
    "rust": emit_rust,
}


def discover_test_files(tests_dir: Path) -> list[Path]:
    """Return sorted .py files under tests_dir. Raises DiscoveryError for test-like non-.py files."""
    _generated_names = set(_TESTER_NAMES.values())
    for f in tests_dir.rglob("*"):
        if f.is_file() and f.suffix != ".py":
            if f.name in _generated_names:
                continue
            s = f.stem.lower()
            if s.startswith("test") or s.endswith("_test") or s.endswith("_tests"):
                rel = f.relative_to(tests_dir).as_posix()
                raise DiscoveryError(f"non-.py test-like file found: {rel}")
    return sorted(
        (f for f in tests_dir.rglob("*.py") if f.is_file()),
        key=lambda p: p.relative_to(tests_dir).parts,
    )


def cmd_generate(args: argparse.Namespace) -> int:
    tests_dir = Path(args.tests_dir)

    try:
        py_files = discover_test_files(tests_dir)
    except DiscoveryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cases: list[TestCase] = []
    for py_file in py_files:
        file_prefix = py_file.relative_to(tests_dir).as_posix()
        try:
            source = py_file.read_text()
            file_cases = parse_tests(source, args.entrypoint, file_prefix=file_prefix)
            cases.extend(file_cases)
        except DiscoveryError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"error: failed to parse {file_prefix}: {e}", file=sys.stderr)
            return 1

    if not cases:
        print(f"error: no tests discovered in {tests_dir}", file=sys.stderr)
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


def _read_tester_ids(tester_path: Path) -> list[str]:
    """Extract test IDs from the _BCG_IDS comment line in a generated tester file."""
    try:
        with open(tester_path) as f:
            for line in f:
                if "_BCG_IDS:" in line:
                    idx = line.index("_BCG_IDS:") + len("_BCG_IDS:")
                    return json.loads(line[idx:].strip())
    except Exception:
        pass
    return []


def cmd_test(args: argparse.Namespace) -> int:
    if args.lang not in _TESTER_NAMES:
        return _error_exit()

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    if not tester_path.exists():
        return _error_exit()

    # --list-tests: return all IDs as passed without running the solution
    if getattr(args, "list_tests", False):
        all_ids = _read_tester_ids(tester_path)
        print(json.dumps({"status": "pass", "passed": all_ids, "failed": []}))
        return 0

    # --run: validate the requested ID exists before running
    run_id: str | None = getattr(args, "run_id", None)
    if run_id is not None:
        all_ids = _read_tester_ids(tester_path)
        if run_id not in all_ids:
            return _error_exit()

    sol_path = Path(args.solution_path)
    fd, results_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    bin_path: str | None = None
    try:
        if args.lang in _COMPILE:
            fd_bin, bin_path = tempfile.mkstemp()
            os.close(fd_bin)
            rc = _COMPILE[args.lang](tester_path, sol_path, Path(bin_path))
            if rc != 0:
                return _error_exit()
            cmd: list[str] = [bin_path]
        else:
            cmd = _SUBPROC[args.lang](tester_path, sol_path)

        env = {**os.environ, "_BCG_RESULTS_FILE": results_file}
        if args.tol is not None:
            env["_BCG_TOL"] = str(args.tol)
        if run_id is not None:
            env["_BCG_RUN_ID"] = run_id
        timeout_ms: int | None = getattr(args, "timeout_ms", None)
        if timeout_ms is not None:
            env["_BCG_TIMEOUT_MS"] = str(timeout_ms)
        total_timeout_ms: int | None = getattr(args, "total_timeout_ms", None)

        proc_timeout = total_timeout_ms / 1000.0 if total_timeout_ms is not None else None
        timed_out = False
        try:
            subprocess.run(cmd, env=env, check=False, timeout=proc_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        except FileNotFoundError as e:
            print(f"error: subprocess not found: {e}", file=sys.stderr)
            return _error_exit()

        try:
            with open(results_file) as f:
                data = json.load(f)
            passed: list[str] = data.get("passed", [])
            failed: list[str] = data.get("failed", [])
        except Exception:
            passed, failed = [], []

        if timed_out:
            # Move any IDs not yet recorded into failed
            recorded = set(passed) | set(failed)
            all_ids = _read_tester_ids(tester_path)
            if run_id is not None:
                all_ids = [i for i in all_ids if i == run_id]
            for tid in all_ids:
                if tid not in recorded:
                    failed.append(tid)

        if not passed and not failed:
            return _error_exit()

        status = "fail" if failed else "pass"
        print(json.dumps({"status": status, "passed": passed, "failed": failed}))
        return 0 if status == "pass" else 1
    finally:
        try:
            os.unlink(results_file)
        except OSError:
            pass
        if bin_path is not None:
            try:
                os.unlink(bin_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# profile command
# ---------------------------------------------------------------------------

def _run_one_trial(
    cmd: list[str],
    env: dict,
    results_file: str,
    all_ids: list[str],
    run_id: str | None,
    total_timeout_ms: int | None,
    measure_memory: bool,
) -> tuple[list[str], list[str], int, float | None]:
    """Run one subprocess trial. Returns (passed, failed, duration_ns, memory_kb_or_None)."""
    proc_timeout = total_timeout_ms / 1000.0 if total_timeout_ms is not None else None

    if measure_memory and _HAS_RESOURCE:
        before = _resource.getrusage(_resource.RUSAGE_CHILDREN).ru_maxrss
    else:
        before = None

    t0 = time.perf_counter_ns()
    timed_out = False
    try:
        subprocess.run(cmd, env=env, check=False, timeout=proc_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    except FileNotFoundError as e:
        print(f"error: subprocess not found: {e}", file=sys.stderr)
        return [], list(all_ids if run_id is None else [run_id]), time.perf_counter_ns() - t0, None
    duration_ns = time.perf_counter_ns() - t0

    if measure_memory and _HAS_RESOURCE and before is not None:
        after = _resource.getrusage(_resource.RUSAGE_CHILDREN).ru_maxrss
        delta_raw = after - before
        import platform
        if platform.system() == "Darwin":
            memory_kb: float | None = delta_raw / 1024.0
        else:
            memory_kb = float(delta_raw)  # Linux: ru_maxrss already in KB
        if memory_kb < 0:
            memory_kb = 0.0
    else:
        memory_kb = None

    try:
        with open(results_file) as f:
            data = json.load(f)
        passed: list[str] = data.get("passed", [])
        failed: list[str] = data.get("failed", [])
    except Exception:
        passed, failed = [], []

    if timed_out:
        recorded = set(passed) | set(failed)
        ids_scope = all_ids if run_id is None else [i for i in all_ids if i == run_id]
        for tid in ids_scope:
            if tid not in recorded:
                failed.append(tid)

    open(results_file, "w").close()
    return passed, failed, duration_ns, memory_kb


def _stats(samples: list[float]) -> dict:
    n = len(samples)
    if n == 0:
        return {"mean": 0.0, "std": 0.0}
    mean = sum(samples) / n
    variance = sum((x - mean) ** 2 for x in samples) / n
    return {"mean": mean, "std": math.sqrt(variance)}


def cmd_profile(args: argparse.Namespace) -> int:
    if args.lang not in _TESTER_NAMES:
        return _error_exit()

    tests_dir = Path(args.tests_dir)
    tester_path = tests_dir / _TESTER_NAMES[args.lang]
    if not tester_path.exists():
        return _error_exit()

    n: int = args.n
    warmup: int = args.warmup
    if warmup >= n:
        print(f"error: --warmup {warmup} must be less than -n {n}", file=sys.stderr)
        return 1

    all_ids = _read_tester_ids(tester_path)
    run_id: str | None = getattr(args, "run_id", None)

    if getattr(args, "list_tests", False):
        out: dict = {
            "status": "pass",
            "passed": all_ids,
            "failed": [],
            "runtime_ns": {"mean": 0.0, "std": 0.0},
        }
        if args.memory:
            out["memory_kb"] = {"mean": 0.0, "std": 0.0}
        print(json.dumps(out))
        return 0

    if run_id is not None and run_id not in all_ids:
        return _error_exit()

    sol_path = Path(args.solution_path)
    fd, results_file = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    bin_path: str | None = None
    try:
        if args.lang in _COMPILE:
            fd_bin, bin_path = tempfile.mkstemp()
            os.close(fd_bin)
            rc = _COMPILE[args.lang](tester_path, sol_path, Path(bin_path))
            if rc != 0:
                return _error_exit()
            cmd_base: list[str] = [bin_path]
        else:
            cmd_base = _SUBPROC[args.lang](tester_path, sol_path)

        env_base = {**os.environ, "_BCG_RESULTS_FILE": results_file}
        if args.tol is not None:
            env_base["_BCG_TOL"] = str(args.tol)
        if run_id is not None:
            env_base["_BCG_RUN_ID"] = run_id
        timeout_ms: int | None = getattr(args, "timeout_ms", None)
        if timeout_ms is not None:
            env_base["_BCG_TIMEOUT_MS"] = str(timeout_ms)
        total_timeout_ms: int | None = getattr(args, "total_timeout_ms", None)

        last_passed: list[str] = []
        last_failed: list[str] = []

        for i in range(warmup):
            passed_w, failed_w, _, _ = _run_one_trial(
                cmd_base, env_base, results_file, all_ids, run_id, total_timeout_ms, False
            )
            last_passed, last_failed = passed_w, failed_w

        duration_samples: list[float] = []
        memory_samples: list[float] = []

        for i in range(n):
            passed_t, failed_t, dur_ns, mem_kb = _run_one_trial(
                cmd_base, env_base, results_file, all_ids, run_id, total_timeout_ms, args.memory
            )
            last_passed, last_failed = passed_t, failed_t
            duration_samples.append(float(dur_ns))
            if args.memory and mem_kb is not None:
                memory_samples.append(mem_kb)

        if not last_passed and not last_failed:
            return _error_exit()

        status = "fail" if last_failed else "pass"
        out = {
            "status": status,
            "passed": last_passed,
            "failed": last_failed,
            "runtime_ns": _stats(duration_samples),
        }
        if args.memory:
            out["memory_kb"] = _stats(memory_samples) if memory_samples else {"mean": 0.0, "std": 0.0}

        print(json.dumps(out))
        return 0 if status == "pass" else 1
    finally:
        try:
            os.unlink(results_file)
        except OSError:
            pass
        if bin_path is not None:
            try:
                os.unlink(bin_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_VALID_LANGS = frozenset(_TESTER_NAMES)


def _lang_type(value: str) -> str:
    if value not in _VALID_LANGS:
        raise argparse.ArgumentTypeError(
            f"lang must be python/javascript/typescript/cpp/rust, got: {value!r}"
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
    tst.add_argument("--list-tests", dest="list_tests", action="store_true", default=False)
    tst.add_argument("--run", dest="run_id", type=str, default=None)
    tst.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=None)
    tst.add_argument("--total-timeout-ms", dest="total_timeout_ms", type=int, default=None)

    prf = sub.add_parser("profile")
    prf.add_argument("tests_dir")
    prf.add_argument("solution_path")
    prf.add_argument("--lang", required=True)
    prf.add_argument("--tol", type=float, default=None)
    prf.add_argument("--list-tests", dest="list_tests", action="store_true", default=False)
    prf.add_argument("--run", dest="run_id", type=str, default=None)
    prf.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=None)
    prf.add_argument("--total-timeout-ms", dest="total_timeout_ms", type=int, default=None)
    prf.add_argument("-n", dest="n", type=int, default=1)
    prf.add_argument("--warmup", dest="warmup", type=int, default=0)
    prf.add_argument("--memory", action="store_true", default=False)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 1
    if args.command == "generate":
        return cmd_generate(args)
    if args.command == "profile":
        return cmd_profile(args)
    return cmd_test(args)


if __name__ == "__main__":
    sys.exit(main())
