## 1. CLI Options and Discovery Flow

- [x] 1.1 Add `test` parser flags for `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Add shared validation for positive integer timeout values and mutually exclusive `--list-tests` plus `--run`, returning the standard error JSON on invalid input.
- [x] 1.3 Implement `--list-tests` after tester metadata validation and discovery so it prints `status="pass"`, all discovered IDs in `passed`, `failed=[]`, and does not load or invoke the solution.
- [x] 1.4 Implement `--run <test_id>` filtering after discovery, including the standard error JSON for unknown IDs.

## 2. Timeout-Aware Result Aggregation

- [x] 2.1 Add an execution-options data structure that carries per-test timeout and total timeout values through `command_test()`, `aggregate_results()`, and `execute_case()`.
- [x] 2.2 Update `aggregate_results()` to track a monotonic total deadline and mark all not-yet-executed in-scope tests as failed when the total timeout is exhausted.
- [x] 2.3 Update `execute_case()` and each target runner signature to use the effective per-case timeout, combining `--timeout-ms` with remaining total time when both are present.
- [x] 2.4 Preserve existing loop-test behavior while ensuring selected loop tests and total-timeout skipped loop tests still obey the coverage rule.

## 3. Async Entrypoint Execution

- [x] 3.1 Update the Python case harness to await coroutine or awaitable entrypoint results before evaluating assertions, mutation assertions, output expectations, and exception expectations.
- [x] 3.2 Audit the JavaScript and TypeScript Node harness paths so direct calls, mutation calls, and exception expectations consistently await promise results.
- [x] 3.3 Extend C++ driver generation to support completed values from recognized `std::future<T>`-style entrypoint returns within the effective timeout.
- [x] 3.4 Extend Rust driver generation with a std-only helper for supported future results and rely on the outer subprocess timeout for non-completing futures.

## 4. Regression Tests

- [x] 4.1 Add CLI tests for `--list-tests`, including successful discovery output and proof that invalid or missing solution code is not executed.
- [x] 4.2 Add CLI tests for `--run <test_id>`, including pass, fail, unknown ID, and interaction with loop or recursive-discovery IDs.
- [x] 4.3 Add timeout tests proving per-test timeouts fail only the timed-out test and total timeouts mark remaining in-scope tests failed.
- [x] 4.4 Add Python async tests for successful async return values, async failures, output capture, and exception expectations.
- [x] 4.5 Add JavaScript and TypeScript promise-based tests for successful completion, rejection or thrown async errors, and timeout behavior when Node is available.
- [x] 4.6 Add C++ and Rust async/future smoke tests where the available toolchains can compile the supported future shapes.

## 5. Verification

- [x] 5.1 Run the full Python test suite and any focused CLI flows needed for Python, JavaScript, TypeScript, C++, and Rust based on locally available toolchains.
- [x] 5.2 Run `openspec status --change "add-async-test-selection-timeouts"` and confirm the change is apply-ready.
