## Why

The CLI can currently generate testers and run tests, but it cannot measure solution performance with repeatable trial counts, warmup exclusion, or optional memory statistics. Adding `profile` gives users a first-class way to benchmark generated test harnesses while preserving the selection, tolerance, and timeout behavior already defined for `test`.

## Related Work

### Related Changes
- `add-cpp-rust-targets`: motivated compiled-target execution parity across generated harnesses. This change complements it by defining profiling behavior in terms of the same language-specific tester contract.
- `support-single-call-traceability`: motivated unambiguous per-test invocation mapping. This change relies on that traceability so profiling results can aggregate discovered test executions without changing test identity rules.
- `add-async-test-selection-timeouts`: motivated async completion, test selection, and timeout reporting for `test`. This change extends those timeout and selection semantics to `profile`, including timeout failures in aggregate statistics.

### Related Specs
- `babel-code-goat-cli/add-babel-code-goat`: defines the base `generate` and `test` CLI commands, language validation, tester-file requirements, and JSON result shape. This change reuses that command and tester-file model for `profile`.
- `babel-code-goat-cli/add-async-test-selection-timeouts`: defines `test` selection flags, tolerance behavior, and timeout failure reporting. This change adapts those controls for profiling and adds aggregate runtime and optional memory measurements.
- `babel-code-goat-cli/support-single-call-traceability`: defines stable discovery and per-test traceability expectations. This change builds on those test IDs for `passed` and `failed` profiling output.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `profile` to fail when the expected generated tester file for the selected language is missing.
- Add profiling flags `-n <trials>`, `--warmup <k>`, and `--memory`.
- Support the same `test` selection, timeout, and tolerance flags where applicable: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol <float>`.
- Print JSON with `status`, `passed`, `failed`, and `runtime_ns` mean/std statistics; include `memory_kb` mean/std when `--memory` is requested.
- Exclude warmup runs from statistics while including timed-out run measurements in the aggregate statistics and failed results.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `babel-code-goat-cli`: extend the CLI contract with a `profile` command, profiling flags, aggregate JSON output, and timeout-statistics behavior.

## Impact

- CLI argument parsing and command dispatch need a new `profile` command.
- Test runner execution code should be shared or adapted so `profile` honors existing discovery, selection, tolerance, timeout, language validation, and tester-file behavior.
- JSON output contracts expand for `profile` only; existing `test` output remains unchanged.
- Tests should cover trial counting, warmup validation, memory output, missing tester errors, flag parity, and timeout aggregation.
