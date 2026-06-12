## Why

Async solutions and test helpers are increasingly common, but the current test contract does not say that generated harnesses must await async entrypoints or bound execution time. The `test` command also needs first-class discovery, single-test selection, and timeout controls so callers can inspect and run test suites predictably across every supported target language.

## What Changes

- Add async/await-aware execution semantics for Python, JavaScript, TypeScript, C++, and Rust targets so each entrypoint invocation runs to completion before the result is compared.
- Add `test --list-tests` to perform discovery only and report all discovered test IDs in `passed`.
- Add `test --run <test_id>` to execute only one selected discovered test while preserving the standard JSON result contract.
- Add per-test and total test-run timeout controls with `test --timeout-ms <int>` and `test --total-timeout-ms <int>`.
- Require timed-out or otherwise not-executed discovered tests to be reported in `failed` after successful discovery.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the CLI test contract with async execution, test discovery listing, selected test execution, and timeout behavior.

## Impact

- Affected code: `babel_code_goat.py` CLI argument parsing, test discovery/execution orchestration, generated tester code, and per-language runtime adapters.
- Affected targets: Python, JavaScript, TypeScript, C++, and Rust test harness execution.
- Affected tests: CLI contract tests in `tests/test_babel_code_goat.py`, including new coverage for async entrypoints, `--list-tests`, `--run`, timeout failures, and invalid flag values.
