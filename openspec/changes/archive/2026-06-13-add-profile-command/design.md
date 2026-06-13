## Context

`babel_code_goat.py` currently exposes `generate` and `test`. The `test` command validates the generated tester metadata, discovers stable `TestCase` IDs, optionally lists or selects cases, applies default tolerance and timeout flags, executes each selected case through a language-specific runner, and prints the standard `status`/`passed`/`failed` JSON shape. Profiling should reuse this path so benchmarks measure the same behavior that correctness checks already exercise.

## Goals / Non-Goals

**Goals:**

- Add a `profile` command with the requested positional order: `<tests_dir> <solution_path> --lang <target_lang>`.
- Share language validation, tester metadata validation, discovery, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` behavior with `test`.
- Run warmup executions before measured executions and exclude warmup samples from runtime and memory statistics.
- Report runtime mean and standard deviation in nanoseconds for measured profile executions.
- Report memory mean and standard deviation in kilobytes only when `--memory` is requested.
- Include timed-out profile executions in both the failed test list and aggregate statistics.

**Non-Goals:**

- Do not add a new tester file format or require `generate` to emit profile-specific files.
- Do not change `test` output or exit-code behavior.
- Do not add non-standard benchmarking or memory-profiling dependencies.
- Do not promise stable wall-clock values across machines, languages, or operating systems.

## Decisions

1. Reuse the `test` preparation path for `profile`.

   Factor the shared command preparation into helpers that parse tolerance and timeout flags, validate the tester file, read metadata, discover cases, handle `--list-tests`, and apply `--run`. `command_test` can keep printing the current result shape, while `command_profile` consumes the same prepared cases and entrypoint. This keeps flag parity anchored to one implementation.

   Alternative considered: implement `profile` as a separate discovery and validation path. Rejected because it would likely drift from `test` semantics and duplicate error handling.

2. Add a profiled execution result instead of changing every caller to infer timing from booleans.

   Keep the existing `execute_case` boolean contract for `test`, and add a small profiling wrapper that records `time.perf_counter_ns()` around each selected case execution. For timeout failures, the wrapper records the elapsed timeout-bound duration and marks the case failed. Total-timeout accounting should use the existing monotonic deadline approach and make every timeout-failed selected case visible in both `failed` and the measured sample set.

   Alternative considered: make all runners return rich result objects. Rejected for the initial change because the profiling wrapper can preserve the existing runner contract and keep the implementation smaller.

3. Treat `-n` as measured trials and `--warmup` as unmeasured trials.

   `profile` should run `warmup + n` rounds over the selected case set. Warmup rounds execute the same cases with the same timeout and tolerance settings, but their runtime and memory samples are discarded. Measured rounds contribute samples to the aggregate statistics. A case belongs in `failed` if it fails or times out in any measured round; otherwise it belongs in `passed`.

   Alternative considered: aggregate pass/fail only from the final measured round. Rejected because profiling repeated trials should surface nondeterministic failures instead of hiding them.

4. Use standard-library memory observation for `--memory`.

   Record memory in kilobytes with the best available standard-library process resource data around each measured execution. On platforms where only cumulative child-process usage is available, compute deltas per execution and clamp negative or unavailable readings to zero. Memory statistics should be omitted entirely unless `--memory` is present.

   Alternative considered: require a third-party profiler for consistent cross-platform memory readings. Rejected because the CLI is currently dependency-light and the checkpoint asks for an optional CLI flag, not a new runtime requirement.

5. Keep profile JSON deterministic in shape.

   Normal profiling runs print `status`, `passed`, `failed`, and `runtime_ns`. When `--memory` is requested, they also print `memory_kb`. `--list-tests` should behave like `test --list-tests` and skip measured execution, because listing is a discovery operation rather than a benchmark.

   Alternative considered: include zero-valued statistics for `--list-tests`. Rejected because it would imply a measurement happened when no solution code was executed.

## Risks / Trade-offs

- Timing measurements can vary by machine load -> tests should assert shape, numeric types, warmup exclusion, and broad timeout behavior rather than exact benchmark values.
- Memory measurement differs between in-process checks and subprocess-based targets -> use standard-library resource data and document that `memory_kb` is an aggregate profiling signal, not a precise allocator trace.
- Total timeouts can expire before all selected cases start -> make failed IDs explicit and ensure timeout-related samples are represented so the aggregate statistics still reflect the timeout outcome.
- Reusing boolean runners limits detail about failure causes -> acceptable for this change because the public contract reports pass/fail IDs and aggregate measurements, not per-case diagnostics.
