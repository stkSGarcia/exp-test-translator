## 1. CLI Options and Validation

- [x] 1.1 Update `babel_code_goat.py` `build_parser()` and `command_test()` to accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>` for `test` [extends `babel-code-goat-cli/support-single-call-traceability`].
- [x] 1.2 Add normalized execution options in `babel_code_goat.py` for list mode, selected test ID, per-test timeout, and total timeout, using the existing `--tol` validation style as the starting point.
- [x] 1.3 Add parser and invalid-value coverage in `tests/test_babel_code_goat.py` for the new `test` flags.

## 2. Listing and Selected Execution

- [x] 2.1 Update `babel_code_goat.py` `command_test()` so `--list-tests` runs `discover_tests()` and returns `{"status":"pass","passed":[...],"failed":[]}` without invoking `aggregate_results()` [extends `babel-code-goat-cli/support-mutation-directory-discovery`].
- [x] 2.2 Update `babel_code_goat.py` to filter the discovered cases after discovery when `--run <test_id>` is provided, returning the standard error result if the ID is not discovered.
- [x] 2.3 Add `tests/test_babel_code_goat.py` coverage proving `--list-tests` reports all discovered IDs, `--run` reports only the selected ID, and discovery failures still return the standard error JSON.

## 3. Async Entrypoint Completion

- [x] 3.1 Update `babel_code_goat.py` `PYTHON_CASE_RUNNER` so callable results that are awaitable are completed before `_matches()` and stdout/stderr expectations are evaluated.
- [x] 3.2 Audit `babel_code_goat.py` `NODE_CASE_RUNNER` to preserve promise awaiting through `withCaptureAsync()` for both JavaScript and TypeScript solutions.
- [x] 3.3 Add `tests/test_babel_code_goat.py` regression tests for Python `async def`, JavaScript promise-returning, and TypeScript promise-returning entrypoints.

## 4. Timeout Handling

- [x] 4.1 Thread per-test timeout values through `babel_code_goat.py` `aggregate_results()`, `execute_case()`, `run_python_case()`, and `run_node_case()` so per-case subprocess timeout maps to a failed test ID [extends `babel-code-goat-cli/add-loop-as-test-support`].
- [x] 4.2 Add total-timeout tracking in `babel_code_goat.py` `aggregate_results()` so the current and remaining active cases are listed in `failed` when `--total-timeout-ms` is exhausted [extends `babel-code-goat-cli/add-loop-as-test-support`].
- [x] 4.3 Audit `babel_code_goat.py` native suite paths `run_cpp_suite()` and `run_rust_suite()` for current target-language scope, and either pass timeout options through them or document and test the chosen behavior.
- [x] 4.4 Add timeout coverage in `tests/test_babel_code_goat.py` for per-test timeout, total timeout with not-executed tests, and timeout behavior combined with `--run`.

## 5. Verification

- [x] 5.1 Run `python -m unittest tests.test_babel_code_goat` and fix any regressions.
- [x] 5.2 Run `openspec status --change "add-async-test-selection-timeouts"` and confirm the proposal is ready for apply.
