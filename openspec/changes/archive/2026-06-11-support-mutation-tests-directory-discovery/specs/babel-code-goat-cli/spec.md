## ADDED Requirements

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests when an entrypoint call appears as a standalone statement or as a single-variable assignment and is immediately followed by one or more assert statements in the same statement body. The mutation call MUST be the entrypoint invocation used by each following mutation assert. Each following mutation assert MUST NOT contain an entrypoint call and MUST reference at least one direct variable passed to the mutation call or the variable directly assigned from the mutation call. If a file uses mutation-style entrypoint calls outside these constraints, discovery MUST fail.

#### Scenario: Standalone mutation call is discovered
- **WHEN** a Python test source contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` followed immediately by `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assert as one test that invokes `sort_colors` with the initial value of `a` and evaluates the assertion against the mutated argument

#### Scenario: Assignment mutation call is discovered
- **WHEN** a Python test source contains `a = [3, 1, 2]` followed by `result = normalize(a)` followed immediately by `assert result == [1, 2, 3]`
- **THEN** discovery includes the assert as one test that invokes `normalize` with the initial value of `a` and evaluates the assertion against the assigned result

#### Scenario: Multiple immediate mutation asserts are discovered
- **WHEN** a Python test source contains an entrypoint mutation call immediately followed by two assert statements, and each assert references a mutation argument variable or the assigned result variable
- **THEN** discovery includes one test for each assert in source order

#### Scenario: Mutation assert cannot call entrypoint
- **WHEN** a Python test source contains `sort_colors(a)` immediately followed by `assert sort_colors(a) is None`
- **THEN** discovery fails because the mutation assert contains an entrypoint call

#### Scenario: Mutation assert must reference mutation variable
- **WHEN** a Python test source contains `sort_colors(a)` immediately followed by `assert expected == [0, 1, 2]`
- **THEN** discovery fails because the assert does not reference a variable passed to or directly assigned from the mutation call

#### Scenario: Mutation call requires immediate assert
- **WHEN** a Python test source contains an entrypoint call statement or assignment that is not immediately followed by at least one assert statement
- **THEN** discovery fails

## MODIFIED Requirements

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from all `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, constrained mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. The system MUST report a discovery error for non-`.py` files under `<tests_dir>` whose stem matches `test*`, `*_test`, `tests`, or `*_tests`, except for generated tester artifacts named `tester.js` or `tester.ts`.

#### Scenario: Assertions inside functions are discovered
- **WHEN** a Python test source under `<tests_dir>` contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Tests in nested Python files are discovered
- **WHEN** `<tests_dir>/nested/test_values.py` contains `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test

#### Scenario: Supported assertion forms are discovered
- **WHEN** a Python test source contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** a Python test source contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** a Python test source contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** a Python test source contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** a Python test source contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** a Python test source contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** a Python test source contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** a Python test source imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Non-Python test-like file is rejected
- **WHEN** `<tests_dir>` contains a non-`.py` file with a filename such as `test_data.json`, `values_test.txt`, `tests.yaml`, or `integration_tests.md`
- **THEN** discovery fails

#### Scenario: Generated non-Python tester file is ignored by discovery
- **WHEN** `<tests_dir>` contains the generated `tester.js` or `tester.ts` file and otherwise contains discoverable Python tests
- **THEN** discovery ignores the generated tester file and succeeds

#### Scenario: No discovered tests is rejected
- **WHEN** recursive discovery under `<tests_dir>` finds no tests
- **THEN** discovery fails

#### Scenario: Discovery fails
- **WHEN** a Python test source cannot be read, cannot be parsed, contains unsupported test constructs, or a non-`.py` test-like file is present under `<tests_dir>`
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST be based on the forward-slash relative source path from `<tests_dir>` followed by the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative-path>:<line>`. If multiple non-loop tests originate from the same source path and source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source path, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single root test on a line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single nested test on a line
- **WHEN** one test originates from line 10 of `<tests_dir>/nested/test_foo.py`
- **THEN** its test ID is `nested/test_foo.py:10`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/tests.py`
- **THEN** their test IDs are `tests.py:12#0`, `tests.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/cases/test_loop.py`
- **THEN** the loop test ID is `cases/test_loop.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/cases/test_loop.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `cases/test_loop.py:3:0` and `cases/test_loop.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop at line 2 of `<tests_dir>/nested/tests.py` executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `nested/tests.py:3:0` and the assertion test ID is `nested/tests.py:4:0:1`
