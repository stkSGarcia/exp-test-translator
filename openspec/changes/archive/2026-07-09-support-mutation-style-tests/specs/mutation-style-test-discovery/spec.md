## ADDED Requirements

> Extends: babel-code-goat-cli/support-single-call-test-traceability
> Extends: babel-code-goat-cli/support-loop-construct-tests

### Requirement: Mutation-style test discovery (adapts babel-code-goat-cli/support-single-call-test-traceability/single-call-traceable-assertions)
The system SHALL discover mutation-style tests only when the configured entrypoint call is a statement or assignment immediately followed by one or more assertions with no intervening entrypoint call.

Each assertion in the mutation-style group MUST reference at least one variable passed to the mutation call or directly assigned from the mutation call. The system MUST keep each discovered mutation-style test traceable to the mutation call that produced the asserted state.

#### Scenario: Statement mutation followed by assert
- **GIVEN** a Python test file assigns `a = [2, 0, 2, 1, 1, 0]`
- **WHEN** the next statement calls `sort_colors(a)` and the following statement asserts `a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery emits a mutation-style test traceable to the `sort_colors(a)` call

#### Scenario: Assignment mutation followed by assert
- **GIVEN** a Python test file calls the configured entrypoint in an assignment such as `result = mutate(a)`
- **WHEN** one or more immediately following assertions reference `result`
- **THEN** discovery emits mutation-style tests traceable to that assignment call

#### Scenario: Multiple assertions over mutated value
- **GIVEN** a supported mutation-style call passes variable `a`
- **WHEN** two immediately following assertions both reference `a`
- **THEN** discovery emits tests for the assertions without requiring a second entrypoint call

### Requirement: Unsupported mutation pattern errors
The system SHALL report a discovery error when a file uses mutation-style patterns outside the supported constraints.

Unsupported mutation-style patterns MUST include an entrypoint call followed by no assertion, an entrypoint call separated from its assertions by an unrelated statement, a follow-up assertion that references neither a variable passed to nor directly assigned from the mutation call, and a mutation-style group interrupted by another entrypoint call.

#### Scenario: Entrypoint call without following assert
- **WHEN** a Python test file contains an entrypoint call as a statement or assignment and no immediately following assertion
- **THEN** discovery reports an error

#### Scenario: Unrelated statement between mutation and assert
- **WHEN** an unrelated statement appears between a mutation-style entrypoint call and an assertion
- **THEN** discovery reports an error

#### Scenario: Assertion does not reference mutated value
- **WHEN** an assertion immediately follows a mutation-style entrypoint call but references no variable passed to or assigned from that call
- **THEN** discovery reports an error

