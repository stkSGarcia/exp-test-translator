## Context

`babel_code_goat.py` discovers Python tests from `tests.py`, serializes them into a payload, and emits language-specific testers that execute the configured entrypoint from that payload. Discovery currently walks function bodies and accepts imports, `def` blocks, assertions, supported raise expectation blocks, and `pass`; it rejects assignments and loop statements. Checkpoint 4 expands the accepted Python test surface so parameterization loops are themselves tests and assertions inside loop bodies produce per-iteration tests while continuing to obey single-call traceability.

## Goals / Non-Goals

**Goals:**

- Treat each supported `for` and `while` statement as a discovered loop test with a pass/fail outcome based on whether the loop body executes at least once.
- Evaluate supported loop constructs deterministically during discovery so loop body assertions can be expanded into ordinary serialized test cases with concrete arguments and expectations.
- Preserve the existing single-call assertion expression model for assertions inside loops.
- Support direct iteration, `enumerate(...)`, index-based `range(len(...))`, `while` loops with simple state updates, and nested loops.
- Generate stable IDs for loop statements and per-iteration assertion tests.

**Non-Goals:**

- Supporting arbitrary Python execution, user-defined helper functions, comprehensions, generators, mutation-heavy loops, or side effects during discovery.
- Changing the CLI command shape, result JSON shape, exit code mapping, or generated tester filenames.
- Requiring JavaScript or TypeScript testers to evaluate Python loop syntax directly.

## Decisions

1. Evaluate loops during discovery with a restricted Python subset.

   Discovery will maintain a scoped environment of supported literal values and loop variables. Literal assignments needed for parameterization, such as `cases = [...]` and `i = 0`, become allowed discovery constructs. Supported `for` iterables include literal containers, names bound to supported literal containers, strings, `range(...)`, `range(len(...))`, and `enumerate(...)`. Supported `while` loops evaluate comparisons and primitive expressions against the scoped environment and must be bounded by a defensive iteration cap.

   Alternative considered: preserve loop syntax in the payload and make each generated tester interpret it. That would duplicate a Python subset in JavaScript and TypeScript and make ID generation depend on runtime behavior in three implementations.

2. Serialize loop-as-test outcomes as payload tests that do not call the solution.

   Each loop statement will produce a `kind: "loop"` test case containing its source line and whether discovery observed at least one body execution. Generated testers can mark that test as passed or failed without invoking the entrypoint. A zero-iteration loop therefore generates a failing loop test and no body assertion cases.

   Alternative considered: fail discovery when a loop iterates zero times. The checkpoint requires normal test failure semantics with `status: "fail"` and exit code `1`, not a discovery error.

3. Expand body assertions per iteration into normal assertion payloads.

   When a loop iteration executes, discovery evaluates assertions in that iteration using the current scoped environment. `value_from_node` and expression parsing will resolve loop variables and assigned constants into supported values before serializing the test case. Assertions still use the existing traceability machinery: exactly one configured entrypoint invocation is required after substituting loop variables, and multiple entrypoint calls remain discovery errors.

   Alternative considered: represent a single assertion plus a table of parameter rows. That would be compact, but it would complicate per-iteration IDs and cross-language execution.

4. Use explicit loop-aware ID assignment.

   Loop statement tests keep the current line ID shape, `tests.py:<line>`. Assertions expanded from loop bodies use the assertion line plus an iteration suffix, `tests.py:<line>:<iteration-index>`, with indexes assigned in execution order across the loop nesting path. Existing same-line non-loop suffix behavior remains available for non-loop constructs.

   Alternative considered: reusing the current `#<n>` same-line suffix for loop iterations. The checkpoint examples require colon iteration suffixes, and using a distinct suffix separates parameterization from same-line collisions.

## Risks / Trade-offs

- [Risk] A restricted loop evaluator can accidentally grow into a general Python interpreter. -> Mitigation: whitelist only the constructs in the checkpoint examples and existing primitive expression support, and fail discovery for unsupported statements inside loop bodies.
- [Risk] `while` loops can be infinite or depend on unsupported state changes. -> Mitigation: enforce a conservative iteration cap and mark the loop test failed when the loop cannot be evaluated safely.
- [Risk] Loop variable scoping can leak between nested loops or sibling tests. -> Mitigation: use scoped environment copies for function bodies and loop iterations, committing only supported top-level assignments where needed.
- [Risk] Changing ID generation could regress existing tests. -> Mitigation: keep existing line and same-line behavior for non-loop tests, and add focused tests for loop IDs, nested loop IDs, and mixed loop/non-loop files.
