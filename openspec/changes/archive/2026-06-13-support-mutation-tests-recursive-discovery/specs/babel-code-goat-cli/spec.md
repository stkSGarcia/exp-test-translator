## MODIFIED Requirements

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests recursively from `.py` files under `<tests_dir>`. The system MUST NOT require `<tests_dir>/tests.py` when other Python test files contain discoverable tests. Non-`.py` files under `<tests_dir>` whose filenames match the test-like patterns `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}` MUST cause discovery to fail. If recursive discovery finds no tests under `<tests_dir>`, discovery MUST fail. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, constrained mutation-style entrypoint calls, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint, except that mutation-style assertions MUST be traceable to the immediately preceding mutation-style entrypoint call. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. Mutation-style tests are valid only when an entrypoint call is used as a statement or single-target assignment and is immediately followed by one or more assertions with no entrypoint call. Each mutation-style assertion MUST reference at least one variable passed to the mutation call or a variable directly assigned from the mutation call.

#### Scenario: Recursive Python files are discovered
- **WHEN** `<tests_dir>/nested/test_sort.py` contains `assert ENTRYPOINT([2, 1]) == [1, 2]`
- **THEN** discovery includes that assertion as a test

#### Scenario: Root tests file is not required
- **WHEN** `<tests_dir>/tests.py` is absent and `<tests_dir>/subdir/cases.py` contains `assert ENTRYPOINT(1) == 2`
- **THEN** discovery includes the assertion from `subdir/cases.py`

#### Scenario: Test-like non-Python file is rejected
- **WHEN** `<tests_dir>` contains `test_cases.txt`, `value_test.json`, `tests.yaml`, or `value_tests.md`
- **THEN** discovery fails because test-like files must be Python files

#### Scenario: No recursive tests discovered
- **WHEN** `<tests_dir>` contains no discoverable tests in any `.py` file
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Assertions inside functions are discovered
- **WHEN** a discovered Python file contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** a discovered Python file contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** a discovered Python file contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** a discovered Python file contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Mutation statement followed by assertions is discovered
- **WHEN** a discovered Python file contains `a = [2, 0, 2, 1, 1, 0]` followed by `ENTRYPOINT(a)` and immediately followed by `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the adjacent assertion as a mutation-style test that invokes the entrypoint once before evaluating the assertion

#### Scenario: Mutation assignment followed by assertions is discovered
- **WHEN** a discovered Python file contains `result = ENTRYPOINT([2, 1])` immediately followed by `assert result == [1, 2]`
- **THEN** discovery includes the adjacent assertion as a mutation-style test that invokes the entrypoint once before evaluating the assertion

#### Scenario: Multiple adjacent mutation assertions are discovered
- **WHEN** a mutation-style entrypoint statement is immediately followed by two assertions that both reference a variable passed to that entrypoint call
- **THEN** discovery includes each adjacent assertion as a separate mutation-style test associated with the same mutation call

#### Scenario: Non-adjacent mutation assertion is rejected
- **WHEN** a discovered Python file contains an entrypoint statement followed by a non-assert statement before an assertion inspects a passed variable
- **THEN** discovery fails because mutation-style assertions must immediately follow the mutation call

#### Scenario: Mutation assertion without mutated variable reference is rejected
- **WHEN** a mutation-style entrypoint call is followed by `assert expected == [0, 1, 2]` and the assertion references no variable passed to the mutation call or directly assigned from it
- **THEN** discovery fails

#### Scenario: Mutation assertion with entrypoint call is rejected
- **WHEN** a mutation-style entrypoint call is followed by `assert ENTRYPOINT(a) == a`
- **THEN** discovery fails because mutation-style assertions must not contain an entrypoint call

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** a discovered Python file contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** a discovered Python file contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** a discovered Python file contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** a discovered Python file contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** a discovered Python file imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Discovery fails
- **WHEN** a candidate Python test file cannot be parsed or contains unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Loop-Based Test Parameterization
The system SHALL support loop statements as test constructs in discovered Python test files under `<tests_dir>`. A supported loop statement MUST be reported as a loop test that passes when its body iterates at least once and fails when the loop iterates zero times or cannot be evaluated. Assertions inside executed loop bodies MUST be discovered as per-iteration tests and MUST obey the single-entrypoint-call traceability rule.

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

### Requirement: Test IDs
Each discovered test ID MUST be based on the Python file path relative to `<tests_dir>` using forward slashes, followed by the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative-path>:<line>`. If multiple non-loop tests originate from the same source line in the same file, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source file, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single root test on a line
- **WHEN** one test originates from line 12 of `tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single nested test on a line
- **WHEN** one test originates from line 5 of `subdir/tests.py`
- **THEN** its test ID is `subdir/tests.py:5`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 10 of `nested/test_foo.py`
- **THEN** their test IDs are `nested/test_foo.py:10#0`, `nested/test_foo.py:10#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `cases/test_math.py`
- **THEN** the loop test ID is `cases/test_math.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `cases/test_math.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `cases/test_math.py:3:0` and `cases/test_math.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop in `nested/test_grid.py` at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `nested/test_grid.py:3:0` and the assertion test ID is `nested/test_grid.py:4:0:1`
