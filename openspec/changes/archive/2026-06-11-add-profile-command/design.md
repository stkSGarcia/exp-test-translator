## Context

`babel_code_goat.py` already validates language-specific tester files, reads generated metadata, discovers test cases, applies selection/timeout/tolerance options, and executes cases through target-specific runners. The new `profile` command should reuse that path so profiling answers the same correctness question as `test` while adding repeated timing and optional memory statistics.

The checkpoint defines `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]`, which intentionally differs from the existing `test <solution_path> <tests_dir>` positional order. The implementation must preserve that command shape while sharing the same internal discovery and execution machinery.

## Goals / Non-Goals

**Goals:**

- Add `profile` command parsing, validation, and dispatch for every supported target language.
- Reuse the generated tester metadata and discovery preconditions from `test`.
- Support profiling-specific `-n`, `--warmup`, and `--memory` flags.
- Support `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` with behavior matching `test` where applicable.
- Produce deterministic single-line JSON with runtime mean/std and optional memory mean/std.
- Include timed-out executions in the statistics and failed-test accounting.

**Non-Goals:**

- Change the `test` command output schema or positional argument order.
- Add external benchmarking, memory-profiler, or package-manager dependencies.
- Parallelize profile trials or test case execution.
- Guarantee language-runtime-level memory precision beyond the process measurements available to the CLI.

## Decisions

1. Share the `test` discovery and execution path behind a richer result type.

   `profile` should load the expected tester file, parse metadata, discover cases, apply `--list-tests`/`--run`, and pass the same tolerance and timeout options used by `test`. Internally, case execution should return a small result object that includes pass/fail, elapsed nanoseconds, timeout state, and optional memory kilobytes; `test` can keep projecting that result down to booleans while `profile` aggregates measurements.

   Alternative considered: implement `profile` as a wrapper that shells out to the CLI `test` command repeatedly. That would duplicate JSON parsing, make timeout attribution harder, and prevent memory measurements from being gathered in the same process tree.

2. Treat `-n` as total trials and `--warmup` as the number of leading trials excluded from statistics.

   This follows the checkpoint constraint that `--warmup <k>` must satisfy `k < n`, ensuring at least one measured trial remains. All trials, including warmups, should still contribute to pass/fail accounting because a profiling run should not hide correctness failures.

   Alternative considered: make warmups extra runs in addition to `n` measured trials. That is common in some benchmark tools, but it conflicts with the explicit `k < n` validation rule.

3. Aggregate runtime and memory per full selected trial.

   Runtime should be measured with `time.perf_counter_ns()` around each selected trial. `runtime_ns.mean` and `runtime_ns.std` should use the measured, non-warmup samples. When `--memory` is enabled, the profile path should track the peak kilobytes observed across case subprocesses for each trial and compute the same statistics for `memory_kb`.

   Alternative considered: report per-test arrays or per-case nested statistics. The checkpoint asks for mean/std fields and the existing CLI favors compact result JSON, so a single aggregate per profile invocation is easier to consume and test.

4. Use population standard deviation.

   The standard deviation should divide by the number of measured samples, not `n - 1`, so one measured sample reports `std: 0`. This keeps the default `-n 1` behavior simple and avoids special-case undefined values in JSON.

   Alternative considered: use sample standard deviation. That is useful for statistical inference, but it creates awkward output for the default one-trial invocation.

5. Preserve timeout accounting inside measured samples.

   If a per-test timeout or total timeout occurs during a measured trial, the elapsed timeout duration remains part of that trial's runtime sample. Timed-out or total-timeout-skipped selected tests are reported in `failed`; memory samples, when requested, include whatever peak was observed before timeout.

   Alternative considered: drop timeout samples from stats. That would make slow or hung solutions look artificially fast and contradict the checkpoint.

## Risks / Trade-offs

- Memory measurement can vary by platform and process lifetime -> keep it optional, numeric, and based on available child-process peak measurements rather than promising exact allocator-level data.
- Running correctness checks multiple times can expose nondeterministic solutions -> report a test failed if it fails in any trial so callers can see instability instead of averaged success.
- Sharing execution internals may require changing boolean runner interfaces -> keep compatibility by adding small adapters so existing `test` behavior and JSON remain unchanged.
- Total timeout with many selected tests can leave some cases unexecuted -> mirror `test` behavior by marking those selected IDs failed and include the measured timeout duration in the trial sample.

## Migration Plan

No data migration is required. Existing `generate` and `test` commands continue to work unchanged. Rollback is limited to removing `profile` parser dispatch, the profiling aggregation helpers, and profile-specific tests.

## Open Questions

None.
