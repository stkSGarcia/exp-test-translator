## 1. CLI Selection and Listing

- [x] 1.1 Add `test` parser support for `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Refactor `command_test` after tester payload revalidation to derive the discovered ID list and selected execution set.
- [x] 1.3 Implement `--list-tests` so it returns a pass result with every discovered ID in `passed`, `failed=[]`, and no solution entrypoint execution.
- [x] 1.4 Implement `--run <test_id>` validation and ensure selected runs report only the selected ID in `passed` or `failed`.
- [x] 1.5 Preserve existing error JSON and exit code behavior for unsupported languages, missing testers, discovery failures, payload mismatches, and unknown selected IDs.

## 2. Runtime Control Contract

- [x] 2.1 Define and document the internal environment variables or tester arguments used for selected IDs, per-test timeout, total timeout/deadline, and tolerance.
- [x] 2.2 Update Python tester generation and execution helpers to filter selected IDs without changing embedded payloads or tester files.
- [x] 2.3 Update JavaScript and TypeScript tester generation to filter selected IDs while preserving existing Promise-aware execution.
- [x] 2.4 Update C++ tester generation and compile/run flow to filter selected IDs without rebuilding or modifying tester files unnecessarily.
- [x] 2.5 Update Rust tester generation and compile/run flow to filter selected IDs without rebuilding or modifying tester files unnecessarily.

## 3. Async Entrypoint Completion

- [x] 3.1 Add Python awaitable detection and completion for direct-call, mutation-style, and raise expectation tests.
- [x] 3.2 Add JavaScript and TypeScript regression-safe Promise completion for direct-call, mutation-style, and raise expectation tests.
- [x] 3.3 Add C++ standard future-like result completion before comparison or exception expectation handling.
- [x] 3.4 Add Rust future completion with standard-library-only polling before comparison or panic expectation handling.
- [x] 3.5 Ensure async completion failures are reported as failing test outcomes unless an existing harness error prevents result construction.

## 4. Timeout Handling

- [x] 4.1 Implement per-test timeout handling so timed-out selected tests appear in `failed`.
- [x] 4.2 Implement total timeout handling so selected tests not executed before the deadline appear in `failed`.
- [x] 4.3 Ensure timeout runs still print exactly one JSON object with only `status`, `passed`, and `failed`.
- [x] 4.4 Preserve mutation group semantics under timeout handling while reporting only selected IDs for `--run`.
- [x] 4.5 Ensure killed or stalled tester subprocesses are converted into fail results for selected IDs after discovery succeeds.

## 5. Regression Coverage

- [x] 5.1 Add CLI tests for `--list-tests`, successful `--run`, failing `--run`, unknown `--run`, and discovery failure with `--list-tests`.
- [x] 5.2 Add timeout tests covering per-test timeout, total timeout, not-executed selected IDs, and `--run` timeout reporting.
- [x] 5.3 Add Python async entrypoint tests for resolving, raising, and timing out awaitables.
- [x] 5.4 Add JavaScript and TypeScript async entrypoint tests for resolving, rejecting, and never-settling Promises.
- [x] 5.5 Add C++ and Rust async/future coverage where supported by the generated tester model, with compiler-gated skips where tooling is unavailable.
- [x] 5.6 Run the full pytest suite and `openspec status --change add-async-test-selection-timeouts`.
