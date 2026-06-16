## 1. Shared CLI Setup

- [x] 1.1 Refactor `babel_code_goat.py` `command_test()` into shared helpers for parsing `--tol`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, validating tester metadata, discovering cases, and applying selected-test filtering [extends `babel-code-goat-cli/add-babel-code-goat`].
- [x] 1.2 Preserve existing `test` behavior in `babel_code_goat.py` by routing `command_test()` through the shared helpers and keeping current JSON/error/exit-code outputs unchanged [extends `babel-code-goat-cli/add-async-test-selection-timeouts`].
- [x] 1.3 Add regression coverage in `tests/test_babel_code_goat.py` confirming existing `test` selection, timeout, tolerance, and missing-tester cases still pass after the refactor.

## 2. Profile Command

- [x] 2.1 Add `profile <tests_dir> <solution_path> --lang <target_lang>` to `babel_code_goat.py` `build_parser()`, including `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` flags [extends `babel-code-goat-cli/add-babel-code-goat`].
- [x] 2.2 Implement `command_profile()` in `babel_code_goat.py` using the shared setup helpers so unsupported languages, missing testers, metadata errors, discovery errors, and unknown `--run` IDs return the standard error JSON.
- [x] 2.3 Validate profile-specific flags in `babel_code_goat.py`: default `-n` to `1`, default `--warmup` to `0`, reject non-integer or negative counts, and reject `--warmup >= -n`.
- [x] 2.4 Implement `profile --list-tests` in `babel_code_goat.py` as discovery-only output with no profiling statistics and no solution execution [extends `babel-code-goat-cli/add-async-test-selection-timeouts`].

## 3. Profiling Statistics

- [x] 3.1 Add small stats helpers in `babel_code_goat.py` for numeric `mean` and population `std`, returning `std` as `0` for a single measured sample.
- [x] 3.2 Add trial execution in `babel_code_goat.py` that runs warmup trials first, then runs measured trials through `aggregate_results()` while timing each measured trial with `time.perf_counter_ns()` [extends `babel-code-goat-cli/add-loop-as-test-support`].
- [x] 3.3 Build `profile` result JSON in `babel_code_goat.py` with `status`, stable merged `passed` and `failed` arrays, `runtime_ns.mean`, and `runtime_ns.std`.
- [x] 3.4 Add optional `--memory` sampling in `babel_code_goat.py` using standard-library child-process resource data where available, normalizing samples to kilobytes and emitting numeric `memory_kb.mean` and `memory_kb.std`.
- [x] 3.5 Ensure timed-out measured trials from `--timeout-ms` and `--total-timeout-ms` remain failed results and contribute timing and memory samples [extends `babel-code-goat-cli/add-async-test-selection-timeouts`].

## 4. Test Coverage

- [x] 4.1 Add `tests/test_babel_code_goat.py` coverage for `profile` missing tester errors and unsupported language errors preserving `{"status":"error","passed":[],"failed":[]}`.
- [x] 4.2 Add `tests/test_babel_code_goat.py` coverage for successful `profile` output shape, default one-trial behavior, `-n` multi-trial mean/std, and warmup exclusion.
- [x] 4.3 Add `tests/test_babel_code_goat.py` coverage for invalid `--warmup`, invalid `-n`, and invalid timeout/tolerance flags on `profile`.
- [x] 4.4 Add `tests/test_babel_code_goat.py` coverage for `profile --list-tests`, `profile --run <test_id>`, and `profile --tol <float>` parity with `test`.
- [x] 4.5 Add `tests/test_babel_code_goat.py` coverage proving `profile --memory` includes numeric `memory_kb.mean` and `memory_kb.std`.
- [x] 4.6 Add timeout coverage in `tests/test_babel_code_goat.py` proving per-test and total-timeout profile failures appear in `failed` and still include aggregate statistics.

## 5. Verification

- [x] 5.1 Run `python -m unittest tests.test_babel_code_goat` and fix any regressions.
- [x] 5.2 Run `openspec status --change "add-profile-command"` and confirm the proposal is ready for apply.
