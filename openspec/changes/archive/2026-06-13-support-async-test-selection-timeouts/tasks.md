## 1. CLI Selection Controls

- [x] 1.1 Add `test` parser flags for `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Validate timeout flag values as positive integer milliseconds and return the standard error JSON on invalid input.
- [x] 1.3 Implement `--list-tests` after tester metadata validation and discovery so it returns discovered IDs without executing solution code.
- [x] 1.4 Implement `--run <test_id>` filtering after discovery and return the standard error JSON when the requested ID is unknown.

## 2. Timeout Execution Flow

- [x] 2.1 Add timeout options to `aggregate_results`, `execute_case`, and target runner call signatures.
- [x] 2.2 Apply per-test timeout budgets to Python, Node, C++, and Rust subprocess execution.
- [x] 2.3 Track total timeout with monotonic elapsed time and pass the remaining budget to each selected case.
- [x] 2.4 Mark timed-out and not-executed selected test IDs as failed while preserving the existing JSON shape and exit-code mapping.

## 3. Async Entrypoint Support

- [x] 3.1 Update the Python case runner to await awaitable entrypoint results before assertion and output expectation evaluation.
- [x] 3.2 Confirm JavaScript and TypeScript Promise results are awaited under the new timeout plumbing.
- [x] 3.3 Update the C++ harness support to unwrap standard future-like entrypoint results before assertion evaluation.
- [x] 3.4 Update the Rust harness support to complete `Future` entrypoint results with a standard-library `block_on` helper before assertion evaluation.

## 4. Verification

- [x] 4.1 Add CLI tests for `--list-tests`, selected `--run`, unknown selected IDs, and invalid timeout values.
- [x] 4.2 Add timeout tests for per-test timeout failures and total-timeout not-executed failures.
- [x] 4.3 Add async execution tests for Python and JavaScript/TypeScript, plus conditional C++ and Rust async smoke coverage when compilers are available.
- [x] 4.4 Run the repository test suite and OpenSpec status/validation checks for `support-async-test-selection-timeouts`.
