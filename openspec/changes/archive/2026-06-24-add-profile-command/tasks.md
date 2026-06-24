## 1. CLI Preflight and Parser

- [x] 1.1 Extract shared language validation, tester existence, payload verification, discovered ID collection, `--run` validation, and `--list-tests` behavior from `command_test`.
- [x] 1.2 Preserve the existing `test` command output shape, exit codes, selection behavior, timeout behavior, and tolerance handling after refactoring.
- [x] 1.3 Add the `profile <tests_dir> <solution_path> --lang <target_lang>` parser with `-n`, `--warmup`, `--memory`, `--tol`, `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- [x] 1.4 Validate profile arguments, including default `-n 1`, non-negative warmup, positive measured trial count, and `--warmup < -n`.

## 2. Profiling Execution

- [x] 2.1 Implement selected-run execution helpers that `profile` can call for warmup and measured trials while preserving timeout and selected-ID semantics.
- [x] 2.2 Measure each profiled selected-run execution with nanosecond precision and collect exactly `-n` measured runtime samples.
- [x] 2.3 Exclude successful warmup runs from runtime and memory aggregates while still surfacing harness errors.
- [x] 2.4 Include timed-out measured runs in runtime statistics and merge timed-out IDs into the final `failed` list.
- [x] 2.5 Implement optional `--memory` sampling and aggregate measured memory samples in kilobytes.
- [x] 2.6 Compute mean and population standard deviation for `runtime_ns` and, when requested, `memory_kb`.

## 3. JSON Results and Exit Codes

- [x] 3.1 Print exactly one profile JSON line with `status`, `passed`, `failed`, and `runtime_ns` for measured profile runs.
- [x] 3.2 Include `memory_kb` only when `--memory` is provided.
- [x] 3.3 Return exit code `0` for passing profiles, `1` for failing profiles, and `2` for profile errors.
- [x] 3.4 Keep `profile --list-tests` output compatible with `test --list-tests` and omit aggregate profiling fields.

## 4. Tests

- [x] 4.1 Add tests for missing generated tester errors and confirming `profile` does not create tester files.
- [x] 4.2 Add tests for `--list-tests`, `--run`, unknown selected IDs, unsupported language, and `--tol` parity with `test`.
- [x] 4.3 Add tests for default trial count, `-n`, warmup validation, and warmup exclusion from statistics.
- [x] 4.4 Add tests for runtime aggregate JSON shape and pass/fail exit codes.
- [x] 4.5 Add tests for `--memory` inclusion and omission.
- [x] 4.6 Add tests showing per-test and total timeouts contribute to aggregate statistics and failed IDs.
- [x] 4.7 Run the existing test suite and confirm current `test` behavior did not regress.
