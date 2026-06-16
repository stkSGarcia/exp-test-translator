## Why

The CLI can run translated tests, but it cannot measure repeated execution performance or optional memory usage in the same workflow. Adding `profile` gives users a JSON-producing profiling path that preserves the generated tester prerequisite and selection/timeout semantics already defined for `test`.

## Related Work

### Related Changes

- `add-async-test-selection-timeouts`: added async completion, test selection, timeout handling, and tolerance behavior for `test`; this change extends those execution controls to profiling so selected tests and timed-out runs are measured consistently.
- `add-loop-as-test-support`: expanded test discovery to loop-based parameterization; this change relies on the same discovered test IDs so profiling reports aggregate results over the same execution surface.
- `support-mutation-directory-discovery`: clarified nested and mutation-oriented discovery behavior; this change complements it by measuring the executions produced by the active discovery contract without redefining discovery.

### Related Specs

- `babel-code-goat-cli/add-babel-code-goat`: defines the base `generate` and `test` commands, language validation, tester file generation, missing tester behavior, JSON output, and execution outcome shape. This change adapts those CLI and tester-file rules for `profile`.
- `babel-code-goat-cli/add-async-test-selection-timeouts`: defines selection, timeout, and tolerance behavior for `test`. This change reuses those flags and requires timeout samples to remain part of aggregate profile statistics.
- `babel-code-goat-cli/add-loop-as-test-support`: defines loop-derived test IDs and coverage expectations. This change builds on those IDs when profiling parameterized tests.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require the matching generated tester file to exist before profiling; `generate` remains responsible for creating tester files.
- Add profiling-specific flags `-n <trials>`, `--warmup <k>`, and `--memory`.
- Support the same selection, timeout, and tolerance flags as `test`: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Print JSON containing `status`, `passed`, `failed`, and `runtime_ns` mean/std fields, with optional `memory_kb` mean/std when `--memory` is provided.
- Exclude warmup runs from statistics while including timeout results in aggregate timing and memory calculations.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: add profiling command behavior, flags, output schema, warmup statistics handling, and timeout aggregation semantics.

## Impact

- CLI argument parsing and dispatch for a new `profile` command.
- Existing generated tester execution path so profiling shares discovery, language validation, selection, tolerance, timeout, and outcome behavior with `test`.
- JSON result construction for aggregate runtime and optional memory metrics.
- Test coverage for missing tester errors, flag validation, warmup exclusion, memory output, selection parity, and timeout aggregation.
