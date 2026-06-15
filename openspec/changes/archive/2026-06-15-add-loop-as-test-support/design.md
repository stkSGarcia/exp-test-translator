## Context

`babel_code_goat.py` discovers tests by walking the Python AST for a constrained `tests.py` file. It already supports typed values, expression plans, output expectations, tolerance metadata, typed exceptions, and a single-entrypoint-call traceability rule. The checkpoint expands that discovery model so Python loop statements can act as parameterized tests without executing arbitrary user code.

Loops introduce two separate result types. The loop statement itself reports whether the parameterization actually iterated, while assertions inside the loop body become normal entrypoint-backed tests for each executed iteration. Zero-iteration loops must fail as loop tests, and their body assertions must not appear in the result.

## Goals / Non-Goals

**Goals:**

- Treat supported `for` and `while` loop statements as first-class tests.
- Evaluate supported loop parameterization constructs during discovery without executing `tests.py`.
- Expand assertions inside executed loop bodies into per-iteration test cases that still invoke the configured entrypoint exactly once.
- Generate stable IDs for loop statements, loop-body assertions, and nested loop instances.
- Preserve existing JSON output, exit-code behavior, rich value handling, tolerance support, output expectations, typed exceptions, and traceability enforcement.

**Non-Goals:**

- Supporting arbitrary Python execution, user-defined helper functions, mutation beyond supported loop state, comprehensions, fixtures, pytest, or unittest.
- Adding a general-purpose Python interpreter to the discovery phase.
- Changing generated tester file names, language validation, or tester preservation guarantees.
- Relaxing the single-entrypoint-call requirement inside loop bodies.

## Decisions

1. Add a constrained discovery-time loop evaluator.
   - Rationale: The harness must know whether a loop iterated before it can report the loop test or expand body assertions, but it must still avoid executing `tests.py`.
   - Approach: Track a small environment of supported literal values, constructor values, loop targets, and loop index variables. Accept assignment forms needed by the checkpoint examples, including simple value assignment, tuple/list unpacking, index-based access into supported containers, and simple numeric increment updates used by `while` loops.
   - Alternative considered: Execute `tests.py` in a sandbox and collect runtime assertions. That would reintroduce side effects and would conflict with the existing AST-only discovery contract.

2. Represent loop statements as non-entrypoint test cases.
   - Rationale: A loop test has a pass/fail outcome but does not call the solution entrypoint.
   - Approach: Extend the pending/test case model with a loop kind and a predetermined loop outcome. Runner aggregation treats loop cases as already evaluated, while normal assertion cases continue through the existing Python, JavaScript, or TypeScript execution path.
   - Alternative considered: Encode loop results outside the test case list. That would complicate result ordering, ID generation, and the guarantee that every discovered test appears exactly once.

3. Expand loop-body assertions during discovery.
   - Rationale: Existing runners already know how to execute one assertion test at a time after discovery has resolved arguments, expected values, expression plans, tolerance metadata, and output expectations.
   - Approach: For each executed loop iteration, bind loop variables in the discovery environment, visit supported statements in the loop body, and materialize assertion or exception tests using the current environment. Existing single-call analysis still runs on the assertion AST after variable substitution or environment-aware value parsing.
   - Alternative considered: Send the loop AST to target-language runners. That would duplicate loop semantics across Python and Node and make ID generation harder to keep deterministic.

4. Use iteration paths in generated IDs.
   - Rationale: A loop-body assertion can originate from one source line but execute multiple times, and nested loops need stable, unique IDs.
   - Approach: The loop statement uses its source line as its test ID, with the active outer iteration path appended when nested. Assertions inside loops append the zero-based active iteration path after the source line, such as `tests.py:3:0` and `tests.py:3:1`. Nested loops append each active index in order, such as `tests.py:5:0:1`. Existing `#<n>` suffixes remain available when multiple tests share the same line and iteration path.
   - Alternative considered: Continue using only `#<n>` suffixes. That preserves uniqueness but hides parameterization structure and does not match the checkpoint examples.

5. Bound `while` evaluation.
   - Rationale: A supported `while` loop can still be accidentally non-terminating.
   - Approach: Evaluate only allowlisted boolean and comparison expressions over the discovery environment, update only supported loop-state assignments, and fail the loop test when evaluation cannot proceed. Keep a conservative iteration limit so runaway loops become failed loop tests rather than hanging the command.
   - Alternative considered: Treat all unsupported or runaway loops as discovery errors. The checkpoint calls for loop tests to fail when they cannot be evaluated, so a failed loop case better matches the requested behavior.

## Risks / Trade-offs

- The loop evaluator may reject Python patterns that look natural but exceed the supported subset -> Keep the subset aligned to the checkpoint examples and fail unsupported loop tests without expanding their body assertions.
- Precomputing loop cases can create many tests from large parameter lists -> Preserve deterministic ordering and consider an implementation cap with a clear failure mode if test explosion becomes a problem.
- Nested loop IDs add a new suffix form beside existing `#<n>` IDs -> Cover ID generation directly in tests and document when each suffix is used.
- `while` loop evaluation is more error-prone than `for` iteration -> Bound evaluation and start with the simple index-counter forms required by the checkpoint.

## Migration Plan

No migration is required. Existing non-loop tests continue to discover and execute as before. Loop support only adds new accepted constructs and new loop test result entries when `tests.py` contains supported loops.

## Open Questions

None for the checkpoint scope.
