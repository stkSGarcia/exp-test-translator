## Why

Async solutions and async-style tests should run to completion in every supported target instead of being treated like ordinary synchronous return values. The `test` command also needs explicit discovery listing, single-test selection, and timeout controls so callers can inspect, isolate, and bound harness execution.

## What Changes

- Add async/await execution support for discovered entrypoint invocations across Python, JavaScript, TypeScript, C++, and Rust targets where the target exposes an awaitable, promise, future-like, or async-compatible result.
- Add `test --list-tests` to report discovered test IDs without executing the solution.
- Add `test --run <test_id>` to execute and report only the selected discovered test.
- Add `test --timeout-ms <int>` to bound individual test execution and `test --total-timeout-ms <int>` to bound the full `test` run.
- Preserve the existing JSON output shape and coverage rule: executed, timed out, skipped because of total timeout, or otherwise not-executed selected tests appear exactly once in `passed` or `failed`.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Extends the `test` command contract with async-aware execution, discovery listing, single-test selection, and per-test plus total timeout behavior.

## Impact

- Updates `babel_code_goat.py` CLI parsing, test discovery/reporting flow, and target runner invocation paths.
- Updates generated tester metadata or runtime payloads if needed to carry async and timeout execution options.
- Adds regression tests for async execution, `--list-tests`, `--run`, per-test timeouts, total timeouts, and coverage-rule reporting across supported target languages where toolchains are available.
