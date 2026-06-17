## 1. Shared CLI Preparation

- [x] 1.1 In `babel_code_goat.py`, extract the shared `command_test` validation path into a helper that validates language, parses `--tol`, `--timeout-ms`, and `--total-timeout-ms`, reads tester metadata, discovers cases, and applies `--run`. [extends `babel-code-goat-cli/add-babel-code-goat`]
- [x] 1.2 In `babel_code_goat.py`, keep `command_test` output unchanged while routing it through the shared preparation helper and existing `aggregate_results(...)`.
- [x] 1.3 In `babel_code_goat.py`, preserve `--list-tests` behavior for `test` and expose equivalent prepared-case listing for `profile`. [extends `babel-code-goat-cli/add-async-test-selection-timeouts`]

## 2. Profile Execution

- [x] 2.1 In `babel_code_goat.py`, add parsing and validation for `profile <tests_dir> <solution_path> --lang <target_lang>`, `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- [x] 2.2 In `babel_code_goat.py`, implement statistics helpers for numeric mean and population standard deviation with deterministic empty-sample handling avoided by `warmup < n`.
- [x] 2.3 In `babel_code_goat.py`, implement `profile_cases(...)` beside `aggregate_results(...)` to run selected cases for the requested trial count, exclude warmup trials from statistics, and aggregate `status`, `passed`, `failed`, and `runtime_ns`.
- [x] 2.4 In `babel_code_goat.py`, add optional `--memory` sampling that returns numeric `memory_kb.mean` and `memory_kb.std` without adding external dependencies.
- [x] 2.5 In `babel_code_goat.py`, include timed-out and total-timeout-failed tests in `failed` and in runtime and memory sample aggregation. [extends `babel-code-goat-cli/add-async-test-selection-timeouts`]

## 3. Verification

- [x] 3.1 In `tests/test_babel_code_goat.py`, add profile command tests for missing tester errors, unsupported language errors, generated tester preservation, and default runtime JSON shape.
- [x] 3.2 In `tests/test_babel_code_goat.py`, add tests for `-n`, `--warmup`, invalid warmup/trial values, and exclusion of warmup samples from statistics.
- [x] 3.3 In `tests/test_babel_code_goat.py`, add tests for `--memory`, `--list-tests`, `--run`, and `--tol` parity with `test`.
- [x] 3.4 In `tests/test_babel_code_goat.py`, add timeout profiling tests covering `--timeout-ms` and `--total-timeout-ms` with failed IDs and aggregate statistics present. [extends `babel-code-goat-cli/add-async-test-selection-timeouts`]
- [x] 3.5 Run `python -m pytest tests/test_babel_code_goat.py` and confirm the existing `test` command behavior remains unchanged.
