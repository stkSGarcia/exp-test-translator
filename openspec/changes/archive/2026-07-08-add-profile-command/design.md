## Context

The CLI currently exposes `generate` and `test` in `babel_code_goat.py`. `command_test` already validates generated tester presence, reloads tester payload metadata, applies `--list-tests` and `--run`, forwards tolerance and per-test timeout state through the environment, enforces total timeout with `subprocess.run(..., timeout=...)`, validates tester JSON, and maps whole-run timeout to failed in-scope IDs. The new `profile` command should preserve those semantics while adding repeated measurement and aggregate statistics.

## Related Work

**`babel-code-goat-cli/support-rich-python-test-comparisons`**: Defines the root-level CLI command surface and JSON test result contract — informs reusing the existing tester payload validation and result validation shape because profiling must execute the same generated language-specific testers rather than introduce a separate harness.

**`async-test-execution-controls/support-async-test-selection-timeouts`**: Defines selected test execution and timeout accounting — informs sharing selection, per-test timeout, total timeout, and timeout failure handling because profiling must include timeout outcomes in both failed IDs and aggregate measurements.

## Goals / Non-Goals

**Goals:**
- Add `profile <tests_dir> <solution_path> --lang <target_lang>` with the required profiling flags and the same selection, timeout, and tolerance flags as `test`.
- Reuse the existing generated tester validation and execution behavior so `profile` and `test` remain consistent.
- Report deterministic JSON keys for command status, passed/failed IDs, runtime mean/std, and optional memory mean/std.
- Exclude warmup runs from statistics while still validating all requested measured runs.
- Include timeout outcomes in aggregate statistics.

**Non-Goals:**
- Do not change generated tester source formats unless needed to preserve current result output.
- Do not add per-test percentile reporting, histograms, or detailed trial traces.
- Do not introduce external profiling dependencies.
- Do not implement OS-specific high-precision memory accounting beyond the standard-library approach chosen for this CLI.

## Decisions

1. Share execution setup between `test` and `profile` in `babel_code_goat.py`.

   Extract the tester validation, discovered-test comparison, in-scope selection, environment construction, subprocess invocation, and JSON result validation currently embedded in `command_test` into helper functions used by both commands. `command_test` can continue printing the simple result shape, while `command_profile` wraps the same execution helper with measurement. _(see `babel-code-goat-cli/support-rich-python-test-comparisons`)_

   Alternative considered: implement `profile` by shelling out to `babel_code_goat.py test` repeatedly. That would preserve behavior but would make timeout accounting, memory measurement, and structured error handling harder to control and test.

2. Measure whole tester invocations rather than individual entrypoint calls.

   Each measured trial will execute the same selected tester subprocess that `test` would execute. Runtime is captured around the subprocess execution using `time.perf_counter_ns()`. This keeps behavior uniform across Python, JavaScript, TypeScript, C++, and Rust testers and avoids changing generated test harness internals.

   Alternative considered: instrument generated testers per test case. That could provide more granular data, but it would require changing every language harness and would raise the risk of diverging from `test` command behavior.

3. Treat warmup as extra executions before measured trials.

   `-n` is the number of measured trials, defaulting to `1`. `--warmup <k>` runs `k` unmeasured executions before collecting statistics and is rejected when `k >= n`, as required. Warmup failures should still cause the command to surface an error/failure result rather than silently proceed with invalid measurement state.

   Alternative considered: interpret `-n` as total runs including warmup. The checkpoint explicitly says warmup runs are excluded from statistics and `k < n`, so measured-trial semantics are less ambiguous for users.

4. Use population standard deviation for deterministic small-sample output.

   Compute `mean` and `std` over measured trial samples with a standard-library helper. For a single measured trial, `std` is `0`. This avoids dependency churn and keeps JSON values numeric.

   Alternative considered: sample standard deviation. Population standard deviation is simpler for command output and avoids undefined or special-case output for one trial.

5. Use standard-library peak child memory measurement where available.

   When `--memory` is requested, collect memory in kilobytes for each measured trial using standard-library process resource data around subprocess execution. If a platform cannot provide meaningful child-process memory deltas, report `0` rather than changing the output shape. This keeps the command dependency-free while satisfying the optional `memory_kb` contract.

   Alternative considered: add `psutil` or a platform-specific sampler. That would improve precision but introduces a new runtime dependency for a compact CLI.

6. Include timeout trials as measured samples.

   The measurement wrapper records elapsed runtime before mapping a per-test or total timeout to the same failed IDs that `test` reports. If `--memory` is enabled, the memory sample from that timed-out execution is retained. _(see `async-test-execution-controls/support-async-test-selection-timeouts`)_

   Alternative considered: exclude timed-out trials as failed measurements. The checkpoint requires timeout timing and memory data to be included in mean/std calculations.

## Risks / Trade-offs

- [Risk] Refactoring `command_test` could alter existing result validation or exit codes -> Mitigation: keep `command_test` tests intact and add regression tests around unsupported language, missing tester, `--list-tests`, `--run`, tolerance, and timeout behavior.
- [Risk] Whole-process runtime can include tester startup overhead -> Mitigation: document through command behavior and provide `--warmup` so users can reduce one-time effects.
- [Risk] Standard-library memory accounting may be coarse or platform-dependent -> Mitigation: keep `memory_kb` optional, numeric, and dependency-free; focus tests on output shape and non-negative values.
- [Risk] Repeated compiled profiling may include compile time if compilation stays inside the existing compiled runner helper -> Mitigation: prefer compiling once per profile invocation before measured runs when practical, while keeping `test` behavior unchanged.

## Migration Plan

- Add helper functions and `command_profile` in `babel_code_goat.py`.
- Add parser coverage for `profile` and its flags.
- Add focused pytest coverage in `tests/test_babel_code_goat.py`.
- No data migration or rollback steps are required; removing the parser entry restores the prior command surface.

## Open Questions

- Should compiled targets exclude compile time from profiling by compiling once before measured trials? The design prefers that where practical, but the implementation should preserve current `test` behavior for the existing command.
