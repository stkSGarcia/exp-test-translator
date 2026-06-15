## 1. CLI and Shared Setup

- [x] 1.1 In `babel_code_goat.py`, extract shared `test` setup from `command_test` into a helper that validates language, tolerance, timeout flags, tester metadata, discovery, `--list-tests`, and `--run` selection. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 1.2 In `babel_code_goat.py`, add a `profile` parser with positional arguments `<tests_dir>` and `<solution_path>`, required `--lang`, and flags `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`. [extends `babel-code-goat-cli/support-rich-test-comparisons`]
- [x] 1.3 In `babel_code_goat.py`, implement profile argument validation for positive trial count and `0 <= warmup < n`, returning the standard JSON error result on invalid input.

## 2. Profiling Execution

- [x] 2.1 In `babel_code_goat.py`, implement profile trial execution by reusing `aggregate_results` for each warmup and measured run. [extends `async-test-execution-controls/add-async-test-selection-timeouts`]
- [x] 2.2 In `babel_code_goat.py`, measure each measured trial with `time.perf_counter_ns()` and compute `runtime_ns.mean` and `runtime_ns.std` over non-warmup samples.
- [x] 2.3 In `babel_code_goat.py`, implement optional `--memory` sampling and include `memory_kb.mean` and `memory_kb.std` only when requested.
- [x] 2.4 In `babel_code_goat.py`, ensure timeout failures from `--timeout-ms` and `--total-timeout-ms` remain in `failed` and their elapsed measurements contribute to statistics. [extends `async-test-execution-controls/add-async-test-selection-timeouts`]
- [x] 2.5 In `babel_code_goat.py`, print profile JSON with at least `status`, `passed`, `failed`, and `runtime_ns`, and return the same status-derived exit codes as `test`.

## 3. Test Coverage

- [x] 3.1 In `tests/test_babel_code_goat.py`, add coverage that `profile` errors when the generated tester file for the requested language is missing.
- [x] 3.2 In `tests/test_babel_code_goat.py`, add coverage for `--list-tests`, `--run`, `--tol`, `--timeout-ms`, and `--total-timeout-ms` parity with `test`. [extends `async-test-execution-controls/add-async-test-selection-timeouts`]
- [x] 3.3 In `tests/test_babel_code_goat.py`, add coverage that `-n` and `--warmup` exclude warmup runs from runtime statistics and reject `warmup >= n`.
- [x] 3.4 In `tests/test_babel_code_goat.py`, add coverage that `runtime_ns` always contains numeric `mean` and `std`, and `memory_kb` appears only when `--memory` is supplied.

## 4. Verification

- [x] 4.1 Run the focused Python unittest suite for `tests/test_babel_code_goat.py`.
- [x] 4.2 Run `openspec status --change "add-profile-command"` and confirm the change artifacts are complete.
