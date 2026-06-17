## Why

Async entrypoints can finish after the current harness decides the result, and long-running tests can hang the `test` command without a contract for partial failure reporting. The CLI also needs direct test discovery and single-test execution controls so callers can inspect and target generated test IDs.

## Related Work

### Related Changes

- `add-cpp-rust-targets`: motivated by extending generated harness execution beyond interpreted-only targets; this change complements that work by requiring async completion and timeout behavior consistently across all supported target runtimes.
- `add-babel-code-goat`: captured the cross-language harness and runner contract; this change extends that contract with async invocation, selection flags, and timeout reporting for `test`.
- `add-loop-as-test-support`: introduced coverage expectations for parameterized loop tests; this change builds on that rule by specifying how timed-out and not-executed tests are represented.

### Related Specs

- `babel-code-goat-cli/support-mutation-style-test-discovery`: defines recursive discovery and allowed constructs; this change reuses the existing discovered test ID model for listing and selected execution.
- `babel-code-goat-cli/support-single-call-traceability`: defines single-call traceability for tests; this change keeps selection and timeout behavior scoped to already-discovered tests rather than changing discovery semantics.
- `babel-code-goat-cli/add-loop-as-test-support`: defines loop-based test reporting and coverage outcomes; this change adapts its "every discovered test is reported" requirement for timeout and non-execution cases.

## What Changes

- Add `test --list-tests` to perform discovery only and return discovered IDs in `passed` with `failed=[]` when discovery succeeds.
- Add `test --run <test_id>` so only the selected discovered test ID appears in `passed` or `failed`.
- Add `test --timeout-ms <int>` as a per-test execution timeout and `test --total-timeout-ms <int>` as an overall command timeout.
- Require every target-language harness to await async or awaitable entrypoint results until completion or timeout.
- Require tests that time out or are not executed because a timeout budget is exhausted to appear in `failed` under the existing coverage rule.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: extend `test` command behavior with async completion, test listing, selected execution, and timeout reporting.

## Impact

- Affects CLI parsing and validation for `test` flags.
- Affects generated testers and/or runtime adapters for Python, JavaScript, and TypeScript async invocation handling.
- Affects test execution orchestration and JSON result construction.
- Requires focused coverage for async pass/fail behavior, discovery listing, selected runs, per-test timeouts, total timeouts, and timeout-driven coverage failures.
