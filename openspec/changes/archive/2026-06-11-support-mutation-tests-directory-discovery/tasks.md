## 1. Recursive Discovery

- [x] 1.1 Add recursive `<tests_dir>` file scanning that sorts `.py` sources by forward-slash relative path.
- [x] 1.2 Reject non-`.py` files whose stems match `test*`, `*_test`, `tests`, or `*_tests`.
- [x] 1.3 Parse and discover tests from every `.py` source under `<tests_dir>`.
- [x] 1.4 Raise `DiscoveryError` when recursive scanning discovers no tests.

## 2. Source-Aware Test IDs

- [x] 2.1 Add relative source path fields to `PendingTest` and `TestCase`.
- [x] 2.2 Pass each file's relative path into `TestDiscoverer`.
- [x] 2.3 Update ID assignment to emit `<relative-path>:<line>` with existing loop iteration paths and `#k` same-line suffixes.
- [x] 2.4 Preserve existing root `tests.py:<line>` IDs for root `tests.py` cases.

## 3. Mutation-Style Discovery

- [x] 3.1 Update statement-body traversal to detect entrypoint call statements and single-variable assignments from entrypoint calls.
- [x] 3.2 Validate that mutation calls are immediately followed by one or more assert statements.
- [x] 3.3 Reject mutation asserts that contain an entrypoint call.
- [x] 3.4 Track direct argument variable names and assignment result names available to each mutation assert.
- [x] 3.5 Parse mutation assert expressions so each assert references at least one tracked mutation variable.
- [x] 3.6 Create one test case per valid mutation assert while preserving output expectation handling where applicable.

## 4. Runner Expression Support

- [x] 4.1 Extend expression metadata with post-call argument references and assignment result references.
- [x] 4.2 Update Python runner expression evaluation to read mutated argument values after the entrypoint call.
- [x] 4.3 Update JavaScript and TypeScript runner expression evaluation to read mutated argument values after the entrypoint call.
- [x] 4.4 Ensure mutation-style tests continue to use existing comparison, truthiness, stdout, stderr, and exception result aggregation behavior.

## 5. Verification

- [x] 5.1 Add discovery tests for nested `.py` files, multiple files, deterministic ordering, and no-tests discovery errors.
- [x] 5.2 Add discovery tests for non-`.py` test-like filename rejection.
- [x] 5.3 Add unit tests for path-based IDs, including nested files, same-line suffixes, and loop iteration IDs.
- [x] 5.4 Add Python execution tests for standalone mutation calls, assignment mutation calls, multiple immediate asserts, and invalid mutation patterns.
- [x] 5.5 Add JavaScript and TypeScript smoke tests for mutation-style argument updates when Node is available.
- [x] 5.6 Run the repository test suite and `openspec status --change "support-mutation-tests-directory-discovery"` to confirm the change is apply-ready.
