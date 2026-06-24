## Context

`babel_code_goat.py` currently exposes `generate` and `test`. `test` validates that the selected generated tester exists, extracts its embedded payload, rediscover tests to detect stale testers, supports listing, selection, tolerance, and timeout flags, and prints strict result JSON. Filtered or timeout-aware execution already runs one temporary generated tester per selected test, which gives a natural hook for per-test timing.

The `profile` command needs the same correctness and workflow guarantees as `test`, but it also needs aggregate statistics across repeated trials and optional memory measurements. Warmup executions must affect neither correctness output nor statistics.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` with generated-tester validation parity with `test`.
- Reuse discovery, stale-tester validation, selection, tolerance, timeout, and result-accounting behavior from `test`.
- Measure elapsed runtime for executed tests across repeated trials and report mean and sample standard deviation in nanoseconds.
- Support warmup trials that execute before measured trials and are excluded from aggregate statistics.
- Optionally measure memory in kilobytes and report mean and sample standard deviation when `--memory` is supplied.
- Include timeout observations in aggregate statistics while still reporting timed-out test IDs as failed.

**Non-Goals:**

- Changing generated tester payloads or requiring users to regenerate for already-supported correctness behavior.
- Providing per-test or per-trial detail in the public JSON beyond aggregate statistics.
- Adding target-language-specific profilers, flamegraphs, or benchmark calibration.
- Guaranteeing cross-platform memory precision beyond a best-effort process-level peak measurement.

## Decisions

1. Share validation and run selection with `test`.

   The CLI should extract common helpers for language validation, tester existence checks, payload extraction, rediscovery, `--list-tests`/`--run` validation, timeout validation, and environment setup. `profile` should call those helpers so it fails the same way as `test` when the generated tester is missing or stale, when flags are invalid, or when a selected ID is absent.

   Alternative considered: implement an independent profile path. That would be quick initially but would duplicate fragile generated-tester and discovery precondition logic.

2. Reuse per-case filtered execution as the measured path.

   Profiling should execute selected tests one case at a time using temporary generated testers, as the current timeout-aware path already does. Each measured case execution records elapsed `perf_counter_ns()` duration around the tester subprocess or compiled tester invocation. A full profile trial is the ordered set of selected test executions; aggregate runtime uses all executed and timeout-affected observations from measured trials.

   Alternative considered: time a single full generated-tester invocation per trial. That is simpler, but it cannot include per-test timeout failures or selected IDs in statistics with the same precision as the existing filtered path.

3. Treat warmup as real execution with discarded measurements.

   `--warmup <k>` should run before measured trials using the same selected tests, timeout, tolerance, and memory settings. Warmup failures should not contribute to final `passed`/`failed` arrays or statistics; measured trials determine the reported correctness result. `k` must be non-negative and less than `n`.

   Alternative considered: skip correctness tracking during warmup. That reduces overhead slightly but risks exercising a different execution path from measured trials.

4. Aggregate correctness across measured trials deterministically.

   A test ID should be reported in `passed` only if it passes in every measured trial where it is selected. A test ID should be reported in `failed` if any measured trial fails or times out for that ID. Result ordering should follow discovery order, narrowed by `--run` when present. If `--list-tests` is used, `profile` should match `test` list-only behavior and include empty runtime statistics because no solution execution occurs.

   Alternative considered: report only the last trial's correctness. That could hide intermittent failures found during profiling.

5. Use process-level memory measurement as optional best effort.

   When `--memory` is provided, the runner should capture peak resident memory for each measured subprocess where the platform exposes it, then aggregate those observations in kilobytes. If a test times out, the memory observation available at timeout/cleanup is still included; if memory cannot be observed on a platform, the command should report an error rather than silently fabricate values.

   Alternative considered: infer memory from Python's `tracemalloc`. That would miss JavaScript, TypeScript, C++, and Rust solution memory and would not match the cross-language CLI surface.

## Risks / Trade-offs

- Profiling via subprocess boundaries includes tester startup and compile overhead for C++/Rust temporary testers -> Keep the contract explicit as CLI-level profiling and cover the observed behavior with tests.
- Repeating tests one at a time can be slower than full-suite execution -> It preserves timeout and per-test aggregation semantics, which are required for this command.
- Memory measurement APIs differ across platforms -> Implement a narrow, tested best-effort path and return the standard error JSON when memory profiling is unavailable.
- Intermittent failures across trials can make statistics harder to interpret -> Report any such test as failed while still including all measured observations in aggregates.
