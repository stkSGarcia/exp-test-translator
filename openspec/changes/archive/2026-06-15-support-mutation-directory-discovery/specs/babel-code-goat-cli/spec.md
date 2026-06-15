## ADDED Requirements

> Extends: babel-code-goat-cli/support-single-call-traceability

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests when an entrypoint call is a standalone statement or is directly assigned to one or more target variables, is immediately followed by one or more `assert` statements, and each such assertion references at least one variable passed to the mutation call or directly assigned from it. Mutation-style assertions MUST obey the supported assertion expression and value rules that apply to discovered assertions. Mutation-style patterns outside these constraints MUST cause discovery to fail. (adapts babel-code-goat-cli/support-single-call-traceability/test-discovery-source-and-allowed-constructs)

#### Scenario: Mutated argument assertion is discovered
- **WHEN** a Python test file contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` and then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assertion as one mutation-style test traceable to the `sort_colors(a)` entrypoint invocation

#### Scenario: Assigned result assertion is discovered
- **WHEN** a Python test file contains `result = normalize(items)` immediately followed by `assert result == expected`
- **THEN** discovery includes the assertion as one mutation-style test traceable to the assignment entrypoint invocation

#### Scenario: Multiple dependent assertions are discovered
- **WHEN** a Python test file contains a valid mutation-style entrypoint call immediately followed by multiple `assert` statements and each assertion references a mutated argument or assigned target
- **THEN** discovery includes each assertion as a separate mutation-style test associated with the same entrypoint invocation

#### Scenario: Non-immediate mutation assertion is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call followed by any non-assert executable statement before a dependent assertion
- **THEN** discovery fails because the mutation-style assertions are not immediately adjacent to the entrypoint invocation

#### Scenario: Independent assertion is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call immediately followed by an assertion that does not reference any variable passed to the call or assigned from the call
- **THEN** discovery fails because the assertion is not traceable to mutated or assigned state

## MODIFIED Requirements

> Extends: babel-code-goat-cli/add-loop-as-test-support

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from all `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, supported mutation-style tests, allowed assertions, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. Non-`.py` files under `<tests_dir>` with test-like names MUST cause discovery to fail. Discovery MUST fail when recursive discovery finds no tests. Test-like names are `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, and `*_tests.<ext>` for any non-`.py` extension. (adapts babel-code-goat-cli/add-loop-as-test-support/test-discovery-source-and-allowed-constructs)

#### Scenario: Assertions inside functions are discovered
- **WHEN** any `.py` file under `<tests_dir>` contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** any `.py` file under `<tests_dir>` contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** any `.py` file under `<tests_dir>` contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** any `.py` file under `<tests_dir>` contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Nested Python files are discovered
- **WHEN** tests exist only in nested Python files below `<tests_dir>`, such as `<tests_dir>/cases/sorting_tests.py`
- **THEN** recursive discovery includes those tests without requiring `<tests_dir>/tests.py` to exist

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** any `.py` file under `<tests_dir>` contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** any `.py` file under `<tests_dir>` contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** any `.py` file under `<tests_dir>` contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** any `.py` file under `<tests_dir>` contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** any `.py` file under `<tests_dir>` imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Test-like non-Python file is rejected
- **WHEN** `<tests_dir>` contains a non-`.py` file whose basename matches `test*`, `*_test`, `tests`, or `*_tests`, such as `test_cases.txt` or `nested/api_tests.md`
- **THEN** discovery fails

#### Scenario: No tests discovered is rejected
- **WHEN** recursive discovery finds no supported tests in any `.py` file under `<tests_dir>`
- **THEN** discovery fails

#### Scenario: Discovery fails
- **WHEN** any candidate Python test file cannot be parsed or contains unsupported test constructs, a test-like non-Python file is present, or recursive discovery finds no tests
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test IDs
Each discovered test ID MUST start with the test file path relative to `<tests_dir>` using forward slashes, followed by `:<line>` for the 1-based source line where the test originates. Multiple non-loop tests from the same source line in the same file MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source file, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes. (adapts babel-code-goat-cli/add-loop-as-test-support/test-ids)

#### Scenario: Single test on a line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Nested file test ID
- **WHEN** one test originates from line 5 of `<tests_dir>/subdir/test_sort.py`
- **THEN** its test ID is `subdir/test_sort.py:5`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/nested/test_math.py`
- **THEN** their test IDs are `nested/test_math.py:12#0`, `nested/test_math.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/cases/tests.py`
- **THEN** the loop test ID is `cases/tests.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop executes two iterations and an assertion in its body originates from line 3 of `<tests_dir>/cases/tests.py`
- **THEN** the assertion test IDs are `cases/tests.py:3:0` and `cases/tests.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1 in `<tests_dir>/cases/nested_tests.py`
- **THEN** the inner loop test ID is `cases/nested_tests.py:3:0` and the assertion test ID is `cases/nested_tests.py:4:0:1`
