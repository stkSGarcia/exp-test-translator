## 1. IR and ID tagging

- [x] 1.1 Add `"loop_pass"` and `"loop_fail"` as valid `kind` literals in `TestCase` (update the `Literal` type annotation)
- [x] 1.2 Define the ID tagging convention in `_collect_stmts`: use `"loop:<lineno>"` for loop-as-test and `"iter:<lineno>:<k>"` for loop body assertions; document the sentinel in a comment

## 2. Value evaluation with bindings

- [x] 2.1 Add optional `bindings: dict | None = None` parameter to `_ast_to_value`; resolve `ast.Name` nodes from bindings before the existing constant/call dispatch
- [x] 2.2 Propagate `bindings` through all recursive `_ast_to_value` calls (List, Tuple, Set, Dict, UnaryOp, Call)
- [x] 2.3 Propagate `bindings` through `_ast_call_to_value` (all inner `_ast_to_value` calls)
- [x] 2.4 Add `_collect_ep_args(call, bindings)` helper that builds the positional args list and handles `ast.Starred` nodes by expanding bound tuple/list values

## 3. `_match_assert` and helpers accept bindings

- [x] 3.1 Add `bindings: dict | None = None` to `_match_assert`, `_match_isclose`, `_match_abs_tol`, `_match_primitive_wrapped`; thread it through all `_ast_to_value` and arg-collection calls
- [x] 3.2 Replace direct `test.left.args` iteration with `_collect_ep_args(test.left, bindings)` in `_match_assert` for the EP-call cases

## 4. Loop iteration evaluation

- [x] 4.1 Add `_eval_expr(node, bindings)` — a plain-Python evaluator (returns raw Python values, not internal-encoded) supporting: `Constant`, `Name`, `List`, `Tuple`, `Subscript`, `UnaryOp`, `BinOp` (Add/Sub/Mul/FloorDiv), `Compare` (Lt/LtE/Gt/GtE/Eq/NotEq), and `Call` for `len`, `range`, `enumerate`
- [x] 4.2 Add `_bind_target(target, val, bindings)` that handles `ast.Name` (direct bind) and `ast.Tuple`/`ast.List` (destructuring unpack of list or `("__tuple__", [...])` encoded values)
- [x] 4.3 Add `_eval_for_iterations(stmt, bindings)` — evaluates `stmt.iter` via `_eval_expr` or `_ast_to_value`, iterates items, calls `_bind_target` for each, returns list of per-iteration binding dicts; handles `enumerate` specially to wrap items with index
- [x] 4.4 Add `_eval_while_iterations(stmt, outer_bindings)` — simulates while loop using `_eval_expr` for the condition; walks body for `ast.Assign`/`ast.AugAssign` to update a mutable bindings copy; collects per-iteration snapshots; hard cap at 1000 iterations; returns `[]` on any evaluation failure
- [x] 4.5 Add `_eval_loop_iterations(stmt, bindings)` — dispatches to `_eval_for_iterations` or `_eval_while_iterations`; wraps in try/except, returns `[]` on any failure

## 5. Loop handling in `_collect_stmts`

- [x] 5.1 Add `bindings: dict | None = None` parameter to `_collect_stmts`; initialise to `{}` if `None`; pass a copy into recursive calls for `If`, `With`, `FunctionDef`, `ClassDef` (new scope = empty dict)
- [x] 5.2 Detect `ast.Assign` statements with a single `ast.Name` target and constant-evaluable RHS; call `_ast_to_value(stmt.value, bindings)` and store the result in `bindings` if successful (ignore failures)
- [x] 5.3 Replace the existing `isinstance(stmt, (ast.For, ast.While))` branch with a call to `_handle_loop(stmt, lines, ep, out, bindings)`
- [x] 5.4 Add `_handle_loop(stmt, lines, ep, out, bindings)`: call `_eval_loop_iterations`; emit `loop_fail` test case (tagged `"loop:<lineno>"`) if zero iterations; emit `loop_pass` test case (tagged `"loop:<lineno>"`) then for each iteration call `_collect_stmts` on the loop body with `{**bindings, **iter_bindings}`, prefix the resulting test IDs with `"iter:<original_lineno>:<k>"` format (store raw line numbers during body collection, then rewrite to iter tags)
- [x] 5.5 Pass `bindings` to `_match_assert` calls inside `_collect_stmts`

## 6. ID assignment in `parse_tests`

- [x] 6.1 After collecting raw test cases, split them into three buckets by ID prefix: `"loop:"` (loop-as-tests), `"iter:"` (loop body assertions), and plain integers (unlooped assertions)
- [x] 6.2 Apply existing dedup logic only to the plain-integer bucket (unchanged behaviour)
- [x] 6.3 Convert `"loop:<n>"` IDs to `"tests.py:<n>"`
- [x] 6.4 Convert `"iter:<n>:<k>"` IDs to `"tests.py:<n>:<k>"`
- [x] 6.5 Reconstruct the final test case list preserving original order

## 7. Emitter updates

- [x] 7.1 In `emit_python`: add `loop_pass` and `loop_fail` kind handlers before the existing kind dispatch — `loop_pass` appends `tid` to `passed` and `continue`s; `loop_fail` appends `tid` to `failed` and `continue`s
- [x] 7.2 In `emit_javascript`: same two kind handlers in the JS runner loop
- [x] 7.3 In `emit_typescript`: same two kind handlers in the TS runner loop

## 8. Verification

- [x] 8.1 Manually test the basic for-in loop case: `cases = [((1,2),3)]; for args, exp in cases: assert add(*args) == exp` — verify IDs `tests.py:2` (loop_pass) and `tests.py:3:0` (eq)
- [x] 8.2 Manually test empty-list loop: `for x in []: assert add(x,x) == 0` — verify single `loop_fail` at loop line, no body assertion
- [x] 8.3 Manually test enumerate loop pattern: `for i, (a, b) in enumerate(cases): assert add(a,b) == a+b`
- [x] 8.4 Manually test while-loop pattern from checkpoint: `i=0; while i < len(cases): a,b=cases[i]; assert add(a,b)==a+b; i+=1`
- [x] 8.5 Manually test nested loops: outer passes, inner passes; verify both loop-as-test IDs and body assertion IDs
- [x] 8.6 Run `generate` command on a loop-containing test file and inspect the generated tester for correct CASES array
- [x] 8.7 Run `test` command end-to-end with a correct solution and verify JSON output `{"status":"pass",...}` with expected passed/failed lists
