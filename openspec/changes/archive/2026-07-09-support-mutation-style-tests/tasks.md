## 1. Discovery File Traversal

- [x] 1.1 Add focused tests in `tests/test_babel_code_goat.py` for recursive `.py` discovery, nested relative-path IDs, no-tests discovery errors, and non-`.py` test-like file errors. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.2 Update `babel_code_goat.py` `discover_tests` to traverse `<tests_dir>` recursively, parse sorted `.py` files, reject non-`.py` files with test-like names, and error when no tests are discovered. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.3 Add source-path metadata to discovered `TestCase` values in `babel_code_goat.py` and pass it through generated tester payloads without changing existing root `tests.py` IDs. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.4 Update `babel_code_goat.py` `assign_ids` to key duplicate counts by relative path plus line and emit forward-slash IDs such as `nested/test_foo.py:10#0`. [extends babel-code-goat-cli/add-babel-code-goat]

## 2. Mutation-Style Test Discovery

- [x] 2.1 Add focused tests in `tests/test_babel_code_goat.py` for statement mutation calls followed by asserts, assignment mutation calls followed by asserts, and multiple assertions over the same mutated or assigned value. [extends babel-code-goat-cli/support-single-call-test-traceability]
- [x] 2.2 Add focused tests in `tests/test_babel_code_goat.py` for unsupported mutation patterns: no following assert, intervening unrelated statement, assertion over unrelated variables, and another entrypoint call before the assertion group completes. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 2.3 Implement mutation-call detection in `babel_code_goat.py` for `ast.Expr` entrypoint calls and assignment-valued entrypoint calls before unsupported-statement handling. [extends babel-code-goat-cli/support-single-call-test-traceability]
- [x] 2.4 Implement assertion grouping and validation in `babel_code_goat.py` so each immediately following assert references a variable passed to or directly assigned from the mutation call and contains no entrypoint call. [extends babel-code-goat-cli/support-single-call-test-traceability]
- [x] 2.5 Serialize mutation-style tests through the existing `TestCase` payload shape where possible, adding only minimal explicit metadata if existing assertion representations cannot express the expected mutated state. [extends mutation-style-test-discovery]

## 3. Runner Compatibility

- [x] 3.1 Verify generated Python, JavaScript, and TypeScript testers continue to execute existing assertion, raise, tolerance, and loop tests with the updated path-aware IDs. [extends babel-code-goat-cli/support-loop-construct-tests]
- [x] 3.2 Add end-to-end tests in `tests/test_babel_code_goat.py` proving generated testers execute mutation-style cases and report path-relative pass/fail IDs. [extends mutation-style-test-discovery]

## 4. Validation

- [x] 4.1 Run `uv run pytest tests/test_babel_code_goat.py` and fix any regressions.
- [x] 4.2 Run `openspec status --change support-mutation-style-tests` and confirm the change remains complete.
