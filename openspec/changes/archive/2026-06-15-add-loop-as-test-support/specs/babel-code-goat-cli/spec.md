## ADDED Requirements

### Requirement: Loop-Based Test Parameterization
The system SHALL support loop statements as test constructs in `<tests_dir>/tests.py`. A supported loop statement MUST be reported as a loop test that passes when its body iterates at least once and fails when the loop iterates zero times or cannot be evaluated. Assertions inside executed loop bodies MUST be discovered as per-iteration tests and MUST obey the single-entrypoint-call traceability rule.

#### Scenario: For-in loop reports loop and assertion tests
- **WHEN** `tests.py` contains `cases = [((1, 2), 3), ((2, 3), 5)]` followed by `for args, exp in cases:` with `assert add(*args) == exp` in the loop body
- **THEN** discovery includes a passing loop test for the `for` statement and one assertion test for each executed iteration

#### Scenario: Zero-iteration loop fails without body assertions
- **WHEN** `tests.py` contains `for x in []:` with `assert add(x, x) == 0` in the loop body
- **THEN** `test` prints exactly `{"status":"fail","passed":[],"failed":["tests.py:1"]}` as one stdout line and exits with code 1

#### Scenario: Enumerate loop is supported
- **WHEN** `tests.py` contains `cases = [(1, 2, 3), (4, 5, 9)]` followed by `for _, (a, b, exp) in enumerate(cases):` with `assert add(a, b) == exp` in the loop body
- **THEN** discovery includes a passing loop test and one assertion test for each enumerated case

#### Scenario: Index-based for loop is supported
- **WHEN** `tests.py` contains `cases = [(1, 2, 3), (4, 5, 9)]` followed by `for i in range(len(cases)):` and the body assigns `a, b, exp = cases[i]` before `assert add(a, b) == exp`
- **THEN** discovery includes a passing loop test and one assertion test for each index in the range

#### Scenario: While loop is supported
- **WHEN** `tests.py` contains a finite index-controlled `while` loop over a supported `cases` value and the body asserts the configured entrypoint result
- **THEN** discovery includes a passing loop test and one assertion test for each executed loop iteration

#### Scenario: Nested loops report each loop level
- **WHEN** `tests.py` contains an outer supported loop and an inner supported loop with an assertion in the inner loop body
- **THEN** discovery includes a loop test for the outer loop, a loop test for each executed inner loop instance, and assertion tests for each executed inner iteration

#### Scenario: Multi-call assertion inside nested loops is rejected
- **WHEN** `tests.py` contains nested loops with `assert add(a, b) == add(b, a)` in the inner loop body
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

## MODIFIED Requirements

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from `<tests_dir>/tests.py`. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace.

#### Scenario: Assertions inside functions are discovered
- **WHEN** `tests.py` contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** `tests.py` contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** `tests.py` contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** `tests.py` contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** `tests.py` contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** `tests.py` contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** `tests.py` contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** `tests.py` imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Discovery fails
- **WHEN** `tests.py` is missing, cannot be parsed, or contains unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST be based on the 1-based source line where the test originates. Non-loop tests MUST use the format `tests.py:<line>`. If multiple non-loop tests originate from the same source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `tests.py:<line>:<index>` for a single loop and `tests.py:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source line and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single test on a line
- **WHEN** one test originates from line 12 of `tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `tests.py`
- **THEN** their test IDs are `tests.py:12#0`, `tests.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `tests.py`
- **THEN** the loop test ID is `tests.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop executes two iterations and an assertion in its body originates from line 3 of `tests.py`
- **THEN** the assertion test IDs are `tests.py:3:0` and `tests.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `tests.py:3:0` and the assertion test ID is `tests.py:4:0:1`

### Requirement: Coverage and Execution Outcomes
If tests are discoverable, every discovered test ID MUST appear exactly once in either `passed` or `failed`. Loop statement tests MUST be reported independently from loop-body assertion tests. Assertions inside loop bodies MUST be discovered and reported only for iterations that execute. Tests not executed for any reason after successful discovery MUST be listed in `failed`. If test discovery fails, the output MUST be exactly `{"status":"error","passed":[],"failed":[]}`.

#### Scenario: Every discovered test is reported
- **WHEN** discovery succeeds and three tests are discovered
- **THEN** each of the three test IDs appears exactly once across the `passed` and `failed` arrays

#### Scenario: A discovered test is not executed
- **WHEN** discovery succeeds but a discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Zero-iteration loop body assertions are not reported
- **WHEN** a supported loop statement executes zero iterations and its body contains an assertion
- **THEN** the loop statement test ID appears in `failed` and no assertion test ID from that loop body appears in `passed` or `failed`

#### Scenario: Discovery failure has empty results
- **WHEN** discovery fails before tests can be enumerated
- **THEN** `test` reports `status` as `error` with empty `passed` and `failed` arrays
