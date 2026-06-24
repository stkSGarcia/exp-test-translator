## MODIFIED Requirements

### Requirement: Test discovery source
The system SHALL discover tests from any `.py` file under `<tests_dir>` recursively. Non-`.py` files under `<tests_dir>` whose names match test-like patterns MUST be discovery errors. Test-like patterns are `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, and `*_tests.<ext>`, where `<ext>` is any extension other than `py`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. If no tests are discovered recursively under `<tests_dir>`, discovery MUST fail.

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_cases.py` contains a supported assertion and no root `tests.py` exists
- **THEN** the assertion is discovered as a test

#### Scenario: Root tests file remains valid
- **WHEN** `<tests_dir>/tests.py` contains a supported assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

#### Scenario: Non-Python test-like file is rejected
- **WHEN** `<tests_dir>/nested/test_cases.txt` exists
- **THEN** discovery fails

#### Scenario: Empty recursive discovery is an error
- **WHEN** no supported tests are discovered in any `.py` file under `<tests_dir>`
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed direct-call assertion forms, constrained mutation-style entrypoint call statements or assignments, mutation-style assertions immediately following those calls, and supported raise expectation blocks as non-comment code in discovered Python test files. Each allowed direct-call assertion, each mutation-style assertion, each supported raise expectation block, and each supported loop statement MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

#### Scenario: Equality assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...) == expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Inequality assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...) != expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Truthy assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Falsy assertion is discovered
- **WHEN** a discovered Python test file contains `assert not ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Raise-any block is discovered
- **WHEN** a discovered Python test file contains a `try` block that calls the entrypoint, then asserts `False`, and catches `Exception` with `pass`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed raise block is discovered
- **WHEN** a discovered Python test file contains a `try` block that calls the entrypoint, then asserts `False`, and catches a specific exception type such as `ValueError`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception matching that type

#### Scenario: Typed raise block with substring message check is discovered
- **WHEN** a discovered Python test file contains a typed exception handler that asserts a string literal is contained in `str(e)`
- **THEN** the block is discovered as one test that also requires the raised exception message to contain that substring

#### Scenario: Typed raise block with regex message check is discovered
- **WHEN** a discovered Python test file contains a typed exception handler that asserts `re.search(<pattern>, str(e))`
- **THEN** the block is discovered as one test that also requires the raised exception message to match that regex pattern

#### Scenario: Math isclose assertion is discovered
- **WHEN** a discovered Python test file contains `assert math.isclose(ENTRYPOINT(args...), expected, abs_tol=abs_tol, rel_tol=rel_tol)`
- **THEN** the assertion is discovered as one test with per-assert absolute and relative tolerance metadata

#### Scenario: Absolute difference tolerance assertion is discovered
- **WHEN** a discovered Python test file contains `assert abs(ENTRYPOINT(args...) - expected) < tol` or `assert abs(ENTRYPOINT(args...) - expected) <= tol`
- **THEN** the assertion is discovered as one test with a per-assert absolute tolerance and strictness metadata

#### Scenario: Literal assignment for parameterization is accepted
- **WHEN** a discovered Python test file contains a simple assignment such as `cases = [((1, 2), 3)]` used by a supported loop
- **THEN** discovery accepts the assignment as parameterization data and does not report the assignment itself as a test

#### Scenario: For loop is discovered
- **WHEN** a discovered Python test file contains a supported `for ... in ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: While loop is discovered
- **WHEN** a discovered Python test file contains a supported `while ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: Mutation call statement is discovered
- **WHEN** a discovered Python test file contains an entrypoint call statement immediately followed by a valid mutation-style assertion
- **THEN** the mutation-style assertion is discovered as one test

#### Scenario: Mutation assignment is discovered
- **WHEN** a discovered Python test file contains an assignment from an entrypoint call immediately followed by a valid mutation-style assertion
- **THEN** the mutation-style assertion is discovered as one test

#### Scenario: Unsupported code fails discovery
- **WHEN** a discovered Python test file contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Single-call traceable assertions
The system SHALL discover supported direct-call assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject direct-call assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls. Mutation-style assertions are governed by the mutation-style requirements.

#### Scenario: Entrypoint call on right side is discovered
- **WHEN** a discovered Python test file contains `assert 3 == ENTRYPOINT(1, 2)`
- **THEN** the assertion is discovered as one test traceable to the single `ENTRYPOINT(1, 2)` invocation

#### Scenario: Multiple entrypoint calls fail discovery
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(1) == ENTRYPOINT(2)`
- **THEN** discovery fails

