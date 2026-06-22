## 1. Shared CLI Setup

- [x] 1.1 Extract shared parsing and validation helpers for `test`/`profile` language checks, tolerance parsing, timeout parsing, and `--list-tests` plus `--run` conflict handling.
- [x] 1.2 Extract shared generated-tester validation and test discovery so both commands require existing tester metadata and exclude the solution path from discovery.
- [x] 1.3 Extract shared selected-test filtering so unknown `--run <test_id>` returns the standard error JSON.
- [x] 1.4 Add a `profile` subcommand parser with positional order `<tests_dir> <solution_path>` and flags `--lang`, `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.

## 2. Profiling Execution

- [x] 2.1 Add trial and warmup validation helpers for positive `-n`, non-negative `--warmup`, and `warmup < trials`.
- [x] 2.2 Add an internal execution-attempt result that records pass/fail, runtime nanoseconds, and optional memory kilobytes while preserving existing boolean behavior for `test`.
- [x] 2.3 Implement a profile aggregation path that runs warmup attempts before measured attempts for each in-scope case.
- [x] 2.4 Ensure failed or timed-out warmup and measured attempts mark their test IDs failed, while only measured attempts contribute to runtime and memory statistics.
- [x] 2.5 Reuse per-test and total timeout calculation across all profile attempts, including failed reporting for tests skipped after total timeout exhaustion.
- [x] 2.6 Implement mean/std helpers for runtime and memory values, returning zeroed statistics when no measured values are collected.

## 3. Output and Memory Reporting

- [x] 3.1 Implement `profile --list-tests` so it reports discovered IDs without loading the solution and includes zeroed `runtime_ns` statistics.
- [x] 3.2 Implement normal `profile` JSON output with `status`, `passed`, `failed`, and `runtime_ns` mean/std, preserving exit codes 0, 1, and 2.
- [x] 3.3 Add `--memory` measurement using stdlib facilities around measured attempts and include `memory_kb` mean/std when requested.
- [x] 3.4 Ensure standard error cases still print exactly `{"status":"error","passed":[],"failed":[]}` without required profiling statistic keys.

## 4. Regression Tests

- [x] 4.1 Add CLI tests for missing tester, unsupported language, tester preservation, invalid trial/warmup values, and invalid shared flags.
- [x] 4.2 Add profile output tests for default one-trial runs, multi-trial mean/std runtime fields, failing tests, and exit codes.
- [x] 4.3 Add warmup tests proving warmups execute before measured trials and are excluded from aggregate statistics.
- [x] 4.4 Add `--list-tests`, `--run`, `--tol`, per-test timeout, and total-timeout tests showing parity with `test` semantics.
- [x] 4.5 Add `--memory` tests that assert `memory_kb.mean` and `memory_kb.std` are numeric when memory profiling is requested.

## 5. Verification

- [x] 5.1 Run the focused profile-related test cases.
- [x] 5.2 Run the full Python test suite.
- [x] 5.3 Run `openspec status --change "add-profile-command"` and confirm the change is apply-ready.
