## 1. CLI Options and Discovery Flow

- [x] 1.1 Add `test` parser flags for `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 1.2 Add shared validation for optional timeout integers so invalid or less-than-one values produce the standard error JSON and exit code 2.
- [x] 1.3 Add a `test` execution options structure or equivalent shared parameters for selected ID, per-test timeout, total timeout, and list-only mode.
- [x] 1.4 Implement discovery-first `--list-tests` output with `status="pass"`, every discovered ID in `passed`, `failed=[]`, and no solution execution.
- [x] 1.5 Implement `--run <test_id>` filtering after discovery and return the standard error JSON for an unknown ID.

## 2. Timeout-Aware Result Aggregation

- [x] 2.1 Update `aggregate_results`, `execute_case`, and all target case runner call sites to accept execution options.
- [x] 2.2 Thread the configured per-test timeout into Python, Node, C++, and Rust subprocess execution while preserving existing defaults when no flag is provided.
- [x] 2.3 Add monotonic total-deadline accounting around selected case execution.
- [x] 2.4 Mark timed-out cases failed and mark any selected tests skipped because of total timeout failed.
- [x] 2.5 Preserve the existing JSON keys and exit-code mapping for pass, fail, and error results.

## 3. Async Entrypoint Execution

- [x] 3.1 Update the Python case runner to detect awaitable entrypoint results and run them to completion before assertion evaluation.
- [x] 3.2 Keep JavaScript and TypeScript promise awaiting intact while applying configurable subprocess timeouts.
- [x] 3.3 Add C++ harness helpers that resolve `std::future<T>` and `std::shared_future<T>` with `.get()` before comparisons, output checks, and exception matching.
- [x] 3.4 Add Rust harness helpers that accept plain values or `Future` results and drive self-contained futures to completion before comparisons, output checks, and panic matching.

## 4. Verification

- [x] 4.1 Add tests for `--list-tests`, including a case proving solution code is not executed.
- [x] 4.2 Add tests for `--run <test_id>` success and unknown-ID error behavior.
- [x] 4.3 Add tests for per-test timeout failure and total timeout failure accounting, including not-executed selected IDs.
- [x] 4.4 Add async entrypoint tests for Python, JavaScript, TypeScript, C++, and Rust, using existing toolchain skip patterns where needed.
- [x] 4.5 Run the relevant unit test suite and confirm OpenSpec reports the change as apply-ready.
