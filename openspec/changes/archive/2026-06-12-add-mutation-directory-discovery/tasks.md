## 1. Recursive Discovery

- [x] 1.1 Add recursive `.py` file collection in `discover_tests`, sorted by forward-slash relative path from `<tests_dir>`.
- [x] 1.2 Reject non-`.py` files with test-like basenames matching `test*`, `*_test`, `tests`, or `*_tests` before their extension.
- [x] 1.3 Exclude generated tester files from Python test discovery while preserving tester existence checks for `test`.
- [x] 1.4 Return a discovery error when recursive discovery completes with no discovered tests.

## 2. Source-Aware Test IDs

- [x] 2.1 Add relative source-path metadata to pending and finalized test case structures.
- [x] 2.2 Pass each file's relative path into `TestDiscoverer` and propagate it to every pending test, including loop tests.
- [x] 2.3 Update test ID generation to use `<relative-path>:<line>`, loop iteration suffixes, and same-line `#k` suffixes across files.
- [x] 2.4 Update existing tests that assert root `tests.py` IDs only where the new relative-path plumbing changes expectations.

## 3. Mutation-Style Discovery

- [x] 3.1 Detect entrypoint calls used as standalone statements or single-target assignments during sequential body visitation.
- [x] 3.2 Consume one or more immediately following assertion statements as the mutation group and reject groups without immediate assertions.
- [x] 3.3 Validate mutation assertions have no entrypoint calls and reference at least one variable passed to the mutation call or assigned from it.
- [x] 3.4 Encode mutation case metadata so generated testers call the entrypoint before evaluating mutation assertions.
- [x] 3.5 Execute mutation cases for Python, JavaScript, and TypeScript targets without changing existing non-mutation case behavior.

## 4. Regression Coverage

- [x] 4.1 Add discovery unit tests for recursive Python files, nested relative IDs, and deterministic ordering.
- [x] 4.2 Add discovery error tests for test-like non-Python files and directories with no discovered tests.
- [x] 4.3 Add mutation-style discovery tests for valid statement calls, valid assignment calls, and multiple immediate assertions.
- [x] 4.4 Add mutation-style discovery error tests for missing immediate assertions, assertions with entrypoint calls, and assertions that do not reference mutation variables.
- [x] 4.5 Add end-to-end CLI tests showing mutation-style tests pass and fail correctly across supported target languages.

## 5. Validation

- [x] 5.1 Run the repository test suite.
- [x] 5.2 Run OpenSpec validation for `add-mutation-directory-discovery`.
