## 1. Discovery Coverage

- [x] 1.1 Add discovery tests for recursive `.py` files under `<tests_dir>`, including nested files without a root `tests.py`.
- [x] 1.2 Add discovery-error tests for test-like non-Python files and for recursive scanning that finds no tests.
- [x] 1.3 Add ID tests for nested relative paths, root `tests.py` paths, same-line suffixes, and loop body iteration suffixes scoped by source file.
- [x] 1.4 Add mutation-style discovery tests for standalone entrypoint calls, assignment entrypoint calls, multiple immediate follow-up assertions, separated assertions, repeated entrypoint calls, and unrelated assertions.

## 2. Recursive Source Discovery

- [x] 2.1 Add source-relative path tracking to `TestCase` and preserve it in JSON payload generation.
- [x] 2.2 Refactor `discover_tests` into recursive file scanning plus per-file AST parsing.
- [x] 2.3 Reject non-`.py` files with test-like basenames using the required `test*`, `*_test`, `tests`, and `*_tests` patterns.
- [x] 2.4 Raise `DiscoveryError` when recursive scanning produces no discovered tests.
- [x] 2.5 Update ID assignment to key counters by relative source path and line number and to format IDs with forward-slash relative paths.

## 3. Mutation-Style Discovery

- [x] 3.1 Detect entrypoint expression statements and assignment statements that start mutation-style assertion groups.
- [x] 3.2 Record mutation setup metadata, including entrypoint args, direct argument variable names, and optional assignment target.
- [x] 3.3 Parse immediate follow-up assertions into mutation assertion payloads without requiring an entrypoint call inside the assertion.
- [x] 3.4 Enforce mutation constraints for immediacy, no entrypoint calls in follow-up assertions, and references to mutation-related variables.
- [x] 3.5 Preserve existing discovery errors for unsupported statements, unsupported values, and unsupported helper calls outside the mutation subset.

## 4. Tester Execution

- [x] 4.1 Extend Python tester execution to run mutation setup calls once per mutation assertion test and evaluate the assertion against the post-call variable environment.
- [x] 4.2 Extend JavaScript and TypeScript tester execution with equivalent mutation setup and assertion evaluation.
- [x] 4.3 Preserve stdout/stderr expectation checks, exception handling, tolerance behavior, and coverage accounting for mutation tests.
- [x] 4.4 Ensure stale generated testers still fail through the existing regenerated-payload comparison when discovery output changes.

## 5. CLI Verification

- [x] 5.1 Add CLI generate/test coverage for nested recursive test files across Python, JavaScript, and TypeScript targets.
- [x] 5.2 Add CLI generate/test coverage for passing and failing mutation-style tests.
- [x] 5.3 Update existing tests that assume root-only discovery or hard-coded `tests.py` IDs where recursive source paths change expectations.
- [x] 5.4 Run the full pytest suite.
