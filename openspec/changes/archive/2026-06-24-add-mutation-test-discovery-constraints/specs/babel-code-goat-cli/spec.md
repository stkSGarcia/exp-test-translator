## ADDED Requirements

### Requirement: Mutation-style test discovery
The system SHALL discover mutation-style tests only when an entrypoint call appears as a standalone statement or as the value of a direct assignment, and that statement is immediately followed by one or more asserts without another entrypoint call before those asserts. Each mutation-style assert MUST reference at least one variable passed to the mutation call or the variable directly assigned from the mutation call result. Files that use mutation patterns outside these constraints MUST fail discovery.

#### Scenario: Statement mutation call is discovered
- **WHEN** a discovered Python test file contains `a = [2, 0, 2, 1, 1, 0]`, then `sort_colors(a)`, then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery succeeds and reports the assertion as a test that invokes `sort_colors(a)` once before checking the mutated value of `a`

#### Scenario: Assignment mutation call is discovered
- **WHEN** a discovered Python test file contains `result = mutate(a)` immediately followed by `assert result == expected`
- **THEN** discovery succeeds and reports the assertion as a test that invokes `mutate(a)` once before checking `result`

#### Scenario: Multiple adjacent mutation asserts are discovered
- **WHEN** an entrypoint call statement is immediately followed by two asserts and each assert references a variable passed to that call
- **THEN** discovery succeeds and reports both asserts as tests associated with that single mutation call

#### Scenario: Mutation call without following assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement that is not immediately followed by an assert
- **THEN** discovery fails

#### Scenario: Non-adjacent mutation assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement, then another non-assert statement, then an assert that depends on the mutation call
- **THEN** discovery fails

#### Scenario: Unrelated mutation assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement followed by an assert that references no variable passed to the call and no variable assigned from the call
- **THEN** discovery fails

#### Scenario: Mutation assert with entrypoint call fails discovery
- **WHEN** a mutation-style assert contains another configured entrypoint invocation
- **THEN** discovery fails

## MODIFIED Requirements

### Requirement: Test discovery source
The system SHALL discover tests from any `.py` file under `<tests_dir>` recursively. Discovery MUST reject non-`.py` files under `<tests_dir>` whose file names match test-like patterns `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. If recursive discovery finds no tests, discovery MUST fail.

#### Scenario: Root tests file is discovered
- **WHEN** `<tests_dir>/tests.py` contains an allowed assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_cases.py` contains an allowed assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Multiple Python files are discovered recursively
- **WHEN** `<tests_dir>/tests.py` and `<tests_dir>/nested/more_tests.py` both contain allowed tests
- **THEN** discovery includes tests from both files

#### Scenario: Test-like non-Python file is a discovery error
- **WHEN** `<tests_dir>/nested/test_cases.txt` exists
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: No recursive tests is a discovery error
- **WHEN** no tests are discovered from any `.py` file under `<tests_dir>`
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

### Requirement: Test IDs
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-path>:<line>` using the source file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same line outside loop expansion in the same file, the system MUST suffix them as `<relative-path>:<line>#0`, `<relative-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that file.

#### Scenario: Root test ID uses line
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Nested test ID uses relative path and line
- **WHEN** one non-loop test originates on line 5 of `<tests_dir>/nested/test_cases.py`
- **THEN** its ID is `nested/test_cases.py:5`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of the same file outside loop expansion
- **THEN** their IDs are `<relative-path>:12#0` and `<relative-path>:12#1`

#### Scenario: Same line in different files keeps separate IDs
- **WHEN** one test originates on line 3 of `<tests_dir>/a/tests.py` and another test originates on line 3 of `<tests_dir>/b/tests.py`
- **THEN** their IDs are `a/tests.py:3` and `b/tests.py:3`

#### Scenario: Loop statement ID uses relative path and loop line
- **WHEN** a loop statement originates on line 2 of `<tests_dir>/nested/test_cases.py`
- **THEN** the loop test ID is `nested/test_cases.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `<tests_dir>/nested/test_cases.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_cases.py:3:0` and `nested/test_cases.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `<tests_dir>/nested/test_cases.py`
- **THEN** the assertion test IDs are `nested/test_cases.py:5:0`, `nested/test_cases.py:5:1`, `nested/test_cases.py:5:2`, and `nested/test_cases.py:5:3`
