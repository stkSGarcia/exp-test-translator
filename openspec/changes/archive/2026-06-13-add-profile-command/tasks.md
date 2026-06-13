## 1. Shared CLI Preparation

- [x] 1.1 Extract shared `test`/`profile` preparation helpers for language validation, tolerance parsing, timeout parsing, tester-file lookup, metadata validation, discovery, `--list-tests`, and `--run` selection.
- [x] 1.2 Update `command_test` to use the shared preparation helpers while preserving the existing JSON output and exit-code behavior.
- [x] 1.3 Add `profile` parser support with positional arguments `<tests_dir> <solution_path>` plus `--lang`, `--tol`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, `-n`, `--warmup`, and `--memory`.
- [x] 1.4 Validate `-n` as a positive integer, validate `--warmup` as a non-negative integer with `warmup < n`, and return the standard error JSON for invalid profile arguments.

## 2. Profile Execution and Statistics

- [x] 2.1 Add numeric statistics helpers that return population `mean` and `std` for runtime nanosecond and memory kilobyte samples.
- [x] 2.2 Add a profiled execution wrapper around `execute_case` that records elapsed `runtime_ns`, preserves pass/fail outcomes, and records timeout-bounded failed executions as samples.
- [x] 2.3 Implement profile warmup and measured trial loops so warmup executions run first and measured statistics exclude warmup samples.
- [x] 2.4 Aggregate measured profile outcomes so each selected test ID appears once in either `passed` or `failed`, with any measured failure placing that ID in `failed`.
- [x] 2.5 Implement optional `--memory` sampling with standard-library process resource data and include `memory_kb` only when requested.

## 3. Profile Command Behavior

- [x] 3.1 Implement `command_profile` normal-run output with `status`, `passed`, `failed`, `runtime_ns`, and optional `memory_kb`.
- [x] 3.2 Implement `profile --list-tests` with the same metadata validation, discovery-only execution behavior, exact JSON output, and exit code as `test --list-tests`.
- [x] 3.3 Ensure `profile --run <test_id>` executes and reports only the selected discovered test, and returns the standard error JSON for unknown IDs.
- [x] 3.4 Ensure `profile --tol <float>` follows the same default tolerance and invalid-value behavior as `test --tol`.
- [x] 3.5 Ensure profile per-test and total timeout behavior marks timed-out or not-executed selected tests as failed and includes timeout outcomes in runtime and memory statistics.

## 4. Verification

- [x] 4.1 Add CLI tests for `profile` unsupported language, missing tester, tester preservation, invalid trial/warmup values, output shape, and exit codes.
- [x] 4.2 Add profile statistics tests for default one-trial behavior, multiple measured trials, warmup exclusion, runtime numeric mean/std, and memory flag inclusion/omission.
- [x] 4.3 Add flag parity tests for `profile --list-tests`, `profile --run`, unknown selected IDs, `--tol`, invalid tolerance, and timeout flag validation.
- [x] 4.4 Add timeout profiling tests proving timeout failures appear in `failed` and contribute to aggregate statistics.
- [x] 4.5 Run the repository test suite and OpenSpec status/validation checks for `add-profile-command`.
