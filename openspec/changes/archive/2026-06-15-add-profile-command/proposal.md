## Why

The CLI can generate and execute translated tests, but it cannot measure solution performance across repeated runs or report stable runtime and memory statistics. A dedicated `profile` command is needed so users can benchmark generated test harnesses with the same selection, timeout, and tolerance controls already used by `test`.

## Related Work

### Related Changes

- `add-loop-as-test-support`: Motivated by test discovery gaps in common parameterized patterns; this change complements it by profiling whatever tests discovery exposes, including loop-expanded cases.
- `support-mutation-directory-discovery`: Motivated by broader valid test sources and recursive/mutation-style execution; this change reuses the generated tester prerequisite and execution contract instead of introducing a new discovery path.
- `support-single-call-traceability`: Motivated by keeping each discovered test mapped to one entrypoint invocation; this change builds on that traceability so profile output can attribute pass/fail and timing data to the same selected tests.

### Related Specs

- `async-test-execution-controls/add-async-test-selection-timeouts`: Defines `test` timeout behavior; this change reuses those timeout semantics for profile runs and includes timed-out trials in aggregate statistics.
- `babel-code-goat-cli/support-single-call-traceability`: Defines test discovery and execution traceability; this change keeps profiling tied to the generated tester and existing pass/fail result shape.
- `babel-code-goat-cli/support-rich-test-comparisons`: Defines tolerance-aware comparison behavior; this change carries `--tol` parity into profiling where comparisons support it.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` CLI command.
- Require `generate` to run first by erroring when the expected tester file for the selected language is missing.
- Support `-n <trials>` with default `1`, `--warmup <k>` where `k < n`, and optional `--memory`.
- Support the same selection and timeout flags as `test`: `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- Support `--tol <float>` where the underlying generated tester supports tolerance-aware comparisons.
- Print JSON containing at least `status`, `passed`, `failed`, and `runtime_ns` with `mean` and `std`.
- When `--memory` is provided, include `memory_kb` with `mean` and `std`.
- Exclude warmup trials from reported statistics while still using them to warm the execution path.
- Include timeout measurements in aggregate runtime and memory statistics and list timed-out tests in `failed`.

## Capabilities

### New Capabilities

- `profile-command`: Profiling CLI behavior, trial and warmup controls, runtime and optional memory statistics, tester prerequisite validation, and flag parity with `test`.

### Modified Capabilities

- None.

## Impact

- `babel_code_goat.py`: Add parser wiring, profile command execution, repeated trial orchestration, warmup validation, statistics aggregation, and optional memory measurement.
- `tests/test_babel_code_goat.py`: Add CLI coverage for missing testers, flag parity, warmup exclusion, runtime statistics, memory output, and timeout aggregation.
- No breaking changes to existing `generate` or `test` command behavior.
