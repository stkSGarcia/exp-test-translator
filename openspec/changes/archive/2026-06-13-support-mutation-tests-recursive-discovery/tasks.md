## 1. Recursive Discovery

- [x] 1.1 Replace single-file `tests.py` discovery with deterministic recursive `.py` file collection under `<tests_dir>`.
- [x] 1.2 Add validation that rejects non-Python files with test-like names: `test*`, `*_test`, `tests`, and `*_tests`.
- [x] 1.3 Preserve per-file parser isolation so imports, assignments, and function bodies do not leak across source files.
- [x] 1.4 Return a discovery error when recursive traversal produces no discovered tests.

## 2. Path-Aware Test IDs

- [x] 2.1 Carry each pending test's relative source path through discovery and case creation.
- [x] 2.2 Update ID generation to use forward-slash relative paths plus line numbers, loop iteration paths, and existing `#<n>` same-base suffixes.
- [x] 2.3 Preserve existing root `tests.py:<line>` IDs for tests that still live in `<tests_dir>/tests.py`.

## 3. Mutation-Style Tests

- [x] 3.1 Detect entrypoint calls used as expression statements or single-target assignments during body-level discovery.
- [x] 3.2 Group only the immediately following contiguous assertions as mutation-style assertions for that entrypoint call.
- [x] 3.3 Validate that grouped mutation assertions contain no entrypoint call and reference at least one passed or directly assigned mutation variable.
- [x] 3.4 Add mutation test metadata or expression planning needed to invoke the entrypoint once, then evaluate assertions against mutated or assigned values.
- [x] 3.5 Execute mutation-style tests for Python, JavaScript, and TypeScript solutions using existing comparison, truthiness, output, and tolerance behavior where applicable.
- [x] 3.6 Raise discovery errors for unsupported mutation patterns, including non-adjacent assertions, unreferenced mutation variables, or entrypoint calls inside grouped assertions.

## 4. Regression Coverage

- [x] 4.1 Add discovery tests for nested `.py` files, absent root `tests.py`, sorted traversal order, and no-test discovery errors.
- [x] 4.2 Add discovery tests for non-Python test-like filenames that must error.
- [x] 4.3 Add ID tests for nested paths, same-line suffixes, loop paths, and preservation of root `tests.py` IDs.
- [x] 4.4 Add mutation-style tests for statement calls, assignment calls, multiple adjacent assertions, and assertions over mutated variables.
- [x] 4.5 Add rejection tests for unsupported mutation patterns described in the spec.
- [x] 4.6 Add Python execution tests for supported mutation-style cases.
- [x] 4.7 Add JavaScript and TypeScript mutation-style smoke tests when Node is available.
- [x] 4.8 Run the repository test suite and `openspec status --change "support-mutation-tests-recursive-discovery"` to confirm the change is apply-ready.
