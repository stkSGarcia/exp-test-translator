## Why

Users need a repeatable way to measure translated solution performance with the same generated tester files and test-selection controls already used for correctness runs. Adding a dedicated `profile` command makes timing and optional memory measurements first-class CLI output instead of ad hoc wrapper behavior.

## What Changes

- Add `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` as a generated-tester-dependent CLI command.
- Require `profile` to fail with the standard error JSON when the expected tester file for the selected language is missing.
- Add profiling controls for `-n <trials>`, `--warmup <k>`, and `--memory`, with warmup runs excluded from reported statistics.
- Reuse `test` selection, timeout, and tolerance flags where applicable: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Print one JSON object that includes correctness status, `passed`, `failed`, and aggregate `runtime_ns` mean/std statistics, plus `memory_kb` mean/std when `--memory` is requested.
- Include timed-out test attempts in the reported aggregate statistics while preserving failed test reporting.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Extends the CLI contract with a `profile` command that shares generated tester validation, test selection, tolerance, and timeout behavior with `test` while adding runtime and optional memory statistics.

## Impact

- Updates CLI parsing and dispatch in `babel_code_goat.py`.
- Reuses or extends tester metadata discovery and target runner execution paths to support repeated measured runs.
- Adds result aggregation for mean/std runtime and optional memory statistics, including timeout attempts.
- Adds regression coverage for profile validation, trials and warmups, memory output, selection parity, tolerance, and timeout aggregation.
