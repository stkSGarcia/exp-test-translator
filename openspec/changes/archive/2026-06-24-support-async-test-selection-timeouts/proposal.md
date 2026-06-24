## Why

The harness now supports several target languages and richer test semantics, but async entrypoints can still finish too early or hang indefinitely. Users also need a way to inspect discovered tests, run one test by ID, and bound execution time without weakening the existing result coverage rule.

## What Changes

- Run async/await entrypoint invocations to completion for every supported target language before evaluating assertions, stdout/stderr expectations, mutation follow-up assertions, and exception-style checks.
- Add `test --list-tests` to report discovered test IDs without executing solution code.
- Add `test --run <test_id>` to execute only the selected discovered test.
- Add `test --timeout-ms <int>` to cap individual test execution and mark timed-out tests as failed.
- Add `test --total-timeout-ms <int>` to cap the full `test` command run and mark not-yet-executed discovered tests as failed.
- Preserve the strict one-line JSON result contract, existing exit-code semantics, stale tester validation, and coverage accounting.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend `test` command behavior with async completion, test listing, single-test selection, and per-test/total timeout semantics.

## Impact

- Affects CLI argument parsing and result construction for `test`.
- Affects generated tester helpers and target runtime orchestration for Python, JavaScript, TypeScript, C++, and Rust.
- Requires coverage for async entrypoints, list-only discovery, selected test execution, timeout failures, and coverage behavior for skipped or not-executed discovered tests.
