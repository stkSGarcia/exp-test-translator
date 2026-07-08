## ADDED Requirements

> Extends: babel-code-goat-cli/support-loop-construct-tests

### Requirement: Mutation-style test grouping (adapts babel-code-goat-cli/support-loop-construct-tests/allowed-test-constructs)
The Python test discovery SHALL accept mutation-style tests only when an entrypoint call appears as a statement or assignment and is immediately followed by one or more `assert` statements with no intervening entrypoint call.

Each assert in a mutation-style test MUST reference at least one variable passed to the mutation entrypoint call or directly assigned from the entrypoint call. Files containing mutation-style patterns outside these constraints SHALL fail discovery.

#### Scenario: Statement call mutates passed variable
- **GIVEN** a Python test file contains `a = [2, 0, 2, 1, 1, 0]`
- **WHEN** `sort_colors(a)` is immediately followed by `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery creates one mutation-style test case for the entrypoint call and assertion

#### Scenario: Assignment call is asserted through assigned result
- **GIVEN** a Python test file contains an assignment `result = normalize(items)`
- **WHEN** the immediately following assert references `result`
- **THEN** discovery creates one mutation-style test case for the assignment entrypoint call and assertion

#### Scenario: Assert does not reference mutated or assigned variable
- **WHEN** an assert following a mutation-style entrypoint call references no variable passed to the call or directly assigned from the call
- **THEN** discovery fails for that file

#### Scenario: Entrypoint interrupts mutation assert group
- **WHEN** an entrypoint call appears between a mutation-style entrypoint call and a later assert
- **THEN** discovery fails for that file instead of grouping the later assert with the first call

### Requirement: Recursive tests directory discovery (adapts babel-code-goat-cli/support-loop-construct-tests/allowed-test-constructs)
The Python test discovery SHALL discover tests recursively in any `.py` file under the configured tests directory and SHALL NOT require a root `tests.py` file.

Non-`.py` files under the tests directory with test-like names matching `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>` SHALL fail discovery. If recursive discovery finds no tests under the tests directory, discovery SHALL fail.

#### Scenario: Nested Python test file is discovered
- **WHEN** a supported test appears in `nested/test_foo.py` under the configured tests directory
- **THEN** discovery includes that test in the discovered test set

#### Scenario: Root tests file is absent
- **WHEN** the configured tests directory contains supported tests in Python files but no root `tests.py`
- **THEN** discovery succeeds

#### Scenario: Test-like non-Python file is present
- **WHEN** the configured tests directory contains `test_foo.txt`
- **THEN** discovery fails for the tests directory

#### Scenario: No tests are discovered
- **WHEN** recursive discovery finds no supported tests in the configured tests directory
- **THEN** discovery fails for the tests directory

### Requirement: Path-based test IDs (adapts babel-code-goat-cli/support-loop-construct-tests/test-ids)
The Python test discovery SHALL assign each discovered non-loop test an ID using the tests-directory-relative path with forward slashes, followed by `:<line>` using 1-based source lines.

If multiple non-loop tests originate from the same line, discovery SHALL append `#<k>` where `k` is a 0-based ordinal for tests from that line.

#### Scenario: Root file ID uses relative path and line
- **WHEN** one non-loop test originates on line 5 of `tests.py` at the tests directory root
- **THEN** its ID is `tests.py:5`

#### Scenario: Nested file ID uses forward slashes
- **WHEN** one non-loop test originates on line 10 of `nested/test_foo.py`
- **THEN** its ID is `nested/test_foo.py:10`

#### Scenario: Same-line IDs use ordinal suffixes
- **WHEN** two non-loop tests originate from line 12 of `nested/test_foo.py`
- **THEN** their IDs are `nested/test_foo.py:12#0` and `nested/test_foo.py:12#1`
