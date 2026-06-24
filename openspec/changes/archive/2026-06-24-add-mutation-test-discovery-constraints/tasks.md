## 1. Coverage

- [x] 1.1 Add discovery tests for valid statement mutation calls followed by one and multiple adjacent asserts.
- [x] 1.2 Add discovery tests for valid assignment mutation calls whose following asserts reference the assigned result.
- [x] 1.3 Add negative discovery tests for mutation calls without immediate asserts, non-adjacent mutation asserts, unrelated asserts, and mutation asserts containing another entrypoint call.
- [x] 1.4 Add discovery tests for recursive `.py` files, deterministic file ordering, no-test discovery errors, and test-like non-Python file errors.
- [x] 1.5 Add ID tests for root files, nested files, same-line suffixes per file, and loop iteration suffixes in nested files.
- [x] 1.6 Add end-to-end CLI tests for mutation-style tests and recursive discovery across Python, JavaScript, and TypeScript targets where existing runner support permits.

## 2. Recursive Discovery And IDs

- [x] 2.1 Replace root-only `tests.py` loading in `discover_tests()` with recursive `.py` discovery under `<tests_dir>`.
- [x] 2.2 Reject non-`.py` files under `<tests_dir>` with names matching `test*`, `*_test`, `tests`, or `*_tests` before parsing candidate Python files.
- [x] 2.3 Exclude generated tester files from recursive discovery so existing `generate` and `test` flows do not rediscover harness output.
- [x] 2.4 Track each parsed file's forward-slash path relative to `<tests_dir>` through discovery and ID assignment.
- [x] 2.5 Update `assign_ids()` so IDs use `<relative-path>:<line>`, same-line suffixes are scoped per file and line, and loop iteration suffixes keep execution order per file and line.
- [x] 2.6 Raise `DiscoveryError` when recursive discovery completes without producing any tests.

## 3. Mutation Discovery Model

- [x] 3.1 Extend the test payload model with enough metadata to represent mutation-style setup, one entrypoint invocation, and post-call assertions.
- [x] 3.2 Detect mutation groups in `discover_in_body()` from standalone entrypoint call statements and direct assignments from entrypoint calls.
- [x] 3.3 Consume only immediately adjacent assert statements after a mutation call and fail discovery when a mutation call has no adjacent asserts.
- [x] 3.4 Validate that every mutation assert references at least one variable passed to the mutation call or directly assigned from the mutation call result.
- [x] 3.5 Reuse existing supported value, primitive expression, tolerance, and unsupported-helper validation for mutation assert expressions.
- [x] 3.6 Preserve existing assertion, raise expectation, loop, assignment, import, and unsupported-code behavior outside mutation groups.

## 4. Tester Execution

- [x] 4.1 Update Python tester execution to run mutation setup, invoke the entrypoint once, and evaluate each post-call mutation assert.
- [x] 4.2 Update generated JavaScript tester helpers to execute mutation-style payloads and compare mutated values consistently with existing structural comparison semantics.
- [x] 4.3 Update generated TypeScript tester helpers to execute mutation-style payloads and compare mutated values consistently with existing structural comparison semantics.
- [x] 4.4 Ensure mutation assertion failures produce normal `fail` result JSON while invalid mutation patterns discovered during generation or rediscovery produce `error` result JSON.

## 5. Verification

- [x] 5.1 Run `uv run pytest` and update existing expectations affected by recursive discovery or relative-path IDs.
- [x] 5.2 Run targeted CLI `generate` and `test` checks for root and nested tests, valid mutation-style tests, invalid mutation patterns, and test-like non-Python files.
- [x] 5.3 Run `openspec status --change add-mutation-test-discovery-constraints` and confirm the change is apply-ready.
