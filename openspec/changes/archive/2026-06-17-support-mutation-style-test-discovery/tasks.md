## 1. Recursive Discovery and IDs

- [x] 1.1 Update `babel_code_goat.py` `discover_tests` to recursively collect `.py` files under `<tests_dir>`, sort them by forward-slash relative path, parse each file independently, reject test-like non-`.py` files, and raise `DiscoveryError` when no tests are discovered. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.2 Update `babel_code_goat.py` `PendingTest`, `TestCase`, `TestDiscoverer`, `assign_test_ids`, and `test_id_base` to carry the relative source path and format IDs as `<relative/path.py>:<line>` while preserving loop iteration and duplicate `#k` suffix behavior. [extends babel-code-goat-cli/add-loop-as-test-support]
- [x] 1.3 Add `tests/test_babel_code_goat.py` coverage for nested Python discovery, root `tests.py` compatibility, deterministic multi-file ordering, non-Python test-like file discovery errors, and no-tests discovery errors.

## 2. Mutation-Style Test Groups

- [x] 2.1 Update `babel_code_goat.py` `TestDiscoverer.visit_body`, `visit_assign`, and related parsing helpers to recognize entrypoint calls used as statements or assignments and consume the immediately following contiguous assertion group.
- [x] 2.2 Add validation in `babel_code_goat.py` that every mutation-style group has at least one following assertion, no intervening entrypoint call, and each assertion references a variable passed to the mutation call or assigned from it. [extends babel-code-goat-cli/support-single-call-traceability]
- [x] 2.3 Add a mutation test representation in `babel_code_goat.py` `PendingTest`, `TestCase`, `case_to_json`, and the language execution helpers so one entrypoint invocation validates all associated post-mutation assertions as one test result.
- [x] 2.4 Add `tests/test_babel_code_goat.py` coverage for valid in-place mutation statements, assignment mutation groups, multiple related assertions, unrelated assertions, missing immediate assertions, and interrupted groups with a second entrypoint call.

## 3. Verification

- [x] 3.1 Run the Python unit test suite and fix regressions in existing direct assertion, loop, output expectation, and exception expectation behavior.
- [x] 3.2 Run JavaScript and TypeScript smoke tests when Node is available to confirm serialized mutation cases and relative-path IDs execute consistently.
- [x] 3.3 Run `openspec status --change "support-mutation-style-test-discovery"` and confirm the change is ready to apply.
