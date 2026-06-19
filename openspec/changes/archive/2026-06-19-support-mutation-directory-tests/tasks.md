## 1. Recursive Discovery Sources

- [x] 1.1 Add a recursive source collector in `discover_tests()` that walks `<tests_dir>`, sorts `.py` files by POSIX-style relative path, and parses each file.
- [x] 1.2 Reject non-`.py` files under `<tests_dir>` whose names match `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`.
- [x] 1.3 Raise `DiscoveryError` when recursive discovery completes without finding any tests.
- [x] 1.4 Preserve existing `tests.py` behavior by keeping root-file discovery order and errors deterministic.

## 2. Path-Aware Test IDs

- [x] 2.1 Add a source-relative path field to `PendingTest` and `TestCase`, normalized with forward slashes.
- [x] 2.2 Pass the current source path into each `TestDiscoverer` and every pending test it creates, including loop tests and loop-body assertions.
- [x] 2.3 Update `assign_test_ids()` and `test_id_base()` so duplicate suffixes are scoped by relative path, line, and iteration path.
- [x] 2.4 Verify root `tests.py` IDs remain unchanged and nested files use IDs such as `subdir/tests.py:5`.

## 3. Mutation-Style Discovery

- [x] 3.1 Extend `visit_body()` to identify standalone entrypoint call statements and single-target assignments whose value is the configured entrypoint call.
- [x] 3.2 Collect affected variable names from named call arguments and direct assignment targets, rejecting mutation calls that have no immediate follow-up assertions.
- [x] 3.3 Validate each immediate mutation assertion contains no entrypoint call and references at least one affected variable.
- [x] 3.4 Materialize mutation assertion cases that preserve the call setup, assertion expression, expectations, source path, and source line.
- [x] 3.5 Reject mutation patterns interrupted by non-assert statements before the first assertion or assertions that inspect only unrelated variables.

## 4. Mutation Execution

- [x] 4.1 Extend case encoding/decoding to represent mutation tests and their post-call assertion expression plans.
- [x] 4.2 Update the Python case runner to call the entrypoint once, bind post-call argument and assignment variables, and evaluate the mutation assertion expression.
- [x] 4.3 Update the JavaScript and TypeScript case runners to execute mutation cases with the same call-once and post-call assertion semantics.
- [x] 4.4 Ensure mutation cases still honor stdout and stderr expectations and aggregate into `passed` or `failed` exactly once.

## 5. Tests and Verification

- [x] 5.1 Add tests for recursive `.py` discovery across root and nested directories, including deterministic output order.
- [x] 5.2 Add discovery-error tests for test-like non-Python files and directories with no discovered tests.
- [x] 5.3 Add tests for relative-path IDs, duplicate `#k` suffixes, and loop IDs in nested source files.
- [x] 5.4 Add passing and failing mutation-style tests for standalone calls, assignment calls, multiple immediate asserts, and unrelated-variable rejection.
- [x] 5.5 Run the full test suite and the relevant CLI generate/test flows for Python, JavaScript, and TypeScript.
