## 1. Coverage

- [x] 1.1 Add discovery and CLI tests for non-empty `for` loops reporting the loop line as a passing test and reporting loop body assertions per iteration.
- [x] 1.2 Add CLI tests for zero-iteration loops, including empty lists, `range(0)`, and empty strings, reporting the loop line as failed with exit code `1`.
- [x] 1.3 Add discovery and execution tests for direct tuple unpacking, `enumerate(...)`, index-based `range(len(...))`, and supported `while` loop parameterization.
- [x] 1.4 Add nested loop tests that verify each loop statement is reported separately and nested assertion IDs are assigned in execution order.
- [x] 1.5 Add negative tests for loop body assertions with zero entrypoint calls, multiple entrypoint calls, and unsupported helper calls.

## 2. Discovery Model

- [x] 2.1 Extend the test case model with a loop test kind that records whether the loop executed at least once and does not require entrypoint arguments.
- [x] 2.2 Add a restricted discovery environment for supported literal assignments, loop variables, tuple/list unpacking, and primitive updates needed by supported loop patterns.
- [x] 2.3 Update value and expression parsing to resolve names, subscripts, and primitive expressions from the discovery environment while preserving existing literal and import handling.
- [x] 2.4 Implement supported `for` iterable evaluation for literal containers, strings, bound names, `enumerate(...)`, `range(...)`, and `range(len(...))`.
- [x] 2.5 Implement supported `while` condition evaluation with a conservative iteration cap and supported state updates such as `i += 1`.

## 3. Loop Expansion And IDs

- [x] 3.1 Update body discovery to accept simple assignments and loop statements while preserving discovery errors for unsupported code.
- [x] 3.2 Expand assertions and nested loops during discovery for each executed loop iteration using scoped loop variable bindings.
- [x] 3.3 Preserve single-call traceability checks for every expanded assertion after resolving loop variables.
- [x] 3.4 Update ID assignment so loop statements use `tests.py:<line>` and loop body assertions use `tests.py:<line>:<iteration-index>`.
- [x] 3.5 Preserve existing `tests.py:<line>` and `tests.py:<line>#<n>` behavior for non-loop tests.

## 4. Tester Execution

- [x] 4.1 Update Python test execution so loop test payloads pass or fail without invoking the configured solution entrypoint.
- [x] 4.2 Update generated JavaScript tester helpers to consume loop test payloads and report pass/fail status consistently.
- [x] 4.3 Update generated TypeScript tester helpers to consume loop test payloads and report pass/fail status consistently.
- [x] 4.4 Ensure zero-iteration and safely-unevaluable loops produce normal failing result JSON, not discovery error JSON.

## 5. Verification

- [x] 5.1 Run the full pytest suite and update existing expectations affected by loop-aware ID assignment.
- [x] 5.2 Manually exercise representative `generate` and `test` flows for Python, JavaScript, and TypeScript targets with loop-based tests.
- [x] 5.3 Run `openspec status --change support-loop-construct-tests` and confirm the change is apply-ready.
