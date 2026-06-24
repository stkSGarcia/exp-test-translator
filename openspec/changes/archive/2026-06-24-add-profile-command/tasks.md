## 1. Shared CLI Validation

- [x] 1.1 Add a `profile` subcommand with positional arguments `tests_dir` and `solution_path`, required `--lang`, `-n`, `--warmup`, `--memory`, and parity flags `--tol`, `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- [x] 1.2 Extract shared validation for supported languages, mutually exclusive `--list-tests`/`--run`, positive timeout values, generated tester existence, payload extraction, stale tester rediscovery, selected test lookup, and runner environment setup.
- [x] 1.3 Apply profile-specific validation for `n >= 1`, `warmup >= 0`, and `warmup < n`, returning the strict error JSON and exit code `2` on invalid input.

## 2. Profiling Execution

- [x] 2.1 Refactor the filtered per-test execution path so it can optionally return per-case runtime observations while preserving existing `test` behavior.
- [x] 2.2 Implement measured profile trials using `time.perf_counter_ns()` around each selected test execution and exclude warmup trial observations from aggregates.
- [x] 2.3 Aggregate correctness across measured trials so a test ID passes only if it passes in every measured trial and fails if any measured trial fails or times out.
- [x] 2.4 Include per-test and total timeout observations in runtime statistics while reporting timed-out and not-yet-executed selected IDs in `failed`.
- [x] 2.5 Implement optional process-level memory measurement for profile runs and aggregate measured memory observations in kilobytes when `--memory` is provided.

## 3. Profile Output

- [x] 3.1 Add statistic helpers that compute numeric mean and standard deviation for runtime and memory observation lists, including single-observation and empty list cases.
- [x] 3.2 Emit one-line profile JSON with `status`, `passed`, `failed`, and `runtime_ns`; include `memory_kb` only when `--memory` is supplied.
- [x] 3.3 Preserve strict error output `{"status":"error","passed":[],"failed":[]}` for profile precondition, discovery, generated-tester validation, runner, and unavailable memory profiling errors.
- [x] 3.4 Support `profile --list-tests` without invoking the solution and report discovered IDs with runtime statistics present.

## 4. Tests

- [x] 4.1 Add parser or CLI tests for `profile` flag acceptance, invalid language, invalid `-n`, invalid `--warmup`, missing generated tester, and list/run conflicts.
- [x] 4.2 Add end-to-end profile tests for passing and failing Python solutions, output shape, runtime `mean`/`std`, exit codes, and generated-tester prerequisite behavior.
- [x] 4.3 Add profile tests for `--run`, `--list-tests`, `--tol`, `--timeout-ms`, and `--total-timeout-ms` parity with `test`.
- [x] 4.4 Add profile tests proving warmup executions are excluded from reported statistics.
- [x] 4.5 Add memory profiling coverage for successful runs and timeout-included memory observations when the platform supports process-level memory measurement.

## 5. Verification

- [x] 5.1 Run the focused new profile tests.
- [x] 5.2 Run the existing test suite to verify `generate` and `test` behavior did not regress.
- [x] 5.3 Run OpenSpec validation for `add-profile-command`.
