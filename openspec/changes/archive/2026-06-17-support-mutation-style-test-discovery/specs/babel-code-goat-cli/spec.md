## MODIFIED Requirements

> Extends: babel-code-goat-cli

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests recursively from any `.py` file under `<tests_dir>` and MUST NOT require a root `<tests_dir>/tests.py` file. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion, mutation-style group, or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. Mutation-style groups are valid only when an entrypoint call is a statement or assignment, is immediately followed by one or more assertions with no intervening entrypoint call, and each such assertion references at least one variable passed to the mutation call or directly assigned from it. Non-`.py` files under `<tests_dir>` with test-like names MUST cause discovery to fail. Test-like names are `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, and `*_tests.<ext>` for any extension other than `.py`. If no tests are discovered under `<tests_dir>`, discovery MUST fail. (adapts babel-code-goat-cli/add-babel-code-goat/test-discovery-source-and-allowed-constructs)

#### Scenario: Assertions inside functions are discovered
- **WHEN** any Python file under `<tests_dir>` contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** any Python file under `<tests_dir>` contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** any Python file under `<tests_dir>` contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Recursive Python files are discovered
- **WHEN** `<tests_dir>/nested/test_foo.py` contains `assert ENTRYPOINT(1) == 2`
- **THEN** discovery includes the assertion as a test without requiring `<tests_dir>/tests.py`

#### Scenario: Loop constructs are discovered
- **WHEN** any Python file under `<tests_dir>` contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Mutation-style statement group is discovered
- **WHEN** any Python file under `<tests_dir>` contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` and then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the mutation-style group as one test traceable to the `sort_colors(a)` entrypoint call

#### Scenario: Mutation-style assignment group is discovered
- **WHEN** any Python file under `<tests_dir>` contains `result = normalize(items)` followed immediately by `assert result == expected`
- **THEN** discovery includes the mutation-style group as one test traceable to the `normalize(items)` assignment call

#### Scenario: Mutation-style group may contain multiple related assertions
- **WHEN** any Python file under `<tests_dir>` contains `dedupe(items)` followed immediately by `assert items == [1, 2]` and `assert len(items) == 2`
- **THEN** discovery includes the immediately following assertions in one mutation-style group because each assertion references `items`

#### Scenario: Mutation-style group without related assertion is rejected
- **WHEN** any Python file under `<tests_dir>` contains `sort_colors(a)` followed immediately by `assert other == [0, 1, 2]`
- **THEN** discovery fails because the assertion does not reference a variable passed to or assigned from the mutation call

#### Scenario: Mutation-style group interrupted by another entrypoint call is rejected
- **WHEN** any Python file under `<tests_dir>` contains `mutate(a)` followed by `mutate(b)` before an assertion for `a`
- **THEN** discovery fails because the mutation-style assertion group is not immediately tied to exactly one entrypoint call

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** any Python file under `<tests_dir>` contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** any Python file under `<tests_dir>` contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** any Python file under `<tests_dir>` contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** any Python file under `<tests_dir>` contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** any Python file under `<tests_dir>` imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Non-Python test-like file is rejected
- **WHEN** `<tests_dir>` contains `test_sample.txt`, `case_test.js`, `tests.yaml`, or `more_tests.md`
- **THEN** discovery fails because the test-like file is not a Python file

#### Scenario: No recursive tests discovered
- **WHEN** recursive discovery under `<tests_dir>` finds no supported tests
- **THEN** discovery fails

#### Scenario: Discovery fails
- **WHEN** any candidate Python file under `<tests_dir>` cannot be parsed or contains unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST be based on the 1-based source line where the test originates and MUST prefix that line with the test file path relative to `<tests_dir>` using forward slashes. Non-loop tests and mutation-style groups MUST use the format `<relative/path.py>:<line>`. If multiple non-loop tests or mutation-style groups originate from the same source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative/path.py>:<line>:<index>` for a single loop and `<relative/path.py>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source line and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes. (adapts babel-code-goat-cli/add-loop-as-test-support/test-ids)

#### Scenario: Single test on a line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Nested file test on a line
- **WHEN** one test originates from line 10 of `<tests_dir>/nested/test_foo.py`
- **THEN** its test ID is `nested/test_foo.py:10`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/tests.py`
- **THEN** their test IDs are `tests.py:12#0`, `tests.py:12#1`, and so on in discovery order

#### Scenario: Multiple nested file tests on one line
- **WHEN** multiple tests originate from line 10 of `<tests_dir>/nested/test_foo.py`
- **THEN** their test IDs are `nested/test_foo.py:10#0`, `nested/test_foo.py:10#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/nested/test_foo.py`
- **THEN** the loop test ID is `nested/test_foo.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/nested/test_foo.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `nested/test_foo.py:3:0` and `nested/test_foo.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1 in `<tests_dir>/nested/test_foo.py`
- **THEN** the inner loop test ID is `nested/test_foo.py:3:0` and the assertion test ID is `nested/test_foo.py:4:0:1`

#### Scenario: Mutation-style group test ID
- **WHEN** a mutation-style group starts with an entrypoint statement on line 5 of `<tests_dir>/nested/test_foo.py`
- **THEN** the mutation-style group test ID is `nested/test_foo.py:5`
