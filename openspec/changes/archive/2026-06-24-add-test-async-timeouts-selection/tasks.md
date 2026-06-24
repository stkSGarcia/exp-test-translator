## 1. CLI Contract and Selection

- [x] 1.1 Add parser support for `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Refactor `command_test` to derive the in-scope discovered tests before invoking any tester.
- [x] 1.3 Implement `--list-tests` so discovery success returns `status="pass"` with all discovered IDs in `passed` and no solution execution.
- [x] 1.4 Implement `--run <test_id>` so only the selected discovered test is executed and reported.
- [x] 1.5 Return the standard error result when `--run` references an unknown discovered test ID.

## 2. Async Execution

- [x] 2.1 Update Python execution to detect awaitable entrypoint results and run them to completion before assertion evaluation.
- [x] 2.2 Verify JavaScript and TypeScript generated testers continue to await promise-like entrypoint results under the new orchestration.
- [x] 2.3 Add C++ generated-tester support for supported future-like entrypoint results before comparison.
- [x] 2.4 Add Rust generated-tester support for supported future entrypoint results before comparison.

## 3. Timeout Orchestration

- [x] 3.1 Add parent-side timeout helpers that can bound tester subprocess execution and convert timeout outcomes into normal fail results for in-scope IDs.
- [x] 3.2 Implement `--timeout-ms` so each in-scope test has an independent execution limit.
- [x] 3.3 Implement `--total-timeout-ms` so remaining in-scope tests are marked failed after total time is exhausted.
- [x] 3.4 Preserve completed passing and failing results when a later timeout occurs.
- [x] 3.5 Ensure timed-out or not-executed in-scope tests are listed in `failed` exactly once.

## 4. Test Coverage

- [x] 4.1 Add pytest coverage for `--list-tests` success and discovery error behavior.
- [x] 4.2 Add pytest coverage for `--run` passing, failing, and unknown-ID behavior.
- [x] 4.3 Add pytest coverage for Python async entrypoint completion.
- [x] 4.4 Add pytest coverage for JavaScript and TypeScript async entrypoint completion.
- [x] 4.5 Add compiler-gated pytest coverage for C++ future-like and Rust future entrypoint completion where toolchains are available.
- [x] 4.6 Add pytest coverage for per-test timeout and total-timeout coverage accounting.

## 5. Verification

- [x] 5.1 Run the focused pytest cases for CLI selection, async execution, and timeouts.
- [x] 5.2 Run the full pytest suite.
- [x] 5.3 Run `openspec status --change "add-test-async-timeouts-selection"` and confirm the change is apply-ready.
