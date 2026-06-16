## 1. Regression Coverage

- [x] 1.1 Add recursive discovery tests in `tests/test_babel_code_goat.py` for nested `.py` files and relative-path IDs [extends babel-code-goat-cli/add-loop-as-test-support]
- [x] 1.2 Add discovery error tests in `tests/test_babel_code_goat.py` for test-like non-Python files and directories with no discovered tests
- [x] 1.3 Add mutation-style discovery tests in `tests/test_babel_code_goat.py` for standalone entrypoint calls, assigned entrypoint calls, and multiple dependent assertions [extends babel-code-goat-cli/support-single-call-traceability]
- [x] 1.4 Add mutation-style rejection tests in `tests/test_babel_code_goat.py` for non-immediate assertions and assertions that do not reference mutated or assigned variables

## 2. Recursive Discovery and IDs

- [x] 2.1 Update `babel_code_goat.py` data classes `PendingTest` and `TestCase` to carry a normalized relative source path
- [x] 2.2 Update `babel_code_goat.py` `assign_test_ids` and `test_id_base` so IDs use `<relative-path>:<line>` while preserving loop iteration and duplicate suffix behavior [extends babel-code-goat-cli/add-loop-as-test-support]
- [x] 2.3 Replace `babel_code_goat.py` `discover_tests` single `tests.py` lookup with deterministic recursive `.py` discovery under `<tests_dir>`
- [x] 2.4 Add `babel_code_goat.py` discovery validation for test-like non-Python filenames and for recursive discovery that yields zero tests

## 3. Mutation-Style Discovery

- [x] 3.1 Extend `babel_code_goat.py` `TestDiscoverer.visit_body` to recognize adjacent mutation-style entrypoint statement and assignment groups [extends babel-code-goat-cli/support-single-call-traceability]
- [x] 3.2 Add `babel_code_goat.py` helpers to collect variables passed to or assigned from a mutation entrypoint call
- [x] 3.3 Reuse existing `babel_code_goat.py` assertion parsing for mutation-style assertions while supplying the preceding entrypoint call arguments
- [x] 3.4 Raise `DiscoveryError` from `babel_code_goat.py` when mutation-style groups violate adjacency, dependency, or single-entrypoint constraints

## 4. Verification

- [x] 4.1 Run the project unit tests with `python -m unittest`
- [x] 4.2 Run `openspec status --change "support-mutation-directory-discovery"` and resolve any incomplete artifacts
- [x] 4.3 Run OpenSpec validation for `support-mutation-directory-discovery` if the local CLI exposes a validation command
