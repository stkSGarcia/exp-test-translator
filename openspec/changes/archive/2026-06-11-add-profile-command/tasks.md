## 1. CLI Parsing and Preconditions

- [x] 1.1 Add a `profile` subcommand with positional arguments `<tests_dir> <solution_path>` and `--lang <target_lang>`.
- [x] 1.2 Add `profile` flags `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- [x] 1.3 Validate supported languages, trial counts, warmup counts, timeouts, and tolerance values so invalid inputs print the standard error JSON and exit 2.
- [x] 1.4 Reuse tester-file validation and metadata loading so `profile` requires the generated tester file and never creates or modifies tester artifacts.
- [x] 1.5 Reuse discovery for `profile`, including standard discovery errors and generated tester metadata checks.

## 2. Execution Measurement Core

- [x] 2.1 Introduce an execution result structure that records case ID, pass/fail, elapsed nanoseconds, timeout state, and optional memory kilobytes.
- [x] 2.2 Adapt Python, JavaScript, TypeScript, C++, and Rust case runners to produce execution results while preserving existing `test` behavior through compatibility helpers.
- [x] 2.3 Measure each selected profile trial with `time.perf_counter_ns()` and keep the first `--warmup` trial measurements out of statistics.
- [x] 2.4 Implement population mean/std helpers for `runtime_ns` and optional `memory_kb`, with `std` equal to `0` for one measured sample.
- [x] 2.5 Implement optional child-process peak memory tracking for `--memory` without adding external package dependencies.

## 3. Profile Semantics

- [x] 3.1 Implement `profile --list-tests` to match `test --list-tests`, including no solution execution and discovery-order IDs.
- [x] 3.2 Implement `profile --run <test_id>` selection and unknown-ID error handling.
- [x] 3.3 Aggregate `passed` and `failed` across all profile trials so any trial failure marks the test ID failed.
- [x] 3.4 Apply `--timeout-ms` and `--total-timeout-ms` during profile trials and include timeout durations in measured statistics.
- [x] 3.5 Apply `--tol` to profile comparisons with the same default tolerance behavior as `test`.

## 4. JSON Output and Exit Codes

- [x] 4.1 Emit single-line profile JSON with `status`, `passed`, `failed`, and `runtime_ns` for profile executions that run solution code.
- [x] 4.2 Include `memory_kb` with `mean` and `std` only when `--memory` is provided.
- [x] 4.3 Return exit code 0 for `pass`, 1 for `fail`, and 2 for `error`.
- [x] 4.4 Preserve the existing `test` output schema and exit behavior.

## 5. Verification

- [x] 5.1 Add tests for profile parser preconditions, missing tester files, unsupported languages, and invalid `-n`/`--warmup` values.
- [x] 5.2 Add tests for successful profile output, failing profile output, one-sample `std: 0`, and warmup exclusion from statistics.
- [x] 5.3 Add tests for `--memory` output shape and numeric `memory_kb.mean`/`memory_kb.std`.
- [x] 5.4 Add tests for `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` parity with `test`.
- [x] 5.5 Run the relevant unit test suite and confirm `openspec status --change "add-profile-command"` reports the change as apply-ready.
