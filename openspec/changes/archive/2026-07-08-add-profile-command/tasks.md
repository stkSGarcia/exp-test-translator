## 1. Shared Execution Foundation

- [x] 1.1 Refactor `babel_code_goat.py::command_test` into reusable helpers for supported-language validation, tester file lookup, payload extraction, discovered-test verification, `--list-tests`, `--run`, timeout validation, environment construction, subprocess execution, and result validation. [extends `babel-code-goat-cli/support-rich-python-test-comparisons`]
- [x] 1.2 Preserve existing `test` command behavior and exit codes by updating `command_test` to call the new helpers without changing its JSON result shape. [extends `async-test-execution-controls/support-async-test-selection-timeouts`]
- [x] 1.3 Add helper coverage or regression assertions in `tests/test_babel_code_goat.py` for unsupported language, missing tester, selected runs, list-tests, tolerance, and timeout behavior after the refactor.

## 2. Profile Command Implementation

- [x] 2.1 Add `command_profile` in `babel_code_goat.py` with `profile <tests_dir> <solution_path> --lang <target_lang>` argument handling and generated tester validation. [extends `babel-code-goat-cli/support-rich-python-test-comparisons`]
- [x] 2.2 Add `profile` parser wiring in `babel_code_goat.py::build_parser` for `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, `--tol`, and `--lang`.
- [x] 2.3 Validate `-n` and `--warmup` so trials default to `1`, trial counts are positive, warmup defaults to `0`, and `--warmup <k>` is rejected when `k >= n`.
- [x] 2.4 Reuse the shared list-tests and run-selection helpers so `profile --list-tests` and `profile --run` match `test` behavior. [extends `async-test-execution-controls/support-async-test-selection-timeouts`]

## 3. Profiling Statistics

- [x] 3.1 Add runtime measurement around each tester execution using `time.perf_counter_ns()` and collect measured samples after warmup executions.
- [x] 3.2 Add a small statistics helper that returns numeric `mean` and population `std`, with `std` equal to `0` for one measured sample.
- [x] 3.3 Add optional memory sampling for `--memory` using standard-library process resource data and report non-negative kilobyte samples.
- [x] 3.4 Print profile JSON containing `status`, `passed`, `failed`, `runtime_ns`, and optional `memory_kb`, while preserving the expected exit code mapping for pass, fail, and error.

## 4. Timeout Accounting

- [x] 4.1 Include per-test timeout failures from generated testers in profile `failed` results and in measured runtime and memory samples. [extends `async-test-execution-controls/support-async-test-selection-timeouts`]
- [x] 4.2 Include total-timeout failures by mapping unreported in-scope test IDs to `failed` and retaining the elapsed runtime and memory sample for aggregate statistics. [extends `async-test-execution-controls/support-async-test-selection-timeouts`]
- [x] 4.3 Ensure failed or errored warmup executions stop profiling with an appropriate JSON error or failure rather than contributing to measured aggregates.

## 5. Tests

- [x] 5.1 Add `tests/test_babel_code_goat.py` coverage for successful `profile` output with default `-n 1`, including `runtime_ns.mean` and `runtime_ns.std`.
- [x] 5.2 Add coverage for `-n` with `--warmup` proving warmup executions are excluded from statistics.
- [x] 5.3 Add coverage for invalid `--warmup >= -n` and missing generated tester errors.
- [x] 5.4 Add coverage for `profile --memory` including `memory_kb.mean` and `memory_kb.std`, and for omission of `memory_kb` when `--memory` is absent.
- [x] 5.5 Add coverage for `profile --list-tests`, `profile --run`, and `profile --tol` parity with `test`.
- [x] 5.6 Add coverage for `profile --timeout-ms` and `profile --total-timeout-ms` showing timed-out IDs appear in `failed` and statistics are still present.

## 6. Verification

- [x] 6.1 Run `uv run pytest` and fix any regressions.
- [x] 6.2 Run `openspec status --change "add-profile-command"` and confirm the change is complete.
