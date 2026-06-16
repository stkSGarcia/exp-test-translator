## ADDED Requirements

> Extends: `babel-code-goat-cli/support-single-call-traceability`
> Extends: `babel-code-goat-cli/add-loop-as-test-support`

### Requirement: Recursive Test File Discovery
The system SHALL discover tests from `.py` files under `<tests_dir>` recursively and MUST NOT require tests to be defined in `<tests_dir>/tests.py` (adapts `babel-code-goat-cli/support-single-call-traceability/test-discovery-source-and-allowed-constructs`).

#### Scenario: nested python tests are discovered
- **GIVEN** `<tests_dir>/nested/test_sort.py` contains `assert ENTRYPOINT([2, 1]) == [1, 2]`
- **WHEN** test discovery runs for `<tests_dir>`
- **THEN** discovery includes the assertion as a test

#### Scenario: root tests file is not required
- **GIVEN** `<tests_dir>` has no `tests.py`
- **AND** `<tests_dir>/cases/test_values.py` contains `assert ENTRYPOINT(1) == 2`
- **WHEN** test discovery runs for `<tests_dir>`
- **THEN** discovery succeeds and includes the nested test

### Requirement: Test-Like File Validation
The system SHALL fail discovery when any non-`.py` file under `<tests_dir>` recursively has a test-like name. Test-like names MUST include `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, and `*_tests.{ext}`.

#### Scenario: non-python test-like file is rejected
- **GIVEN** `<tests_dir>/nested/test_cases.txt` exists
- **WHEN** test discovery runs for `<tests_dir>`
- **THEN** discovery fails with a discovery error

#### Scenario: no recursive tests are discovered
- **GIVEN** `<tests_dir>` contains no discoverable tests in any `.py` file
- **WHEN** test discovery runs for `<tests_dir>`
- **THEN** discovery fails with a discovery error

### Requirement: Path-Based Test IDs
Each discovered test ID MUST use the test file path relative to `<tests_dir>` with forward slashes, followed by `:<line>` using the 1-based source line where the test originates. If multiple tests originate from the same source line, their IDs MUST append `#<k>` where `<k>` is a zero-indexed suffix in discovery order (adapts `babel-code-goat-cli/add-loop-as-test-support/test-ids`).

#### Scenario: nested test id uses relative path
- **GIVEN** one test originates from line 10 of `<tests_dir>/nested/test_foo.py`
- **WHEN** discovery records the test
- **THEN** its test ID is `nested/test_foo.py:10`

#### Scenario: multiple tests on one nested line
- **GIVEN** two tests originate from line 8 of `<tests_dir>/cases/tests.py`
- **WHEN** discovery records both tests
- **THEN** their test IDs are `cases/tests.py:8#0` and `cases/tests.py:8#1`

### Requirement: Mutation-Style Test Discovery
The system SHALL treat an entrypoint call as a mutation-style test only when the call is a standalone statement or is directly assigned to a variable, the next statements are one or more asserts, no such assert contains an entrypoint call, and each such assert references at least one variable passed to the mutation call or the variable directly assigned from it (adapts `babel-code-goat-cli/support-single-call-traceability/test-discovery-source-and-allowed-constructs`).

#### Scenario: standalone mutation call is discovered
- **GIVEN** a test file contains `values = [2, 0, 1]`, then `ENTRYPOINT(values)`, then `assert values == [0, 1, 2]`
- **WHEN** test discovery runs
- **THEN** discovery records a mutation-style test for the entrypoint call

#### Scenario: assignment mutation call is discovered
- **GIVEN** a test file contains `result = ENTRYPOINT([2, 1])`, then `assert result == [1, 2]`
- **WHEN** test discovery runs
- **THEN** discovery records a mutation-style test for the assignment entrypoint call

#### Scenario: mutation assert cannot contain another entrypoint call
- **GIVEN** a test file contains `values = [2, 1]`, then `ENTRYPOINT(values)`, then `assert ENTRYPOINT(values) == [1, 2]`
- **WHEN** test discovery runs
- **THEN** discovery fails with a discovery error

#### Scenario: mutation assert must reference mutated variable
- **GIVEN** a test file contains `values = [2, 1]`, then `ENTRYPOINT(values)`, then `assert True`
- **WHEN** test discovery runs
- **THEN** discovery fails with a discovery error

#### Scenario: mutation asserts must immediately follow call
- **GIVEN** a test file contains `values = [2, 1]`, then `ENTRYPOINT(values)`, then `other = values`, then `assert values == [1, 2]`
- **WHEN** test discovery runs
- **THEN** discovery fails with a discovery error
