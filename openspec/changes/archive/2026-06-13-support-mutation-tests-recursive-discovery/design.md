## Context

`babel_code_goat.py` currently discovers tests by parsing one constrained `<tests_dir>/tests.py` file. Test IDs are generated from line numbers with a hard-coded `tests.py` prefix, and each assertion-style test is expected to carry a single entrypoint invocation in the assertion or expectation block itself.

The checkpoint changes both assumptions. Discovery must walk a tests directory recursively, preserve each source file path in IDs, and recognize a narrow mutation-style pattern where an entrypoint mutates an argument before adjacent assertions inspect that mutated value.

## Goals / Non-Goals

**Goals:**

- Discover tests from every `.py` file under `<tests_dir>` in deterministic recursive order.
- Treat non-Python test-like files as discovery errors and report an error when no tests are discovered.
- Preserve existing direct assertions, loops, output expectations, tolerance handling, typed exceptions, rich values, JSON output, and exit-code behavior.
- Generate stable IDs from each file's path relative to `<tests_dir>` using forward slashes.
- Support mutation-style entrypoint calls only when they are statements or assignments immediately followed by assertions that inspect mutated or assigned values.
- Reject ambiguous mutation patterns during discovery instead of silently translating them incorrectly.

**Non-Goals:**

- Supporting pytest, unittest, fixtures, arbitrary helper functions, decorators, imports outside the existing restricted helper set, or arbitrary Python execution.
- Inferring mutation effects across non-adjacent statements, loops with side effects beyond the existing supported subset, or helper-mediated assertions.
- Changing tester filenames, metadata format beyond source path metadata if needed, CLI command shapes, or the `test` JSON schema.

## Decisions

1. Make discovery file-aware before changing assertion semantics.
   - Rationale: Recursive discovery and path-based IDs affect every test kind, including existing assertions, loops, and exception expectations.
   - Approach: Have `discover_tests()` collect candidate `.py` files under `<tests_dir>` in sorted relative-path order, parse each independently, run the existing `TestDiscoverer` with the file's relative path, and concatenate the resulting cases. Update `PendingTest` or the ID assignment path so each pending case carries its relative source path.
   - Alternative considered: Keep a synthetic merged AST for all files. That would make source paths and line numbers harder to preserve and would risk sharing imports or parameter assignments across unrelated files.

2. Validate directory contents before returning discovered cases.
   - Rationale: A misspelled `test_data.json` or `foo_tests.txt` should not be ignored when it looks like a test file.
   - Approach: During recursive traversal, reject non-`.py` files whose base name matches `test*`, `*_test`, `tests`, or `*_tests`. After all Python files are processed, raise `DiscoveryError` if no tests were produced.
   - Alternative considered: Ignore non-Python files. That would make mistakes quiet and conflicts with the checkpoint.

3. Keep mutation-style support as a constrained AST grouping rule.
   - Rationale: In-place mutation tests do not fit the existing "assertion contains the entrypoint call" model, but the checkpoint gives a narrow pattern that can be validated without executing arbitrary test code.
   - Approach: In `visit_body`, detect an entrypoint call used as an expression statement or single-target assignment. Consume the immediately following contiguous assertions as mutation assertions when those assertions contain no entrypoint call and reference at least one tracked variable: an argument name passed to the mutation call or a name directly assigned from the call. Each accepted assertion becomes a normal test case whose execution plan invokes the entrypoint once before evaluating the assertion expression against the mutated local values.
   - Alternative considered: Treat any standalone entrypoint call as setup for later assertions. That would make test grouping ambiguous and could accidentally associate unrelated assertions.

4. Extend expression planning only as much as mutation assertions require.
   - Rationale: Existing expression plans already evaluate primitive operations around one entrypoint result, but mutation assertions need to inspect post-call variables instead of only the return value.
   - Approach: Add a mutation test kind or metadata shape that carries the entrypoint arguments plus an assertion expression plan over named variables after the call. Reuse existing value encoders and comparison helpers for equality, truthiness, membership, containers, and tolerance where applicable.
   - Alternative considered: Execute mutation tests by running the original source assertion text. That would bypass the constrained AST contract and make JavaScript and TypeScript parity brittle.

5. Keep ordering deterministic and local to source files.
   - Rationale: Result arrays need stable ordering across platforms.
   - Approach: Sort paths lexically by forward-slash relative path, preserve in-file AST order, and use existing same-base `#<n>` suffixing after including the relative path and any loop iteration suffixes.
   - Alternative considered: Rely on filesystem traversal order. That varies by platform and filesystem.

## Risks / Trade-offs

- Mutation assertion planning may overlap with existing primitive expression support -> Reuse the expression parser where possible and add tests for each supported assertion shape.
- Recursive discovery can surface previously ignored malformed files -> This is intended for test-like non-Python files, but keep parse errors limited to `.py` candidates and preserve the standard error JSON.
- Source path IDs change the output for tests outside root `tests.py` -> Cover ID formatting directly and keep root `tests.py:<line>` unchanged for existing single-file projects.
- Grouping adjacent mutation assertions can be easy to get subtly wrong -> Implement it as a body-level scanner with explicit index advancement and targeted discovery errors for non-adjacent or mixed-entrypoint patterns.

## Migration Plan

No manual migration is required. Existing `<tests_dir>/tests.py` files continue to work and keep `tests.py:<line>` IDs. Projects may add nested `.py` test files, and unsupported mutation patterns will fail discovery with the existing error output.

## Open Questions

None for the checkpoint scope.
