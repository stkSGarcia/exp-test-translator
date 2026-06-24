## Why

Generated testers currently need clearer execution semantics for async entrypoints and long-running tests. Users also need a predictable way to inspect discovered test IDs, run one selected test, and bound individual or total test execution time without violating coverage accounting.

## What Changes

- Extend generated testers for Python, JavaScript, TypeScript, C++, and Rust so entrypoint invocations that use async/await semantics are run to completion before comparison or timeout handling.
- Add `test --list-tests` to report discovered test IDs without executing solution code.
- Add `test --run <test_id>` to execute only the selected discovered test and report only that ID in `passed` or `failed`.
- Add `test --timeout-ms <int>` to bound each executed test invocation.
- Add `test --total-timeout-ms <int>` to bound the overall selected test run.
- Preserve the existing one-line JSON output contract and coverage rule by listing timed-out or not-executed discovered tests in `failed`.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Add async completion, test discovery listing, single-test selection, and per-test/total timeout requirements to the CLI and generated tester behavior.

## Impact

- Affects `babel_code_goat.py` command parsing and `test` execution flow.
- Affects generated tester files for all supported target languages: Python, JavaScript, TypeScript, C++, and Rust.
- Affects test discovery/reporting behavior, especially result coverage for timeout and selection cases.
- Requires focused regression tests for async entrypoints, `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms` across supported languages where applicable.
