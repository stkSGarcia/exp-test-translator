## MODIFIED Requirements

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed assertion forms, and supported raise expectation blocks as non-comment code in `tests.py`. Each allowed assertion, each supported raise expectation block, and each supported loop statement MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

#### Scenario: Equality assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...) == expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Inequality assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...) != expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Truthy assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Falsy assertion is discovered
- **WHEN** `tests.py` contains `assert not ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Raise-any block is discovered
- **WHEN** `tests.py` contains a `try` block that calls the entrypoint, then asserts `False`, and catches `Exception` with `pass`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed raise block is discovered
- **WHEN** `tests.py` contains a `try` block that calls the entrypoint, then asserts `False`, and catches a specific exception type such as `ValueError`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception matching that type

#### Scenario: Typed raise block with substring message check is discovered
- **WHEN** `tests.py` contains a typed exception handler that asserts a string literal is contained in `str(e)`
- **THEN** the block is discovered as one test that also requires the raised exception message to contain that substring

#### Scenario: Typed raise block with regex message check is discovered
- **WHEN** `tests.py` contains a typed exception handler that asserts `re.search(<pattern>, str(e))`
- **THEN** the block is discovered as one test that also requires the raised exception message to match that regex pattern

#### Scenario: Math isclose assertion is discovered
- **WHEN** `tests.py` contains `assert math.isclose(ENTRYPOINT(args...), expected, abs_tol=abs_tol, rel_tol=rel_tol)`
- **THEN** the assertion is discovered as one test with per-assert absolute and relative tolerance metadata

#### Scenario: Absolute difference tolerance assertion is discovered
- **WHEN** `tests.py` contains `assert abs(ENTRYPOINT(args...) - expected) < tol` or `assert abs(ENTRYPOINT(args...) - expected) <= tol`
- **THEN** the assertion is discovered as one test with a per-assert absolute tolerance and strictness metadata

#### Scenario: Literal assignment for parameterization is accepted
- **WHEN** `tests.py` contains a simple assignment such as `cases = [((1, 2), 3)]` used by a supported loop
- **THEN** discovery accepts the assignment as parameterization data and does not report the assignment itself as a test

#### Scenario: For loop is discovered
- **WHEN** `tests.py` contains a supported `for ... in ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: While loop is discovered
- **WHEN** `tests.py` contains a supported `while ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: Unsupported code fails discovery
- **WHEN** `tests.py` contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Test IDs
The system SHALL assign each discovered non-loop test a line-based ID in the form `tests.py:<line>` using 1-based source lines. If multiple non-loop tests originate from the same line outside loop expansion, the system MUST suffix them as `tests.py:<line>#0`, `tests.py:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `tests.py:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `tests.py:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line.

#### Scenario: Single test ID uses line
- **WHEN** one non-loop test originates on line 12
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 outside loop expansion
- **THEN** their IDs are `tests.py:12#0` and `tests.py:12#1`

#### Scenario: Loop statement ID uses loop line
- **WHEN** a loop statement originates on line 2
- **THEN** the loop test ID is `tests.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 executes for two loop iterations
- **THEN** the assertion test IDs are `tests.py:3:0` and `tests.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5
- **THEN** the assertion test IDs are `tests.py:5:0`, `tests.py:5:1`, `tests.py:5:2`, and `tests.py:5:3`

## ADDED Requirements

### Requirement: Loop statement tests
The system SHALL treat each supported `for` and `while` loop statement as a test. A loop test MUST pass when the loop body executes at least once. A loop test MUST fail when the loop iterates zero times or cannot be evaluated safely. A failing loop test MUST use normal failing test result semantics: `status` is `fail`, the loop test ID appears in `failed`, and the command exits `1` unless another error condition takes precedence.

#### Scenario: Non-empty for loop passes
- **WHEN** `tests.py` contains `for args, exp in [((1, 2), 3)]:` with a supported loop body
- **THEN** the loop statement test passes because the body executes at least once

#### Scenario: Empty for loop fails
- **WHEN** `tests.py` contains `for x in []:` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Zero range loop fails
- **WHEN** `tests.py` contains `for i in range(0):` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Empty string loop fails
- **WHEN** `tests.py` contains `for ch in "":` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Unsupported loop evaluation fails loop test
- **WHEN** a loop iterable or `while` condition cannot be evaluated using the supported parameterization subset
- **THEN** the loop statement test fails and tests from the body are not reported

### Requirement: Loop parameterization patterns
The system SHALL support common Python iteration patterns for parameterized tests, including direct iteration over supported literal containers or strings, `enumerate(...)`, index-based `range(len(...))`, and `while` loops controlled by supported variables and primitive updates.

#### Scenario: Direct tuple unpacking loop expands assertions
- **WHEN** `tests.py` contains `for a, b in [(1, 2), (3, 4)]:` and a supported assertion in the loop body
- **THEN** the loop test is reported and the body assertion is reported once per iteration using the values from that iteration

#### Scenario: Enumerate loop expands assertions
- **WHEN** `tests.py` contains `for _, (a, b, exp) in enumerate(cases):` and a supported assertion in the loop body
- **THEN** the loop test is reported and the body assertion is reported once per enumerated case

#### Scenario: Index-based range loop expands assertions
- **WHEN** `tests.py` contains `for i in range(len(cases)):` and uses `cases[i]` in a supported assertion
- **THEN** the loop test is reported and the body assertion is reported once per index

#### Scenario: While loop expands assertions
- **WHEN** `tests.py` contains a supported `while i < len(cases):` loop whose body advances `i`
- **THEN** the loop test is reported and the body assertion is reported once per loop iteration

#### Scenario: Nested loop levels are separate loop tests
- **WHEN** `tests.py` contains a supported loop nested inside another supported loop
- **THEN** each loop statement is reported as its own loop test and assertions in the nested body are reported per executed inner iteration

### Requirement: Loop body traceability
The system SHALL apply existing single-call traceability rules to every assertion executed inside a loop body. Each loop body assertion MUST trace to exactly one configured entrypoint invocation after loop variables are resolved. Discovery MUST fail when a loop body assertion contains zero configured entrypoint invocations, more than one configured entrypoint invocation, or an unsupported non-primitive helper call.

#### Scenario: Single-call loop body assertion is discovered
- **WHEN** `tests.py` contains a supported loop whose body contains `assert add(a, b) == exp`
- **THEN** each executed assertion is discovered as a test traceable to exactly one `add(a, b)` invocation

#### Scenario: Multiple entrypoint calls in loop body fail discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert add(a, b) == add(b, a)`
- **THEN** discovery fails

#### Scenario: Zero entrypoint calls in loop body fail discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert exp == 3`
- **THEN** discovery fails

#### Scenario: Unsupported helper call in loop body fails discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert normalize(add(a, b)) == exp`
- **THEN** discovery fails
