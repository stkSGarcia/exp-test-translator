## 1. Discovery Coverage

- [x] 1.1 Add `tests/test_babel_code_goat.py` coverage for valid mutation-style statement calls, including the checkpoint `sort_colors(a)` pattern. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 1.2 Add `tests/test_babel_code_goat.py` coverage for valid mutation-style assignment calls whose asserts reference the assigned result. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 1.3 Add `tests/test_babel_code_goat.py` coverage for invalid mutation groups: no following assert, intervening entrypoint calls, and asserts that reference no passed or assigned variable. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 1.4 Add `tests/test_babel_code_goat.py` coverage for recursive `.py` discovery, absence of root `tests.py`, test-like non-Python file errors, and empty-discovery errors. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 1.5 Add `tests/test_babel_code_goat.py` coverage for path-qualified IDs, nested forward-slash paths, and same-line `#k` suffixes. [extends babel-code-goat-cli/support-loop-construct-tests]

## 2. Recursive File Discovery

- [x] 2.1 Update `babel_code_goat.py::discover_tests` to enumerate candidate files recursively, normalize relative paths with forward slashes, and parse each `.py` source with its relative path.
- [x] 2.2 Add test-like filename validation in `babel_code_goat.py` for non-`.py` files matching `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`.
- [x] 2.3 Update `babel_code_goat.py::discover_tests` to fail when recursive discovery produces no test cases.
- [x] 2.4 Ensure `babel_code_goat.py` discovery order is deterministic across platforms by sorting normalized relative paths before parsing.

## 3. Path-Based IDs

- [x] 3.1 Update `babel_code_goat.py::assign_ids` or its caller so non-loop IDs use `<relative-path>:<line>` instead of the hard-coded `tests.py:<line>`.
- [x] 3.2 Preserve existing same-line `#k` behavior and loop iteration suffix behavior with the new relative-path prefix in `babel_code_goat.py`.
- [x] 3.3 Confirm generated tester payload comparisons in `babel_code_goat.py::command_test` continue to pass with path-qualified IDs.

## 4. Mutation-Style Test Support

- [x] 4.1 Refactor `babel_code_goat.py::discover_in_body` to support index-based statement traversal for entrypoint call groups.
- [x] 4.2 Add helpers in `babel_code_goat.py` to detect entrypoint expression statements and simple assignment calls, reusing `parse_entrypoint_call` for argument values.
- [x] 4.3 Add helpers in `babel_code_goat.py` to collect directly passed variables, directly assigned variables, and variable references inside following asserts.
- [x] 4.4 Implement mutation-style assert grouping in `babel_code_goat.py`, failing discovery for groups that violate the immediate-assert or variable-reference constraints.
- [x] 4.5 Extend runner payload generation in `babel_code_goat.py` only if mutation-style cases require a distinct serialized representation.

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/test_babel_code_goat.py` and fix failures.
- [x] 5.2 Run targeted CLI generate/test checks for Python, JavaScript, and TypeScript when mutation-style runner behavior changes.
- [x] 5.3 Verify `openspec status --change "add-mutation-style-test-discovery"` reports the change artifacts as complete.
