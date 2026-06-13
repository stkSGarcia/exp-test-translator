## Why

Translated tests can currently describe only synchronous entrypoint behavior, which makes async solutions unreliable or impossible to verify across target languages. The `test` command also needs first-class discovery, selection, and timeout controls so callers can inspect available tests, run one test deterministically, and report hung or skipped work as coverage failures.

## What Changes

- Run async/await-style entrypoint invocations to completion in every supported target language.
- Add `test` flags for `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Make `--list-tests` report discovered test IDs as passing results without executing solution code.
- Make `--run <test_id>` execute and report only the selected discovered test.
- Make per-test and total timeout outcomes appear in `failed` so timed-out or not-executed tests preserve coverage accounting.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the existing CLI/tester contract with async target execution semantics and `test` command discovery, selection, and timeout behavior.

## Impact

- Affects `babel_code_goat.py` CLI argument parsing, discovery execution flow, target harness generation, subprocess/runtime timeout handling, and JSON result aggregation.
- Affects tests in `tests/test_babel_code_goat.py` covering generated tester behavior and `test` command output/exit codes.
