## Why

Callers currently can only learn whether a translated solution passes or fails. Automation and performance-sensitive grading workflows also need repeatable runtime and memory measurements using the same generated tester files, selection controls, and timeout safeguards as `test`.

## What Changes

- Add a `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `generate` to run first by erroring when the expected language-specific tester file is missing.
- Add profiling flags `-n <trials>`, `--warmup <k>`, and `--memory`.
- Support `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` for `profile` with behavior matching `test` where applicable.
- Print single-line JSON with pass/fail status, passed and failed test IDs, runtime mean/std in nanoseconds, and optional memory mean/std in kilobytes.
- Exclude warmup executions from reported statistics while including timeout executions in the aggregate measurements and failed-test accounting.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the CLI contract with a `profile` command, profiling flags, JSON statistics output, tester preconditions, and timeout accounting semantics.

## Impact

- `babel_code_goat.py` CLI parsing, command dispatch, tester-file validation, test execution orchestration, and result aggregation.
- Runtime measurement and optional memory measurement for Python, JavaScript, TypeScript, C++, and Rust target execution.
- Existing tests plus new coverage for `profile` command behavior, flag validation, JSON output shape, warmup exclusion, memory output, test-flag parity, and timeout statistics.
