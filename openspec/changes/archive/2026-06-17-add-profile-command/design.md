## Context

The CLI is implemented in `babel_code_goat.py` with one parser, `command_generate`, `command_test`, tester metadata helpers, discovery, and execution aggregation. `command_test` already owns language validation, tester-file validation, `--list-tests`, `--run`, `--tol`, `--timeout-ms`, and `--total-timeout-ms`; `profile` should reuse that path rather than define a second interpretation of test selection.

## Related Work

> **`babel-code-goat-cli/add-babel-code-goat`**: establishes the base CLI command model, tester metadata contract, language validation, and JSON status/exit-code conventions — informs `profile` parser shape and error handling because `profile` must run only after `generate` has produced the expected tester. _(see `babel-code-goat-cli/add-babel-code-goat`)_

> **`babel-code-goat-cli/add-async-test-selection-timeouts`**: establishes timeout failure reporting and test-selection controls for `test` — informs reuse of timeout parsing and selected-case execution because `profile` must mirror those flags and include timeout results in statistics. _(see `babel-code-goat-cli/add-async-test-selection-timeouts`)_

> **`babel-code-goat-cli/support-single-call-traceability`**: establishes stable discovered test IDs and one-entrypoint-call traceability — informs aggregating `passed` and `failed` by existing case IDs because profiling must not change discovery identity. _(see `babel-code-goat-cli/support-single-call-traceability`)_

## Goals / Non-Goals

**Goals:**
- Add `profile <tests_dir> <solution_path> --lang <target_lang>` with validation behavior matching `test`.
- Share discovery, tester metadata, selected-case filtering, tolerance parsing, and timeout parsing with `command_test`.
- Measure runtime with `time.perf_counter_ns()` around each selected case execution, compute mean and population standard deviation over non-warmup measurements, and include failed or timed-out executions in the samples.
- Add optional memory samples for `--memory` using stdlib process resource information where available, returning numeric kilobyte statistics without adding external dependencies.
- Preserve the existing `test` JSON contract unchanged.

**Non-Goals:**
- Provide per-test profiling breakdowns; the checkpoint only requires aggregate `runtime_ns` and optional `memory_kb`.
- Change generated tester file formats or discovery rules.
- Add a new dependency or a persistent benchmark storage format.

## Decisions

1. Add shared command preparation for `test` and `profile`.
   - Move the repeated validation flow from `command_test` into a helper that validates language, parses tolerance/timeouts, reads tester metadata, discovers cases, applies `--list-tests`/`--run`, and returns either prepared execution data or `ERROR_RESULT`.
   - Alternative considered: duplicate `command_test` and modify it for profiling. That would make future flag parity fragile.

2. Add `profile_cases(...)` beside `aggregate_results(...)`.
   - `aggregate_results(...)` should remain the pass/fail executor for `test`.
   - `profile_cases(...)` should loop over total trial count, execute selected cases through `execute_case(...)`, collect pass/fail status across measured trials, and collect runtime samples only for trial indexes `>= warmup`.
   - Alternative considered: add timing fields to `aggregate_results(...)`. Keeping profiling separate avoids changing the `test` output path.

3. Define `-n` as total trial count and `--warmup` as the number of initial trials excluded from statistics.
   - Enforce `n >= 1`, `warmup >= 0`, and `warmup < n` during argument validation.
   - Each trial runs the selected case set once; statistics are computed over all selected-case measurements from non-warmup trials.

4. Treat timeout failures as measured samples.
   - Wrap each case execution with a monotonic timer before applying the existing timeout-aware executor. If the executor returns false because of timeout or any other failure, keep the elapsed sample and record the case ID in `failed`.
   - When a total timeout prevents remaining cases from starting, record them as failed and add deterministic timeout-budget samples so aggregate arrays remain aligned with reported failures.

5. Keep memory profiling best-effort and numeric.
   - Use stdlib OS resource data when available to record child-process peak resident memory deltas in kilobytes around case execution. If precise child memory is unavailable, record `0` rather than failing the command; this keeps the `--memory` output contract stable across supported target languages and platforms.

## Risks / Trade-offs

- Memory measurements are platform-dependent and may be coarse → keep the contract to numeric aggregate kilobytes, document implementation as best-effort, and test the output shape instead of exact values.
- Multiple trials can make slow tests much slower → keep `-n` default at `1` and continue honoring per-test and total timeouts.
- Re-running tests can repeat side effects → this is inherent to profiling; selection flags let users constrain the profiled subset.
- Total-timeout samples for tests that never start are synthetic → make the helper deterministic and cover it with tests so aggregate statistics are predictable.

## Migration Plan

No data migration is required. Add the new command behind parser wiring in `babel_code_goat.py`, then extend the pytest suite in `tests/test_babel_code_goat.py`.

## Open Questions

- None.
