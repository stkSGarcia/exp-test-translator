## 1. Recursive Discovery

- [x] 1.1 Update `babel_code_goat.py` discovery helpers to recursively collect `.py` files under `<tests_dir>` in deterministic relative-path order. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 1.2 Add recursive validation in `babel_code_goat.py` that raises `DiscoveryError` for non-`.py` files matching `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}`.
- [x] 1.3 Update `discover_tests()` in `babel_code_goat.py` to parse each discovered Python file and raise `DiscoveryError` when no tests are discovered recursively.

## 2. Path-Based IDs

- [x] 2.1 Extend `PendingTest` and `TestCase` in `babel_code_goat.py` to carry the test file path relative to `<tests_dir>`. [extends `babel-code-goat-cli/add-loop-as-test-support`]
- [x] 2.2 Update `assign_test_ids()` and `test_id_base()` in `babel_code_goat.py` to emit `<relative-path>:<line>` with forward slashes while preserving loop iteration suffixes and duplicate `#<k>` suffixes.
- [x] 2.3 Update existing expectations in `tests/test_babel_code_goat.py` only where recursive path handling changes ID coverage.

## 3. Mutation-Style Discovery

- [x] 3.1 Add mutation-sequence detection to `TestDiscoverer.visit_body()` in `babel_code_goat.py` for standalone entrypoint calls and direct single-name assignments from the entrypoint. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 3.2 Implement validation in `babel_code_goat.py` that mutation asserts immediately follow the call, contain no entrypoint call, and each reference an allowed mutated argument variable or assigned result variable.
- [x] 3.3 Add language-neutral postcondition data to `PendingTest`, `TestCase`, JSON encoding, and JSON decoding in `babel_code_goat.py` so mutation tests can check mutated arguments or assigned results.
- [x] 3.4 Extend the Python and Node case runners in `babel_code_goat.py` to evaluate mutation postconditions after exactly one entrypoint call. [extends `babel-code-goat-cli/support-rich-test-comparisons`]

## 4. Verification

- [x] 4.1 Add unit tests in `tests/test_babel_code_goat.py` for nested Python discovery, root `tests.py` absence, stable relative-path IDs, and same-line `#<k>` suffixes.
- [x] 4.2 Add unit tests in `tests/test_babel_code_goat.py` for non-Python test-like file errors and no-tests-discovered errors.
- [x] 4.3 Add unit and CLI tests in `tests/test_babel_code_goat.py` for valid standalone mutation calls and valid assignment mutation calls.
- [x] 4.4 Add rejection tests in `tests/test_babel_code_goat.py` for mutation asserts with nested entrypoint calls, missing dependent variable references, and intervening statements.
- [x] 4.5 Run the full test suite and ensure existing CLI generation and execution behavior still passes for Python, JavaScript, and TypeScript.
