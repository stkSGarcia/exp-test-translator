## Why

Callers can currently verify correctness with `test`, but they cannot ask the CLI for repeatable runtime or memory measurements using the same generated tester contract. A first-class `profile` command lets users benchmark translated solutions while preserving the same selection, tolerance, and timeout controls they already use for correctness checks.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `generate` to have already produced the language-specific tester file before profiling.
- Support repeated profile trials with `-n <trials>`, optional warmup runs with `--warmup <k>`, and optional memory aggregation with `--memory`.
- Reuse `test` command selection, timeout, and tolerance flags: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Print JSON containing correctness status, passed and failed test IDs, runtime mean/std statistics, and memory mean/std statistics when requested.
- Include timeout executions in aggregate runtime and memory statistics while reporting the affected tests in `failed`.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the existing CLI/tester contract with profiling behavior, repeat-trial statistics, optional memory measurement, and flag parity with `test`.

## Impact

- Affects `babel_code_goat.py` CLI parsing, tester validation, command dispatch, result aggregation, timeout handling, and per-language runner execution timing.
- Affects repository tests covering CLI output shape, exit codes, profiling statistics, warmup exclusion, memory reporting, and `test` flag parity.
