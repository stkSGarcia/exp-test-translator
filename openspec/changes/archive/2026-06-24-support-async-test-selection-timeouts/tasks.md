## 1. CLI Contract Coverage

- [x] 1.1 Add CLI tests for `test --list-tests` reporting `status="pass"`, all discovered IDs in `passed`, `failed=[]`, and no solution entrypoint invocation.
- [x] 1.2 Add CLI tests for `test --run <test_id>` executing and reporting only the selected discovered ID.
- [x] 1.3 Add CLI error tests for unknown `--run` IDs, `--list-tests` combined with `--run`, and non-positive timeout values.
- [x] 1.4 Add timeout coverage for per-test timeout failure, total timeout failure, and selected-test timeout reporting.
- [x] 1.5 Add async entrypoint coverage for Python, JavaScript, TypeScript, C++, and Rust targets where the runtime toolchain is available.

## 2. CLI Parsing And Result Selection

- [x] 2.1 Extend the `test` subcommand parser with `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- [x] 2.2 Validate incompatible or invalid flags before execution and preserve the standard error JSON plus exit code `2`.
- [x] 2.3 Implement list-only result construction after discovery and stale generated-tester validation without invoking solution code.
- [x] 2.4 Implement selected-test filtering so generated execution receives only the selected discovered test and result reporting includes only that ID.
- [x] 2.5 Preserve deterministic discovered-ID ordering in list, selected, normal, and timeout result paths.

## 3. Timeout Execution

- [x] 3.1 Add per-test timeout propagation to the generated tester payload or runner invocation boundary.
- [x] 3.2 Add total-run timeout tracking around the execution phase after discovery and generated-tester validation.
- [x] 3.3 Convert per-test timeout expiration into a failing result for the affected test ID.
- [x] 3.4 Convert total timeout expiration into failing results for timed-out and not-yet-executed discovered IDs.
- [x] 3.5 Ensure subprocesses or compiled-target executions are cleaned up when timeout deadlines expire.

## 4. Async Target Helpers

- [x] 4.1 Update Python tester execution to detect awaitable entrypoint results and run them to completion before assertion evaluation.
- [x] 4.2 Update JavaScript and TypeScript tester helpers to await promise-like entrypoint results across all supported test kinds.
- [x] 4.3 Update C++ tester generation to unwrap supported future-like entrypoint results before assertion evaluation.
- [x] 4.4 Update Rust tester generation to drive supported future entrypoint results to completion before assertion evaluation.
- [x] 4.5 Ensure async errors map through existing assertion, exception-style, stdout/stderr, and coverage semantics.

## 5. Validation

- [x] 5.1 Run focused CLI tests for listing, selection, timeout, and async behavior.
- [x] 5.2 Run generated tester parity tests for Python, JavaScript, TypeScript, C++, and Rust, skipping unavailable compiled toolchains consistently with existing tests.
- [x] 5.3 Run the full pytest suite.
- [x] 5.4 Run `openspec status --change support-async-test-selection-timeouts` and confirm the change is apply-ready.
