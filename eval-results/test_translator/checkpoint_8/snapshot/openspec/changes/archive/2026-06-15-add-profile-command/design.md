## Context

`babel_code_goat.py` currently owns CLI parsing, generated tester metadata validation, test discovery, language-specific execution, timeout handling, and JSON result printing. The `test` command already validates generated tester presence, reads tester metadata, applies `--list-tests` and `--run`, parses `--tol`, and aggregates pass/fail results through `aggregate_results`.

`profile` should use the same generated tester and discovered `TestCase` objects, but repeat execution enough times to calculate runtime statistics and optionally memory statistics. The command must preserve existing `generate` and `test` behavior.

## Related Work

> **`async-test-execution-controls/add-async-test-selection-timeouts`**: Defines selection timeout behavior for test execution — informs reuse of `--timeout-ms` and `--total-timeout-ms` in each measured profile trial because timed-out tests must remain visible as failures and count in statistics.

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines traceable discovered test execution — informs keeping profile runs based on generated tester metadata and discovered `TestCase` ids because profile output must map pass/fail data to the same test identities.

> **`babel-code-goat-cli/support-rich-test-comparisons`**: Defines tolerance-aware comparisons — informs forwarding `--tol` through the same execution path because profile results should match `test` correctness semantics before aggregating measurements.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang>` with checkpoint-required flags.
- Reuse tester metadata validation, discovery, test filtering, timeouts, tolerance parsing, and status exit code behavior from `test`.
- Measure each profile trial with `time.perf_counter_ns()` and report mean/std over non-warmup trials.
- Include failed and timed-out trials in aggregate statistics.
- Add optional memory statistics when `--memory` is provided.

**Non-Goals:**

- Do not regenerate testers from `profile`.
- Do not change existing `test` output.
- Do not provide per-test percentile/histogram output.
- Do not guarantee cross-platform memory measurement precision beyond the process-level metric available in the runtime environment.

## Decisions

### Share test setup logic

Extract common `test` setup into a helper that validates `lang`, parses `--tol` and timeout flags, checks the generated tester file, reads metadata, discovers tests, applies `--list-tests`, and applies `--run`.

Rationale: profile must match test selection and correctness semantics. Sharing setup prevents drift between `test` and `profile` _(see `babel-code-goat-cli/support-single-call-traceability`, `babel-code-goat-cli/support-rich-test-comparisons`)_.

Alternative considered: duplicate `command_test` validation in `command_profile`. That is simpler initially but risks inconsistent handling of missing testers, invalid tolerances, and unknown test ids.

### Measure whole selected run per trial

Run the selected cases through `aggregate_results` once per trial and measure elapsed wall-clock time around that call with `time.perf_counter_ns()`. Treat the result of each measured trial as the correctness result for that run; the final `passed` and `failed` lists should come from the last measured trial because all measured trials use the same inputs.

Rationale: the checkpoint asks for aggregate `runtime_ns` statistics, not per-test timing. Measuring the same aggregate execution path keeps native C++/Rust suite behavior compatible with existing total-timeout handling _(see `async-test-execution-controls/add-async-test-selection-timeouts`)_.

Alternative considered: instrument every individual test case. That would be more detailed but would require larger changes to language-specific execution and generated native suite handling.

### Exclude warmup trials from statistics

Validate `n >= 1`, `warmup >= 0`, and `warmup < n`. Execute warmup runs before measured runs and discard their timing and memory samples.

Rationale: warmup exists to reduce first-run noise and must not affect reported mean/std.

Alternative considered: interpret `-n` as measured trials plus warmups. The checkpoint states `k < n`, which implies warmups are part of the total run count and measured samples are `n - k`.

### Use population standard deviation

Calculate `mean` as the arithmetic average and `std` as population standard deviation over the measured samples. For a single measured sample, report `std` as `0`.

Rationale: users need stable JSON numbers, and population standard deviation avoids undefined or exceptional output for the default `-n 1`.

Alternative considered: sample standard deviation. It is common for benchmark samples but becomes awkward for a single measured trial.

### Memory measurement

When `--memory` is provided, collect process memory before and after each selected run and record the positive delta when available, otherwise the observed post-run resident set value. Use standard-library facilities only, preferring `resource.getrusage` where available and falling back to `0` when no supported metric exists.

Rationale: this keeps the command dependency-free while satisfying optional `memory_kb` output. The metric is coarse but adequate for the required aggregate shape.

Alternative considered: depend on `psutil` for richer memory reporting. That adds an external dependency to a single-file CLI and is unnecessary for the checkpoint.

## Risks / Trade-offs

- [Risk] Memory units and semantics vary by platform -> Mitigation: normalize to kilobytes and document the implementation as best-effort process-level memory measurement.
- [Risk] Repeated execution can make slow tests much slower -> Mitigation: default `-n` to `1` and preserve `--timeout-ms`/`--total-timeout-ms`.
- [Risk] Warmup failures could be hidden if only measured results are reported -> Mitigation: if any warmup run returns `error`, stop and return that error; ordinary pass/fail warmup outcomes do not affect measured statistics.
- [Risk] Total timeout could be interpreted across all trials instead of per trial -> Mitigation: apply `--total-timeout-ms` to each individual `aggregate_results` call, matching existing `test` semantics for one command run.

## Migration Plan

No data migration is required. Add the parser branch, helper functions, and tests in one change. Existing `generate` and `test` invocations remain valid.

## Open Questions

- Should future profile output include per-test timing arrays, or is the aggregate mean/std sufficient for the current CLI contract?
