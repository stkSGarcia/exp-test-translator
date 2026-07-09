## MODIFIED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat

### Requirement: Test discovery source (adapts babel-code-goat-cli/add-babel-code-goat/test-discovery-source)
The system SHALL discover tests from `.py` files under `<tests_dir>` recursively. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called.

The system MUST report a discovery error when recursive discovery finds no supported tests. The system MUST report a discovery error when `<tests_dir>` contains a non-`.py` file with a test-like name matching `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}`.

#### Scenario: Nested Python tests are discovered
- **GIVEN** `<tests_dir>` contains `nested/test_sort.py`
- **WHEN** the file contains supported tests for the configured entrypoint
- **THEN** discovery includes tests from `nested/test_sort.py`

#### Scenario: No supported tests is a discovery error
- **GIVEN** `<tests_dir>` contains no supported tests in any recursive `.py` file
- **WHEN** discovery runs
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: Test-like non-Python file is a discovery error
- **GIVEN** `<tests_dir>` contains `test_data.txt`
- **WHEN** discovery runs
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

### Requirement: Test IDs (adapts babel-code-goat-cli/add-babel-code-goat/test-ids)
The system SHALL assign each discovered test a line-based ID in the form `<relative-path>:<line>` using the path relative to `<tests_dir>` with forward slashes and 1-based source lines.

If multiple tests originate from the same line, the system MUST suffix them as `#0`, `#1`, and later zero-based suffixes.

#### Scenario: Nested test ID uses relative path
- **WHEN** one test originates on line 12 of `<tests_dir>/nested/test_sort.py`
- **THEN** its ID is `nested/test_sort.py:12`

#### Scenario: Same-line IDs use zero-based suffixes
- **WHEN** two tests originate on line 12 of `<tests_dir>/nested/test_sort.py`
- **THEN** their IDs are `nested/test_sort.py:12#0` and `nested/test_sort.py:12#1`

