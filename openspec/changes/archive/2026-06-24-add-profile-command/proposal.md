## Why

Users can currently check correctness with `test`, but they cannot measure solution performance through the same generated tester workflow. A `profile` command provides repeatable timing and optional memory measurements while preserving the command-line controls already available for test selection, tolerance, and timeouts.

## What Changes

- Add a root-level `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require the generated tester file for the selected language to exist before profiling, matching the `test` command's generate-first contract.
- Add profiling controls for trial count (`-n <trials>`), warmup runs (`--warmup <k>` where `k < n`), and optional memory measurement (`--memory`).
- Support `test` command parity flags on `profile`: `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>` where tolerance applies.
- Print one JSON result including `status`, `passed`, `failed`, and aggregate `runtime_ns` mean/std values, plus `memory_kb` mean/std values when `--memory` is requested.
- Include timed-out test results in `failed` and include their timing and memory observations in aggregate statistics; exclude warmup runs from statistics.

## Capabilities

### New Capabilities

### Modified Capabilities

- `babel-code-goat-cli`: Extend the CLI contract with a `profile` command, profiling flags, generated-tester validation, JSON output statistics, and timeout aggregation behavior.

## Impact

- Affects the root CLI argument parser and command dispatch.
- Affects generated tester execution paths for all supported target languages.
- Requires runtime aggregation logic for repeated runs, warmups, timeout results, and optional memory metrics.
- Requires CLI and integration tests covering profile argument validation, generated-tester preconditions, output shape, flag parity, warmup exclusion, and timeout behavior.
