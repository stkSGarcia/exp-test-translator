## Why

Test files frequently use parameterized loops to run the same assertion over multiple inputs. Currently, the harness descends into loop bodies to find assertions but treats loops as transparent structure — the loop itself is not tested, loop body assertions get non-iteration-aware IDs, and loop variables (including starred expansion) can't be resolved at parse time.

## What Changes

- For-loops and while-loops are recognized as test constructs: the loop statement itself becomes a test that passes if the body executes at least once, and fails if it iterates zero times.
- Loop body assertions receive iteration-indexed IDs (`tests.py:<line>:<iter_idx>`) instead of plain line-number IDs.
- The parser tracks module-level variable bindings so loop iterables defined as named lists are resolved.
- Starred argument expansion (`add(*args)`) is supported inside loop bodies.
- All common Python loop patterns are supported: `for…in`, `enumerate`, `range(len(...))`, index-based, and `while` counter loops.
- Nested loops are supported: each loop level is independently a loop-as-test.
- `loop_pass` and `loop_fail` test kinds are added to all three emitters (Python, JavaScript, TypeScript).

## Capabilities

### New Capabilities

- `loop-as-test`: Loop statements as first-class tests — loop-as-test ID generation, zero-iteration failure, iteration-indexed assertion IDs, static loop unrolling with variable binding and starred expansion.

### Modified Capabilities

- `test-parsing`: The parser now handles variable assignments for binding context, recognizes loop constructs specially instead of treating them as transparent, and threads bindings through all expression-evaluation helpers.

## Impact

- `babel_code_goat.py`: all changes are confined to this single file — `_collect_stmts`, `parse_tests`, `_ast_to_value`, `_match_assert` and helpers, and all three `emit_*` functions.
- No new dependencies.
- No breaking changes to existing test-case ID formats or emitter output for non-loop tests.