#### Scenario: Unsupported helper call fails discovery
- **WHEN** a discovered Python test file contains `assert normalize(ENTRYPOINT(1)) == 1`
- **THEN** discovery fails

#### Scenario: Tolerance helper remains traceable
- **WHEN** a discovered Python test file contains `assert math.isclose(ENTRYPOINT("near"), 1.0, abs_tol=0.01)`
- **THEN** the assertion is discovered as one test with per-assert tolerance metadata traceable to the single entrypoint invocation

### Requirement: Test IDs
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-path>:<line>` using the test file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same relative path and line outside loop expansion, the system MUST suffix them as `<relative-path>:<line>#0`, `<relative-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that relative path.

#### Scenario: Single test ID uses relative path and line
- **WHEN** one non-loop test originates on line 12 of `nested/test_foo.py`
- **THEN** its ID is `nested/test_foo.py:12`

#### Scenario: Root tests file ID remains familiar
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of `nested/test_foo.py` outside loop expansion
- **THEN** their IDs are `nested/test_foo.py:12#0` and `nested/test_foo.py:12#1`

#### Scenario: Loop statement ID uses relative path and loop line
- **WHEN** a loop statement originates on line 2 of `nested/test_foo.py`
- **THEN** the loop test ID is `nested/test_foo.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `nested/test_foo.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_foo.py:3:0` and `nested/test_foo.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `nested/test_foo.py`
- **THEN** the assertion test IDs are `nested/test_foo.py:5:0`, `nested/test_foo.py:5:1`, `nested/test_foo.py:5:2`, and `nested/test_foo.py:5:3`

## ADDED Requirements

### Requirement: Mutation-style tests
The system SHALL support mutation-style tests when an entrypoint call is a standalone expression statement or the value of an assignment, and that statement is immediately followed by one or more assertion statements with no intervening non-assert statement. Each mutation-style assertion MUST contain zero configured entrypoint calls and MUST reference at least one variable passed to the mutation call or directly assigned from the mutation call. Files that use mutation-style patterns outside these constraints MUST fail discovery.

#### Scenario: Standalone mutation call with mutated argument assertion is discovered
- **WHEN** a discovered Python test file contains `items = [2, 0, 1]`, followed by `ENTRYPOINT(items)`, followed immediately by `assert items == [0, 1, 2]`
- **THEN** the assertion is discovered as one mutation-style test that invokes the entrypoint once before evaluating the assertion

#### Scenario: Assigned mutation result assertion is discovered
- **WHEN** a discovered Python test file contains `items = [2, 0, 1]`, followed by `result = ENTRYPOINT(items)`, followed immediately by `assert result is None` or `assert items == [0, 1, 2]`
- **THEN** each immediate assertion that references `result` or `items` is discovered as one mutation-style test

#### Scenario: Multiple immediate mutation assertions share one call
- **WHEN** a discovered Python test file contains a valid mutation call followed immediately by two valid assertions that reference variables tied to that call
- **THEN** both assertions are discovered as mutation-style tests that execute after a single entrypoint invocation for the group

#### Scenario: Mutation call without following assertion is rejected
- **WHEN** a discovered Python test file contains a standalone entrypoint call statement that is not immediately followed by an assertion
- **THEN** discovery fails

#### Scenario: Intervening statement breaks mutation group
- **WHEN** a discovered Python test file contains an entrypoint mutation call, then any non-assert statement, then an assertion about the mutated variable
- **THEN** discovery fails

#### Scenario: Mutation assertion must reference related variable
- **WHEN** a discovered Python test file contains an entrypoint mutation call followed by `assert expected == [0, 1, 2]`
- **THEN** discovery fails because the assertion does not reference a variable passed to or assigned from the mutation call

#### Scenario: Mutation assertion cannot call entrypoint
- **WHEN** a discovered Python test file contains an entrypoint mutation call followed by `assert ENTRYPOINT(items) == [0, 1, 2]`
- **THEN** discovery fails
