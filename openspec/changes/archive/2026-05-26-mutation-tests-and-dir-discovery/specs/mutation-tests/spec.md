## ADDED Requirements

### Requirement: Mutation-style call statement is a test construct
The parser SHALL recognise an entrypoint call used as an expression statement (not inside an `assert`) as a mutation test construct when it is immediately followed by one or more `assert` statements that each reference at least one variable passed to that call.

#### Scenario: Statement mutation call generates test case
- **WHEN** `tests.py` contains `sort_colors(a)` as a statement followed immediately by `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** the generated tester contains a test case that calls the entrypoint with the initial value of `a`, then asserts that `a` equals `[0, 0, 1, 1, 2, 2]` after the call

#### Scenario: Statement mutation — multiple asserts
- **WHEN** `tests.py` contains `fn(a, b)` as a statement followed immediately by `assert a == expected_a` and `assert b == expected_b`
- **THEN** the generated tester contains one test case per assertion, each checking the respective argument after the call

#### Scenario: Statement mutation — non-assertion statement breaks the group
- **WHEN** `tests.py` contains `fn(a)` followed by a non-assert statement and then `assert a == expected`
- **THEN** the assertion after the non-assert statement is NOT part of the mutation group for `fn(a)`

### Requirement: Mutation-style assignment is a test construct
The parser SHALL recognise an entrypoint call used as the right-hand side of an assignment statement as a mutation test construct when the immediately following `assert` statements each reference either the assigned variable or a variable passed to the call.

#### Scenario: Assignment mutation — assert checks return value
- **WHEN** `tests.py` contains `result = fn(x)` followed immediately by `assert result == expected`
- **THEN** the generated tester contains a test case that calls the entrypoint with `x` and asserts the return value equals `expected`

#### Scenario: Assignment mutation — assert checks mutated arg
- **WHEN** `tests.py` contains `result = fn(a)` followed immediately by `assert a == expected_a`
- **THEN** the generated tester contains a test case that calls the entrypoint with the initial value of `a` and asserts `a` equals `expected_a` after the call

### Requirement: Mutation assertions must reference mutation variables
Every `assert` immediately following a mutation call SHALL reference at least one variable passed to the call or directly assigned from it. An `assert` that does not reference any such variable is a discovery error.

#### Scenario: Assertion referencing unrelated variable is a discovery error
- **WHEN** `tests.py` contains `fn(a)` followed by `assert unrelated == 1` (where `unrelated` is not a variable passed to `fn`)
- **THEN** `generate` exits non-zero with an error message and no tester file is created

#### Scenario: Valid mutation assertion passes constraint check
- **WHEN** `tests.py` contains `fn(a)` followed by `assert a == [1, 2, 3]` (where `a` was passed to `fn`)
- **THEN** the constraint check passes and the test case is generated

### Requirement: Mutation test execution checks post-call argument state
When the tester executes a mutation test case that was produced from a statement mutation call, it SHALL:
1. Call the entrypoint with the initial argument values
2. After the call completes, compare the argument at the tracked index to the expected value
3. Not compare the return value of the call

#### Scenario: Mutation test passes when argument is correctly mutated
- **WHEN** `sort_colors` mutates its list argument in-place and the test asserts the post-call state
- **THEN** the test case is reported as passed when the argument equals the expected value after the call

#### Scenario: Mutation test fails when argument is not correctly mutated
- **WHEN** `sort_colors` does not mutate its argument to the expected state
- **THEN** the test case is reported as failed

### Requirement: Mutation test IDs follow the same path-based scheme
Mutation test cases SHALL have IDs based on the line number of the `assert` statement (not the mutation call statement), following the same `<relpath>:<lineno>` format as other test cases.

#### Scenario: Mutation assert ID uses assert line number
- **WHEN** `sort_colors(a)` is on line 2 and `assert a == [...]` is on line 3
- **THEN** the test case ID is `tests.py:3`
