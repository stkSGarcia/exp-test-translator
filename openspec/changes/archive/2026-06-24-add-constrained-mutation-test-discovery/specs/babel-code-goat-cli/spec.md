## ADDED Requirements

### Requirement: Mutation-style test discovery
The system SHALL support mutation-style tests where a configured entrypoint call appears as either a standalone expression statement or an assignment statement and is immediately followed by one or more assertions that do not call the entrypoint. The system MUST execute the mutation call once before evaluating each associated follow-up assertion group. Each mutation follow-up assertion MUST reference at least one variable passed to the mutation call or one variable directly assigned from the mutation call. Discovery MUST fail when a mutation-style pattern is separated from its follow-up assertions by any non-assert statement, when a follow-up assertion calls the entrypoint, or when a follow-up assertion does not reference a mutation-related variable.

#### Scenario: Standalone mutation call is discovered
- **WHEN** a discovered Python test file contains `a = [2, 0, 1]`, then `sort_colors(a)`, then `assert a == [0, 1, 2]`
- **THEN** discovery creates a mutation-style test that invokes `sort_colors(a)` once and evaluates the assertion against the mutated `a`

#### Scenario: Assignment mutation result is discovered
- **WHEN** a discovered Python test file contains `result = normalize(items)` followed immediately by `assert result == expected`
- **THEN** discovery creates a mutation-style test that invokes `normalize(items)` once and evaluates the assertion against `result`

#### Scenario: Multiple immediate mutation assertions are discovered
- **WHEN** a mutation call is immediately followed by two assertions and both assertions reference a mutation-related variable
- **THEN** each follow-up assertion is discovered as a separate test associated with the same mutation call

#### Scenario: Separated mutation assertion fails discovery
- **WHEN** an entrypoint call statement is followed by a non-assert statement before an assertion that inspects the mutated variable
- **THEN** discovery fails

#### Scenario: Mutation follow-up entrypoint call fails discovery
- **WHEN** a mutation follow-up assertion calls the configured entrypoint again
- **THEN** discovery fails

#### Scenario: Unrelated mutation follow-up assertion fails discovery
- **WHEN** a mutation follow-up assertion does not reference any variable passed to the mutation call or directly assigned from it
- **THEN** discovery fails

## MODIFIED Requirements

### Requirement: Test discovery source
The system SHALL recursively discover tests from every `.py` file under `<tests_dir>` using paths relative to `<tests_dir>`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. Discovery MUST fail when recursive scanning finds no tests. Discovery MUST also fail when `<tests_dir>` contains a non-`.py` file whose relative basename matches `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`.

#### Scenario: Root Python test file is discovered
- **WHEN** `<tests_dir>/tests.py` contains a supported test
- **THEN** discovery includes that test

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_sort.py` contains a supported test
- **THEN** discovery includes that test

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

#### Scenario: Test-like non-Python file is a discovery error
- **WHEN** `<tests_dir>` contains `nested/test_sort.txt`
- **THEN** discovery fails

#### Scenario: No recursive tests is a discovery error
- **WHEN** recursive scanning under `<tests_dir>` finds no supported tests
- **THEN** discovery fails

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed assertion forms, supported mutation-style entrypoint call statements and assignments, and supported raise expectation blocks as non-comment code in discovered Python test files. Each allowed assertion, each supported raise expectation block, each supported loop statement, and each mutation follow-up assertion MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

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

#### Scenario: Mutation-style entrypoint statement is accepted
- **WHEN** a discovered Python test file contains `ENTRYPOINT(args...)` immediately followed by a supported mutation follow-up assertion
- **THEN** discovery accepts the entrypoint statement as mutation setup and reports the follow-up assertion as a test

#### Scenario: Mutation-style entrypoint assignment is accepted
- **WHEN** a discovered Python test file contains `result = ENTRYPOINT(args...)` immediately followed by a supported mutation follow-up assertion that references `result`
- **THEN** discovery accepts the assignment as mutation setup and reports the follow-up assertion as a test

#### Scenario: Unsupported code fails discovery
- **WHEN** a discovered Python test file contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Single-call traceable assertions
The system SHALL discover supported non-mutation assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject non-mutation assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls. Mutation follow-up assertions MUST instead satisfy the mutation-style test discovery requirements.

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

#### Scenario: Standalone zero-call assertion fails discovery
- **WHEN** a discovered Python test file contains `assert expected == 3` outside a mutation-style assertion group
- **THEN** discovery fails

### Requirement: Test IDs
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-python-path>:<line>` using the Python file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same line outside loop expansion, the system MUST suffix them as `<relative-python-path>:<line>#0`, `<relative-python-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-python-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-python-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that relative Python file.

#### Scenario: Single test ID uses relative file and line
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/nested/test_sort.py`
- **THEN** its ID is `nested/test_sort.py:12`

#### Scenario: Root file ID remains path based
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of `<tests_dir>/nested/test_sort.py` outside loop expansion
- **THEN** their IDs are `nested/test_sort.py:12#0` and `nested/test_sort.py:12#1`

#### Scenario: Loop statement ID uses loop line
- **WHEN** a loop statement originates on line 2 of `<tests_dir>/nested/test_sort.py`
- **THEN** the loop test ID is `nested/test_sort.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `<tests_dir>/nested/test_sort.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_sort.py:3:0` and `nested/test_sort.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `<tests_dir>/nested/test_sort.py`
- **THEN** the assertion test IDs are `nested/test_sort.py:5:0`, `nested/test_sort.py:5:1`, `nested/test_sort.py:5:2`, and `nested/test_sort.py:5:3`

### Requirement: Discovery failure output
If test discovery fails, the system SHALL output exactly `{"status":"error","passed":[],"failed":[]}` and exit with status code `2`.

#### Scenario: Malformed tests produce discovery error
- **WHEN** a discovered Python test file cannot be parsed or contains unsupported constructs
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Test-like non-Python file produces discovery error
- **WHEN** `<tests_dir>` contains a non-`.py` file with a test-like basename
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: No discovered tests produces discovery error
- **WHEN** recursive discovery finds no tests under `<tests_dir>`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`
