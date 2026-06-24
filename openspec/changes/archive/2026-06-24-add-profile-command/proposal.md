## Why

Users can validate correctness with `test`, but they cannot measure solution performance through the same generated-tester workflow. A first-class `profile` command gives repeatable runtime and optional memory statistics while preserving the existing generate-before-run contract.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `profile` to fail when the generated tester file for the selected language is missing.
- Add profiling controls for `-n <trials>`, `--warmup <k>`, and `--memory`.
- Support the same selection, timeout, and tolerance flags as `test`: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Emit profiling JSON containing correctness results plus aggregate runtime statistics, and memory statistics when requested.
- Include timed-out test results in the reported failed list and in aggregate profiling statistics.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Add the `profile` command, its flags, generated-tester prerequisite, JSON output, and timeout aggregation semantics.

## Impact

- Affects the root-level `babel_code_goat.py` CLI argument parser and command dispatch.
- Reuses generated tester execution behavior for all supported languages.
- Adds runtime and optional memory measurement around selected test executions.
- Adds CLI and end-to-end tests for profile validation, output shape, warmups, selection, timeouts, tolerance, and missing tester errors.
