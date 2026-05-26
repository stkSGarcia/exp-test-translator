## Context

`babel_code_goat.py` translates a static `tests.py` file into a language-specific tester that runs against a solution. The parser (`parse_tests` / `_collect_stmts`) does a single AST walk, collecting `TestCase` IR objects. All test case args and expected values must be evaluable at parse time from literal expressions.

Currently loops are treated as transparent scope: `_collect_stmts` recurses into the body but does not model the loop itself as a test. Loop variables are unresolved names at parse time, so any assertion that references loop variables (e.g. `add(*args)`, `add(a, b)`) produces no test case. Starred argument expansion is not handled.

## Goals / Non-Goals

**Goals:**
- Each loop statement becomes a loop-as-test with a deterministic ID
- Loop body assertions are unrolled into per-iteration test cases with iteration-indexed IDs
- Common Python loop forms are handled: `for…in`, `enumerate`, `range(len(...))`, index-based `for i in range(...)`, and simple `while` counter loops
- Starred expansion (`*var`) in entrypoint calls is resolved using loop variable bindings
- Nested loops produce nested loop-as-tests
- Zero-iteration loops produce a `loop_fail` test case; positive-iteration loops produce `loop_pass` plus unrolled assertion test cases
- All three emitters (Python, JS, TS) handle `loop_pass` / `loop_fail` kinds

**Non-Goals:**
- General Python execution — only constant-valued iterables resolvable at AST-walk time are supported
- Arbitrary while-loop conditions beyond simple counter patterns
- Loop-level tolerance/annotation semantics (those belong to individual assertions)
- Changing the JS/TS runtime or harness protocol

## Decisions

### D1: Static unrolling at parse time, not at emitter time

**Decision**: Unroll loop iterations during `_collect_stmts` and emit individual `TestCase` objects (one `loop_pass`/`loop_fail` + N per-iteration assertion cases).

**Alternative considered**: Embed loop metadata in `TestCase` and let the tester generate test IDs at runtime. Rejected because the tester is already a thin, data-driven runner; adding iteration logic would require non-trivial changes to all three emitters and could diverge between languages.

**Rationale**: Static unrolling keeps the emitters unchanged except for two new no-op kind handlers. The cost is that test files with non-evaluable iterables fall back to `loop_fail` rather than producing a parse error, which is the right behavior per the spec.

### D2: Internal value encoding for bindings

**Decision**: Bindings store values in the same internal encoding that `_ast_to_value` already uses (plain scalars, `("__tuple__", [...])`, lists, etc.). `_bind_target` unpacks these encoded values when destructuring loop targets.

**Alternative considered**: Convert to plain Python native types for bindings and re-encode at extraction time. Rejected because it would require two extra passes and make the `_ast_to_value` code path inconsistent.

**Rationale**: Keeping a single encoding throughout means `_ast_to_value(Name('x'), bindings)` just returns what was stored — no conversion needed. Starred expansion is the only special case: `("__tuple__", [a, b])` expands to `[a, b]` as positional args.

### D3: ID tagging via string sentinels, resolved in `parse_tests`

**Decision**: During `_collect_stmts`, raw IDs use tagged strings:
- Loop-as-test: `"loop:<lineno>"`
- Loop body assertion (iteration k): `"iter:<lineno>:<k>"`
- Unlooped assertion: `str(lineno)` (unchanged)

Final ID assignment in `parse_tests` converts these to:
- `tests.py:<lineno>` for loop-as-test
- `tests.py:<lineno>:<k>` for loop body assertion
- `tests.py:<lineno>` / `tests.py:<lineno>#<k>` (dedup) for unlooped assertions

**Alternative considered**: Set final IDs directly inside the loop handler. Rejected because it would bypass the existing dedup logic for unlooped assertions and make `parse_tests` harder to read.

### D4: `while` loop support via bounded simulation

**Decision**: For `while` loops, attempt a limited simulation: evaluate the condition using `_eval_expr` (a plain-Python evaluator operating on raw Python values, separate from `_ast_to_value`), execute simple `ast.Assign` / `ast.AugAssign` updates in the body on a mutable bindings copy, and collect iteration snapshots. Abort and return zero iterations if any expression is unevaluable or if iteration count exceeds 1000.

**Alternative considered**: Reject while loops entirely (always `loop_fail`). Rejected because the spec explicitly includes while loops and provides a concrete example.

**Rationale**: A plain-Python evaluator (`_eval_expr`) operating on real Python values (not internal-encoded) is simpler to write for arithmetic/comparison. The iteration snapshots are then converted back to internal encoding for binding lookup when processing each iteration's assertions.

### D5: New emitter kind handlers are inert

**Decision**: Add `loop_pass` and `loop_fail` to all three emitters as pre-classified cases: `loop_pass` → append to `passed` immediately; `loop_fail` → append to `failed` immediately. No solution function call.

**Rationale**: The pass/fail decision is made at parse time. The runner just needs to record the outcome.

## Risks / Trade-offs

- **Non-evaluable iterables silently become loop_fail** → Mitigation: this is specified behavior per the checkpoint ("fail if cannot be evaluated").
- **`while` simulation is O(N) in loop iterations** → Mitigation: hard cap at 1000 iterations; test files in practice have small N.
- **`_eval_expr` vs `_ast_to_value` are two evaluators** → Mitigation: `_eval_expr` is only used for while-loop condition/body evaluation and returns raw Python values; `_ast_to_value` is the canonical encoder for test-case data. The boundary is clear.
- **Nested loops multiply test case counts** → Expected and matches spec; no mitigation needed.

## Migration Plan

No migration required. All changes are backward-compatible: existing non-loop test files produce identical output. The new test ID format (`tests.py:<n>:<k>`) is additive.
