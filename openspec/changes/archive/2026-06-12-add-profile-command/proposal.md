## Why

Users can run correctness checks today, but they cannot measure solution runtime or memory usage through the same generated tester contract. Adding a `profile` command makes benchmarking repeatable across supported languages while preserving the discovery, selection, tolerance, and timeout behavior already defined for `test`.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command that requires the generated tester file for the requested language to already exist.
- Add profiling controls for trial count with `-n <trials>`, warmup runs with `--warmup <k>`, and optional memory aggregation with `--memory`.
- Support the same `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and applicable `--tol <float>` flags as `test`.
- Emit JSON including correctness result fields and runtime statistics, plus memory statistics when requested.
- Exclude warmup runs from runtime and memory statistics while still using selected executable tests for profiling.
- Include timeout outcomes in the aggregated profiling statistics and list timed-out failed tests in `failed`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the CLI contract with a profiling command, profiling-specific flags, JSON statistics output, tester-file precondition behavior, and timeout aggregation semantics.

## Impact

- Affected code: `babel_code_goat.py` CLI argument parsing, tester-file validation, test discovery/selection flow, execution aggregation, runtime measurement, optional memory measurement, and JSON result formatting.
- Affected targets: Python, JavaScript, TypeScript, C++, and Rust where profiling reuses generated tester execution.
- Affected tests: CLI contract tests in `tests/test_babel_code_goat.py` covering profile invocation, invalid flags, warmup handling, list/run parity, tolerance parity, timeout statistics, and optional memory output.
