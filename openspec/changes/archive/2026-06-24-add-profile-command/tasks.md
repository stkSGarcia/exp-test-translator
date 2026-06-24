## 1. Shared CLI Validation

- [x] 1.1 Add `profile <tests_dir> <solution_path> --lang <target_lang>` to the argument parser with `-n`, `--warmup`, `--memory`, `--tol`, `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- [x] 1.2 Factor shared generated-tester validation, payload rediscovery, in-scope test selection, and environment setup out of `command_test` so `test` and `profile` use the same behavior.
- [x] 1.3 Validate profile-specific arguments: `-n` defaults to `1`, trials must be at least `1`, `--warmup` defaults to `0`, warmup must be non-negative, and warmup must be less than `n`.
- [x] 1.4 Ensure unsupported languages, missing tester files, stale tester payloads, discovery failures, invalid timeouts, invalid profile counts, and unknown `--run` IDs return the standard error JSON and exit code `2`.

## 2. Profiling Execution

- [x] 2.1 Add a profiling execution helper that records elapsed runtime in nanoseconds for each warmup and measured profile run.
- [x] 2.2 Reuse the normal scoped tester execution path for profile runs without timeout flags.
- [x] 2.3 Reuse the per-test scoped execution path for profile runs with `--timeout-ms` or `--total-timeout-ms`, including failed timeout and not-executed test reporting.
- [x] 2.4 Add optional best-effort memory measurement in kilobytes for measured profile runs when `--memory` is provided.
- [x] 2.5 Implement aggregation helpers that compute numeric mean and population standard deviation for measured runtime and optional measured memory observations, excluding warmup observations.

## 3. Profile Output Semantics

- [x] 3.1 Implement `command_profile` so passing measured runs output `status: "pass"`, all in-scope IDs in `passed`, no IDs in `failed`, and `runtime_ns` statistics.
- [x] 3.2 Implement failing measured runs so any failed or timed-out in-scope test appears in `failed`, successful IDs appear in `passed`, status is `fail`, and runtime statistics still include the measured observations.
- [x] 3.3 Include `memory_kb` mean/std only when `--memory` is provided.
- [x] 3.4 Implement `profile --list-tests` so it validates discovery and generated tester consistency, does not execute the solution, reports discovered IDs, and includes numeric `runtime_ns` statistics.
- [x] 3.5 Preserve existing `generate` and `test` output shape and exit code behavior.

## 4. Tests

- [x] 4.1 Add CLI tests for profile parser support, supported and unsupported languages, and generated-tester missing-file errors for each target language.
- [x] 4.2 Add tests for `-n`, `--warmup`, invalid trial counts, invalid warmup counts, and warmup exclusion from aggregate statistics.
- [x] 4.3 Add tests for runtime output shape, optional memory output shape, and omission of `memory_kb` without `--memory`.
- [x] 4.4 Add tests for `--list-tests`, `--run`, unknown test IDs, `--tol`, and discovery error behavior.
- [x] 4.5 Add tests proving per-test and total timeout results appear in `failed` and still contribute to runtime and memory statistics.
- [x] 4.6 Run the full test suite and fix regressions in existing `generate` and `test` behavior.
