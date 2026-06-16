## 1. CLI and Selection

- [x] 1.1 In `babel_code_goat.py`, add `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms` parser options to `build_parser`, following the existing `--tol` test flag pattern. [extends `babel-code-goat-cli/support-rich-test-comparisons`]
- [x] 1.2 In `babel_code_goat.py`, add validation for positive integer millisecond timeout flags and return the existing error JSON on invalid values.
- [x] 1.3 In `babel_code_goat.py`, implement `command_test` list mode so successful discovery returns `status="pass"`, all discovered `TestCase.id` values in `passed`, and `failed=[]` without executing entrypoints. [extends `babel-code-goat-cli/support-mutation-directory-discovery`]
- [x] 1.4 In `babel_code_goat.py`, implement `--run <test_id>` filtering so only the selected discovered ID can appear in `passed` or `failed`, with unknown IDs reported as error JSON. [extends `babel-code-goat-cli/support-single-call-traceability`]

## 2. Async Completion and Timeout Execution

- [x] 2.1 In `babel_code_goat.py`, thread optional per-test and total timeout budgets through `aggregate_results`, `execute_case`, `run_python_case`, `run_node_case`, `run_cpp_suite`, and `run_rust_suite`.
- [x] 2.2 In `babel_code_goat.py`, update the Python case runner payload and `PYTHON_CASE_RUNNER` to await `inspect.isawaitable` entrypoint results before evaluating assertions.
- [x] 2.3 In `babel_code_goat.py`, keep JavaScript and TypeScript entrypoint invocation awaited in `NODE_CASE_RUNNER` and apply the configured per-test timeout to the parent Node subprocess.
- [x] 2.4 In `babel_code_goat.py`, apply total timeout accounting in the aggregate loop so timed-out or not-executed scheduled tests are appended to `failed`. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 2.5 In `babel_code_goat.py`, apply configured timeout budgets to C++ and Rust compile/run subprocesses while preserving existing error behavior for compile failures and missing toolchains.

## 3. Verification

- [x] 3.1 In `tests/test_babel_code_goat.py`, add coverage for `test --list-tests` returning discovered IDs without invoking the solution. [extends `babel-code-goat-cli/support-mutation-directory-discovery`]
- [x] 3.2 In `tests/test_babel_code_goat.py`, add coverage for `test --run <test_id>` executing and reporting only the selected ID. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 3.3 In `tests/test_babel_code_goat.py`, add coverage for Python async entrypoints completing before assertions evaluate.
- [x] 3.4 In `tests/test_babel_code_goat.py`, add coverage for `--timeout-ms` marking a timed-out test as failed.
- [x] 3.5 In `tests/test_babel_code_goat.py`, add coverage for `--total-timeout-ms` marking not-executed scheduled tests as failed.
- [x] 3.6 Run the repository test suite and confirm all existing and new tests pass.
