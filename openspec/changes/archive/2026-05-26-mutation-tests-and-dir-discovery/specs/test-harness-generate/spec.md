## MODIFIED Requirements

### Requirement: Generate command discovers tests from all .py files in tests_dir
The `generate` sub-command SHALL discover tests from all `.py` files found recursively under `<tests_dir>`, not only from a `tests.py` file at the root. Tests from all discovered files are merged into a single tester file. The traversal order SHALL be deterministic (files sorted by path).

#### Scenario: Single tests.py still works
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and only `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.py` is created containing tests from `tests.py` and the process exits `0`

#### Scenario: Tests discovered from subdirectory
- **WHEN** `<tests_dir>/subdir/test_cases.py` exists with valid assertions
- **THEN** `generate` includes those test cases in the produced tester file

#### Scenario: Multiple files merged
- **WHEN** `<tests_dir>/tests.py` and `<tests_dir>/subdir/more_tests.py` both contain assertions
- **THEN** the produced tester file contains test cases from both files

### Requirement: Test-like non-.py files are a discovery error
If any file under `<tests_dir>` (recursively) matches a test-like name pattern but is not a `.py` file, `generate` SHALL exit non-zero with an error message to stderr and NOT create a tester file. Test-like patterns are: `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, `*_tests.<ext>` for any extension other than `.py`.

#### Scenario: Non-.py test-like file causes discovery error
- **WHEN** `<tests_dir>/tests.js` exists
- **THEN** `generate` exits non-zero with an error and no tester file is created

#### Scenario: Non-test-like non-.py files are ignored
- **WHEN** `<tests_dir>/solution.js` exists (does not match test-like patterns)
- **THEN** `generate` ignores that file and proceeds normally

### Requirement: Empty test discovery is a discovery error
If no test cases are discovered across all `.py` files in `<tests_dir>`, `generate` SHALL exit non-zero with an error message to stderr and NOT create a tester file.

#### Scenario: No tests in any file
- **WHEN** all `.py` files under `<tests_dir>` contain no parseable test cases
- **THEN** `generate` exits non-zero with a "no tests found" error and no tester file is created

#### Scenario: At least one test discovered
- **WHEN** at least one valid test case is found across any `.py` file in `<tests_dir>`
- **THEN** `generate` proceeds normally

## ADDED Requirements

### Requirement: Test IDs include relative file path
Test case IDs SHALL be prefixed with the relative path from `<tests_dir>` to the source `.py` file using forward slashes, followed by `:` and the 1-based line number. Multiple tests on the same line are disambiguated with `#k` (0-indexed). The old `tests.py:<line>` format is replaced by `<relpath>:<line>`.

#### Scenario: Single tests.py at root uses path prefix
- **WHEN** an assertion on line 5 of `<tests_dir>/tests.py` is discovered
- **THEN** its test ID is `tests.py:5`

#### Scenario: Nested file uses relative path prefix
- **WHEN** an assertion on line 10 of `<tests_dir>/subdir/test_foo.py` is discovered
- **THEN** its test ID is `subdir/test_foo.py:10`

#### Scenario: Same-line tests use #k suffix
- **WHEN** two tests originate from line 7 of `subdir/tests.py`
- **THEN** their IDs are `subdir/tests.py:7#0` and `subdir/tests.py:7#1`

#### Scenario: Loop iteration IDs use path prefix
- **WHEN** a loop on line 3 of `nested/test_foo.py` has iterations
- **THEN** the loop-as-test ID is `nested/test_foo.py:3` and assertion IDs use `nested/test_foo.py:<line>:<iter>`
