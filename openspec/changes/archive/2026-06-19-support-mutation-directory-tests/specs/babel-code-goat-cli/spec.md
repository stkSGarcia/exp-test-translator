## ADDED Requirements

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests where the configured entrypoint is called as a statement or assignment and is immediately followed by one or more assertions that inspect variables affected by that call. A mutation-style entrypoint call MUST be either a standalone expression statement or the value of a single-target assignment. Each immediately following mutation assertion MUST contain no configured entrypoint call and MUST reference at least one variable passed to the mutation call or directly assigned from the mutation call. If a Python test file uses a mutation-style entrypoint call outside these constraints, discovery MUST fail.

#### Scenario: Standalone mutation call is discovered
- **WHEN** a Python test file contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` and then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assertion as a mutation-style test that first invokes `sort_colors(a)` and then evaluates the assertion against the post-call value of `a`

#### Scenario: Assignment mutation call is discovered
- **WHEN** a Python test file contains `result = normalize(data)` immediately followed by `assert result == expected`
- **THEN** discovery includes the assertion as a mutation-style test because the assertion references a variable directly assigned from the mutation call

#### Scenario: Multiple immediate mutation assertions are discovered
- **WHEN** a mutation-style entrypoint call is immediately followed by two assertions and both assertions reference a variable passed to or assigned from the mutation call
- **THEN** discovery includes both assertions as mutation-style tests using the same entrypoint call setup

#### Scenario: Mutation assert cannot call entrypoint
- **WHEN** a mutation-style entrypoint call is followed by `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery fails because mutation follow-up assertions MUST NOT contain an entrypoint call

#### Scenario: Mutation assert must reference affected variable
- **WHEN** a mutation-style entrypoint call is followed by an assertion that references only variables not passed to or assigned from the mutation call
- **THEN** discovery fails because the assertion is not tied to the mutation call

#### Scenario: Mutation call must be immediately followed by assertion
- **WHEN** a standalone or assignment entrypoint call is followed by any non-assert statement before the first assertion
- **THEN** discovery fails because the mutation pattern is outside the allowed shape

## MODIFIED Requirements

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from any `.py` file under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, mutation-style entrypoint call blocks, raise-any expectation blocks, and typed exception expectation blocks. Each discovered direct assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions for direct tests MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. Discovery MUST fail if no tests are discovered recursively under `<tests_dir>`. Discovery MUST fail if any non-`.py` file under `<tests_dir>` has a test-like name matching `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`.

#### Scenario: Assertions inside functions are discovered
- **WHEN** a Python test file contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** a Python test file contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** a Python test file contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** a Python test file contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Recursive Python files are discovered
- **WHEN** `<tests_dir>` contains `tests.py`, `subdir/test_more.py`, and `nested/cases/examples.py` with supported tests
- **THEN** discovery includes tests from all three Python files

#### Scenario: Test-like non-Python file is rejected
- **WHEN** `<tests_dir>` contains a non-Python file named `test_cases.txt`, `example_test.js`, `tests.md`, or `sample_tests.json`
- **THEN** discovery fails because test-like files MUST be Python files

#### Scenario: Empty recursive discovery is rejected
- **WHEN** `<tests_dir>` contains no discoverable tests in any Python file
- **THEN** discovery fails

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** a Python test file contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** a Python test file contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** a Python test file contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** a Python test file contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** a Python test file imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Discovery fails
- **WHEN** recursive test discovery cannot parse a Python test file or finds unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST be based on the forward-slash relative path from `<tests_dir>` to the Python source file and the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative/path.py>:<line>`. If multiple non-loop tests originate from the same source path and source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative/path.py>:<line>:<index>` for a single loop and `<relative/path.py>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source path, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single root test on a line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single nested test on a line
- **WHEN** one test originates from line 5 of `<tests_dir>/subdir/tests.py`
- **THEN** its test ID is `subdir/tests.py:5`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/nested/test_foo.py`
- **THEN** their test IDs are `nested/test_foo.py:12#0`, `nested/test_foo.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/cases/tests.py`
- **THEN** the loop test ID is `cases/tests.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/tests.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `tests.py:3:0` and `tests.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop in `<tests_dir>/tests.py` at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `tests.py:3:0` and the assertion test ID is `tests.py:4:0:1`
