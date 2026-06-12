## 1. CLI Flags and Validation

- [x] 1.1 Add `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms` arguments to the `test` parser.
- [x] 1.2 Add timeout parsing that accepts only positive integer millisecond values and returns the standard error JSON for invalid values.
- [x] 1.3 Reject conflicting `--list-tests` and `--run` usage with the standard error JSON.

## 2. Listing and Selection

- [x] 2.1 Update `command_test` to perform language, tester metadata, tolerance, timeout, and discovery validation before list or run handling.
- [x] 2.2 Implement `--list-tests` to return `status="pass"`, all discovered IDs in `passed`, `failed=[]`, and exit code 0 without executing the solution.
- [x] 2.3 Implement `--run <test_id>` filtering after discovery so only the selected case can appear in `passed` or `failed`.
- [x] 2.4 Return the standard error JSON when `--run` references an unknown discovered test ID.

## 3. Timeout Execution

- [x] 3.1 Thread a per-case timeout value through `aggregate_results`, `execute_case`, and each language runner.
- [x] 3.2 Replace hard-coded runner execution timeouts with the effective per-case timeout while preserving sensible defaults when `--timeout-ms` is omitted.
- [x] 3.3 Add total-run deadline handling in `aggregate_results` that marks not-yet-executed selected cases as failed when `--total-timeout-ms` elapses.
- [x] 3.4 Ensure timed-out cases return normal fail results after discovery succeeds instead of command error results.

## 4. Async Entrypoint Completion

- [x] 4.1 Update the Python case runner to await coroutine or awaitable entrypoint results before expression evaluation, mutation assertions, output checks, and exception checks.
- [x] 4.2 Update the JavaScript and TypeScript Node runner to await promise-returning entrypoints for normal, mutation, and exception cases.
- [x] 4.3 Update the C++ harness helpers to complete standard future-like entrypoint results before comparison and mutation assertion evaluation.
- [x] 4.4 Update the Rust harness helpers to complete returned futures with a std-only executor path before comparison and mutation assertion evaluation.

## 5. Test Coverage

- [x] 5.1 Add CLI tests for `--list-tests`, including discovery-only behavior that does not invoke failing or hanging solution code.
- [x] 5.2 Add CLI tests for `--run` passing, failing, unknown ID, and conflict-with-list behavior.
- [x] 5.3 Add CLI tests for valid per-test timeouts, total timeouts, and invalid timeout values.
- [x] 5.4 Add async entrypoint tests for Python, JavaScript, TypeScript, C++, and Rust, gating target-specific tests on tool availability where needed.
- [x] 5.5 Add mutation-style async regression coverage for at least one interpreted target and one compiled target where feasible.

## 6. Verification

- [x] 6.1 Run the focused unittest suite for `tests/test_babel_code_goat.py`.
- [x] 6.2 Run `openspec status --change "support-async-test-selection-timeouts"` and confirm all proposal artifacts are complete.
