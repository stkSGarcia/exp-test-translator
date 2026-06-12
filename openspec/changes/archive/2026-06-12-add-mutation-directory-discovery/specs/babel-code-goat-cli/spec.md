## ADDED Requirements

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests where the configured entrypoint is called as a standalone expression statement or as the value of a single-target assignment. A mutation-style entrypoint call MUST be immediately followed by one or more assertion statements with no intervening non-assert statement. Each mutation assertion MUST NOT call the configured entrypoint and MUST reference at least one variable passed directly to the mutation call or directly assigned from the mutation call. A Python test file that uses a mutation-style entrypoint call outside these constraints MUST fail discovery.

#### Scenario: In-place mutation statement is discovered
- **WHEN** a Python test file contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` and then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assertion as one mutation-style test that invokes `sort_colors(a)` before evaluating the assertion

#### Scenario: Mutation assignment is discovered
- **WHEN** a Python test file contains `result = mutate(a)` immediately followed by `assert result == expected`
- **THEN** discovery includes the assertion as one mutation-style test that invokes `mutate(a)` and evaluates the assertion against the assigned `result`

#### Scenario: Multiple immediate mutation assertions are discovered
- **WHEN** a Python test file contains one mutation-style entrypoint call immediately followed by two assertions that each reference a variable passed to the call
- **THEN** discovery includes one mutation-style test for each assertion in source order

#### Scenario: Mutation call without immediate assertion is rejected
- **WHEN** a Python test file contains an entrypoint call as a statement or assignment and the next statement is not an assertion
- **THEN** discovery fails

#### Scenario: Mutation assertion that calls entrypoint is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call followed by an assertion that also calls the configured entrypoint
- **THEN** discovery fails

#### Scenario: Mutation assertion without mutation variable is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call followed by an assertion that references neither a variable passed to the call nor the variable assigned from the call
- **THEN** discovery fails

## MODIFIED Requirements

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion, mutation assertion, or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. The system MUST reject any non-`.py` file under `<tests_dir>` whose filename has a non-Python extension and matches `test*`, `*_test`, `tests`, or `*_tests` before that extension. The system MUST fail discovery when recursive discovery finds no tests.

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
- **WHEN** `<tests_dir>` contains `tests.py` and `nested/test_more.py` with supported test constructs
- **THEN** discovery includes tests from both Python files

#### Scenario: Test-like non-Python file is rejected
- **WHEN** `<tests_dir>` contains `test_cases.txt`, `case_test.md`, `tests.json`, or `case_tests.yaml`
- **THEN** discovery fails

#### Scenario: Empty recursive discovery is rejected
- **WHEN** `<tests_dir>` contains no supported tests in any recursively discovered Python file
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
- **WHEN** recursive Python test discovery cannot read or parse a candidate Python file or contains unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST be based on the Python source file path relative to `<tests_dir>` using forward slashes, followed by the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative-path>:<line>`. If multiple non-loop tests originate from the same source path and source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement source path and line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source path, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single test on a root file line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single test on a nested file line
- **WHEN** one test originates from line 5 of `<tests_dir>/subdir/tests.py`
- **THEN** its test ID is `subdir/tests.py:5`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/nested/test_foo.py`
- **THEN** their test IDs are `nested/test_foo.py:12#0`, `nested/test_foo.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/nested/tests.py`
- **THEN** the loop test ID is `nested/tests.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/nested/tests.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `nested/tests.py:3:0` and `nested/tests.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop in `<tests_dir>/tests.py` at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `tests.py:3:0` and the assertion test ID is `tests.py:4:0:1`
