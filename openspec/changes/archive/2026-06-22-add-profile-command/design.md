## Context

`babel_code_goat.py` already centralizes command parsing, tester metadata validation, discovery, tolerance parsing, timeout parsing, and per-language case execution. The current `test` command turns discovered `TestCase` objects into one pass/fail JSON object through `aggregate_results()`, which calls `execute_case()` for Python, JavaScript, TypeScript, C++, and Rust runners.

`profile` should sit on the same validation and execution path so that generated tester requirements, selection flags, tolerance behavior, async handling, and timeout semantics do not drift from `test`.

## Goals / Non-Goals

**Goals:**
- Add `profile <tests_dir> <solution_path> --lang <target_lang>` with validation parity for supported languages and existing generated tester files.
- Share discovery, `--list-tests`, `--run`, `--tol`, `--timeout-ms`, and `--total-timeout-ms` behavior with `test`.
- Execute warmup and measured trials while excluding warmup attempts from runtime and memory statistics.
- Report aggregate mean/std runtime in nanoseconds and optional memory in kilobytes.
- Include measured timeout attempts in aggregate statistics and failed test reporting.

**Non-Goals:**
- Do not add new target languages or change generated tester filenames.
- Do not change the existing `test` JSON output shape.
- Do not introduce non-stdlib profiling dependencies.
- Do not promise per-test detailed statistics; the required output is aggregate mean/std.

## Decisions

1. Add shared command setup helpers.

   Extract the common `test` setup flow into small helpers for parsing shared flags, validating the tester file and metadata, discovering tests, listing tests, and applying `--run`. `command_test()` and `command_profile()` should both use these helpers so unsupported languages, missing testers, invalid tolerances, invalid timeouts, list/run conflicts, and unknown test IDs all return the standard error JSON consistently.

   Alternative considered: copy `command_test()` and edit the copy. That is quicker initially, but it is likely to diverge as future CLI flags land.

2. Return rich execution attempts internally.

   Introduce an internal result type such as `CaseExecutionResult(passed: bool, runtime_ns: int, memory_kb: int | None)` and have a profiling wrapper measure each call to `execute_case()` with `time.perf_counter_ns()`. The existing `aggregate_results()` can either keep using boolean projection or be lightly adapted to consume the richer result and ignore measurement fields for `test`.

   Loop pseudo-tests should still produce an execution result by timing the existing `case.loop_pass` decision. This keeps output coverage identical to `test`.

   Alternative considered: implement a separate profiler for each target. That would duplicate runner behavior and increase the chance of `profile` evaluating cases differently from `test`.

3. Treat pass/fail as per test ID across all attempted runs.

   Warmup attempts and measured attempts should all use the same correctness checks and timeout handling. A test ID appears in `failed` if any in-scope warmup or measured attempt fails or times out; otherwise it appears in `passed`. Only measured attempts contribute to `runtime_ns` and `memory_kb`.

   Alternative considered: ignore warmup failures. That would hide correctness problems discovered before measurement and make warmup timeouts confusing.

4. Compute aggregate statistics from measured attempts.

   Collect runtime nanoseconds for every measured attempt, including attempts that time out after execution starts. Report population mean and population standard deviation with numeric values. If there is only one measured value, `std` is `0`. For `--list-tests`, report `runtime_ns` as `{"mean":0,"std":0}` without loading the solution.

   Alternative considered: report per-test arrays or sample standard deviation. The spec only needs aggregate mean/std, and population std is deterministic for a complete set of measured attempts.

5. Keep timeout accounting command-wide.

   Reuse `ExecutionOptions` and `effective_case_timeout()` for profile attempts. `--timeout-ms` applies to each attempt. `--total-timeout-ms` applies to the whole profile command, including warmups, measured attempts, and all selected cases. Attempts skipped because the total timeout has elapsed should mark their test IDs failed; attempts that started and timed out contribute collected runtime, while never-started attempts do not add synthetic measurements.

   Alternative considered: reset total timeout for each trial. That would make profile timeout behavior differ from `test` and weaken the meaning of a whole-command limit.

6. Implement memory measurement with stdlib best effort.

   When `--memory` is provided, collect memory in kilobytes for measured attempts using stdlib facilities around the process being executed. For subprocess-backed target runs, prefer sampling child process resident/high-water memory where available. For loop pseudo-tests or environments where per-attempt child memory is unavailable, record `0` rather than omitting the required `memory_kb` fields. Warmup memory samples are discarded.

   Alternative considered: add a third-party profiler. That would make the CLI heavier and is unnecessary for the required aggregate contract.

## Risks / Trade-offs

- Cross-platform memory readings may vary by OS and target runner shape -> keep the contract to numeric kilobyte statistics and test exact key presence/type rather than exact values.
- Repeated profiling can be slow for compiled languages because the existing per-case C++ and Rust paths may compile per attempt -> preserve correctness first, then optimize by reusing build artifacts only if existing runner structure allows it safely.
- Total timeout during warmup can leave no measured samples -> return `fail` with failed IDs and zeroed statistics when no measured sample was collected.
- Timing measurements include harness overhead -> document through tests as aggregate command-level profiling, not isolated entrypoint nanoseconds.

## Migration Plan

Add the parser and shared helpers first, then add the profiling aggregation path and tests. Rollback is simply removing the new `profile` parser branch and helper calls because no generated tester format migration is required.

## Open Questions

- None.
