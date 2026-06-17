## 1. CLI Flags and Selection

- [x] 1.1 Update `babel_code_goat.py` `build_parser` and `command_test` to accept and validate `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Update `babel_code_goat.py` `command_test` to return discovery-only JSON for `--list-tests` using existing discovered test IDs. [extends `babel-code-goat-cli/support-mutation-style-test-discovery`]
- [x] 1.3 Update `babel_code_goat.py` `command_test` or `aggregate_results` to execute only the selected discovered case for `--run <test_id>` and ensure only that ID appears in `passed` or `failed`. [extends `babel-code-goat-cli/support-mutation-style-test-discovery`]

## 2. Async Execution

- [x] 2.1 Update `babel_code_goat.py` `PYTHON_CASE_RUNNER` to await coroutine or awaitable entrypoint results before comparison and output matching. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 2.2 Review `babel_code_goat.py` `NODE_CASE_RUNNER` to ensure JavaScript and TypeScript entrypoint promise results are awaited before assertion matching. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 2.3 Preserve existing synchronous execution behavior in `babel_code_goat.py` for Python, JavaScript, TypeScript, C++, and Rust cases.

## 3. Timeout Aggregation

- [x] 3.1 Replace hard-coded per-case subprocess timeouts in `babel_code_goat.py` `run_python_case` and `run_node_case` with the parsed `--timeout-ms` budget.
- [x] 3.2 Update `babel_code_goat.py` `aggregate_results` to enforce `--total-timeout-ms` with a monotonic deadline and mark unexecuted discovered IDs as failed. [extends `babel-code-goat-cli/add-loop-as-test-support`]
- [x] 3.3 Update `babel_code_goat.py` `run_cpp_cases` and `run_rust_cases` handling so compiled target timeouts mark selected discovered tests as failed rather than returning an error result. [extends `babel-code-goat-cli/add-loop-as-test-support`]
- [x] 3.4 Ensure timed-out tests and not-executed tests appear exactly once across `passed` and `failed` in `babel_code_goat.py`. [extends `babel-code-goat-cli/add-loop-as-test-support`]

## 4. Regression Tests

- [x] 4.1 Add `tests/test_babel_code_goat.py` coverage for `--list-tests` success and discovery error output.
- [x] 4.2 Add `tests/test_babel_code_goat.py` coverage for `--run <test_id>` proving only the selected ID is reported and only that case executes.
- [x] 4.3 Add `tests/test_babel_code_goat.py` coverage for async Python coroutine and JavaScript/TypeScript promise entrypoints.
- [x] 4.4 Add `tests/test_babel_code_goat.py` coverage for per-test timeout and total-timeout failure reporting, including not-executed discovered tests.
- [x] 4.5 Run `python -m pytest tests/test_babel_code_goat.py` and fix regressions.
