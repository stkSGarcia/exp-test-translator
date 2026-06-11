## Why

The `test` command needs finer control for automation and grading workflows: callers must be able to discover test IDs, run one selected test, and bound execution time. Target harnesses also need to handle async/await-style solutions consistently so a test result reflects completed work rather than an unresolved promise/future.

## What Changes

- Ensure generated test execution for every supported target language runs async/await-style entrypoint invocations to completion.
- Add `test --list-tests` to return discovered test IDs without executing solution code.
- Add `test --run <test_id>` to execute and report only the selected discovered test.
- Add `test --timeout-ms <int>` to bound individual test execution time.
- Add `test --total-timeout-ms <int>` to bound the full `test` command execution.
- Require timed-out and not-executed tests caused by timeout accounting to be reported in `failed`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the CLI test contract with async completion semantics, test listing, selected test execution, and per-test/total timeout behavior.

## Impact

- `babel_code_goat.py` command-line parsing, test orchestration, and target-language execution helpers.
- Generated and runtime harness logic for `python`, `javascript`, `typescript`, `cpp`, and `rust`.
- Existing CLI tests plus new coverage for async entrypoints, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and timeout failure accounting.
