## Context

The CLI currently has a `generate` command that writes language-specific tester metadata and a `test` command that validates the tester, rediscovers cases, applies selection/tolerance/timeout flags, and executes selected cases through `aggregate_results`. Profiling should use the same discovery and execution contract so a profile run measures the same behavior users already validate with `test`.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang>` without changing existing `generate` or `test` behavior.
- Reuse tester metadata, discovery, selection, tolerance, timeout, and per-language execution paths from `test`.
- Measure runtime over repeated trials and optionally report memory statistics with deterministic JSON field names.
- Keep warmup handling explicit: `-n` is the total number of trials, the first `--warmup` trials are excluded from statistics, and at least one measured trial remains.

**Non-Goals:**

- Do not generate a new profiler-specific tester file format.
- Do not add external benchmarking or memory-profiling dependencies.
- Do not add per-test timing breakdowns; this change reports aggregate runtime and optional memory statistics for the selected execution set.

## Decisions

- Add a `command_profile` path that shares validation helpers with `command_test`. This avoids two subtly different interpretations of supported languages, tester metadata, `--tol`, `--run`, `--list-tests`, and timeout flags.
- Extract the common test setup into helpers such as tester validation, discovery, and case selection. `command_test` can keep its existing output contract while `command_profile` can add statistics to normal profiling runs.
- Treat `-n` as total trials and `--warmup` as the count of leading trials to discard. This follows the checkpoint constraint `k < n` and gives a measured sample count of `n - k`.
- Measure each trial around the selected execution set with `time.perf_counter_ns()`. Trial results are aggregated so any measured trial failure marks that test ID failed; IDs that never fail across measured trials remain passed.
- Compute `mean` and population `std` for runtime and memory samples. A single measured sample has standard deviation `0`.
- Implement `--memory` with standard-library facilities only, using platform resource counters where available. The output remains in kilobytes and is reported only when the flag is present.

## Risks / Trade-offs

- [Risk] Repeated execution may make stateful solutions behave differently across trials -> Mitigation: document the profile contract around repeated selected execution and aggregate measured-trial failures conservatively.
- [Risk] Memory counters are platform-dependent -> Mitigation: keep the contract at aggregate `memory_kb` mean/std and use standard-library counters without promising per-allocation precision.
- [Risk] Profiling compiled targets may include compilation time if implemented around existing per-case runners -> Mitigation: preserve existing runner behavior initially, then isolate compile caching only if tests expose unstable or misleading measurements.
- [Risk] Total timeout semantics across repeated trials can be confusing -> Mitigation: apply `--total-timeout-ms` per trial execution set, mirroring `test`, and include timed-out measured trials in the statistics.
