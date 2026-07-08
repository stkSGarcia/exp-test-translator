## ADDED Requirements

### Requirement: Single-call traceable assertions
The system SHALL discover supported assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls.

#### Scenario: Entrypoint call on right side is discovered
- **WHEN** `tests.py` contains `assert 3 == ENTRYPOINT(1, 2)`
- **THEN** the assertion is discovered as one test traceable to the single `ENTRYPOINT(1, 2)` invocation

#### Scenario: Multiple entrypoint calls fail discovery
- **WHEN** `tests.py` contains `assert ENTRYPOINT(1) == ENTRYPOINT(2)`
- **THEN** discovery fails

#### Scenario: Unsupported helper call fails discovery
- **WHEN** `tests.py` contains `assert normalize(ENTRYPOINT(1)) == 1`
- **THEN** discovery fails

#### Scenario: Tolerance helper remains traceable
- **WHEN** `tests.py` contains `assert math.isclose(ENTRYPOINT("near"), 1.0, abs_tol=0.01)`
- **THEN** the assertion is discovered as one test with per-assert tolerance metadata traceable to the single entrypoint invocation

### Requirement: Primitive operation assertions
The system SHALL support primitive operations over supported numbers, strings, and containers inside discovered assertion expressions when those expressions contain exactly one configured entrypoint invocation. Primitive operations MUST be evaluated by generated testers as part of the same discovered test and MUST NOT require a second entrypoint invocation.

#### Scenario: Membership assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(1, 2) in [1, 2, 3]`
- **THEN** the assertion is discovered as one test that passes only when the single entrypoint result is a member of the expected container

#### Scenario: Primitive wrapper assertion is discovered
- **WHEN** `tests.py` contains `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`
- **THEN** the assertion is discovered as one test that invokes the entrypoint once and compares the sorted primitive result to the expected list

#### Scenario: Primitive numeric expression is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(2) + 1 == 4`
- **THEN** the assertion is discovered as one test that applies the primitive numeric operation to the single entrypoint result

#### Scenario: Primitive container expression preserves structural comparison
- **WHEN** `tests.py` contains `assert ENTRYPOINT("items")[0] == "first"`
- **THEN** the assertion is discovered as one test that applies the primitive container access to the single entrypoint result before comparison
