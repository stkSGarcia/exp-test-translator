## MODIFIED Requirements

> Extends: babel-code-goat-cli/support-single-call-traceability
> Extends: babel-code-goat-cli/add-loop-as-test-support

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The `test` command MUST accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>` as optional flags. The system MUST accept only `python`, `javascript`, and `typescript` as target languages.

#### Scenario: Generate accepts a supported language
- **GIVEN** an existing tests directory and valid entrypoint
- **WHEN** `generate` is invoked with `--lang python`, `--lang javascript`, or `--lang typescript`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **GIVEN** an existing tests directory and valid entrypoint
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, or `tester.ts`

#### Scenario: Test rejects an unsupported language
- **GIVEN** an existing solution path and tests directory
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Test accepts execution-control flags
- **GIVEN** an existing solution path, tests directory, and expected tester file
- **WHEN** `test` is invoked with `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, or `--total-timeout-ms <int>`
- **THEN** the command parses the flags as part of the `test` invocation and applies the requested discovery or execution behavior

### Requirement: Coverage and Execution Outcomes
If tests are discoverable, every discovered test ID in the active execution scope MUST appear exactly once in either `passed` or `failed`. Loop statement tests MUST be reported independently from loop-body assertion tests. Assertions inside loop bodies MUST be discovered and reported only for iterations that execute. Tests not executed for any reason after successful discovery, including timeout exhaustion, MUST be listed in `failed`. If test discovery fails, the output MUST be exactly `{"status":"error","passed":[],"failed":[]}`. (adapts babel-code-goat-cli/add-loop-as-test-support/coverage-and-execution-outcomes)

#### Scenario: Every discovered test is reported
- **GIVEN** discovery succeeds and three tests are discovered
- **WHEN** `test` executes all discovered tests
- **THEN** each of the three test IDs appears exactly once across the `passed` and `failed` arrays

#### Scenario: A discovered test is not executed
- **GIVEN** discovery succeeds
- **WHEN** a discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Zero-iteration loop body assertions are not reported
- **GIVEN** a supported loop statement executes zero iterations and its body contains an assertion
- **WHEN** `test` reports execution results
- **THEN** the loop statement test ID appears in `failed` and no assertion test ID from that loop body appears in `passed` or `failed`

#### Scenario: Discovery failure has empty results
- **GIVEN** discovery fails before tests can be enumerated
- **WHEN** `test` reports the failure
- **THEN** `test` reports `status` as `error` with empty `passed` and `failed` arrays

#### Scenario: Timed-out tests are failed
- **GIVEN** discovery succeeds and one or more tests are in the active execution scope
- **WHEN** a per-test or total timeout prevents a test from completing or starting
- **THEN** each timed-out or not-executed test ID appears in `failed`

## ADDED Requirements

### Requirement: Async Entrypoint Execution
The system SHALL run entrypoint invocations to completion for async tests in every supported target language. Python coroutine results, JavaScript promises, and TypeScript promises MUST be awaited or otherwise resolved before the test assertion, expectation, timeout, and result classification are finalized.

#### Scenario: Python async entrypoint completes
- **GIVEN** `tests.py` contains a discovered test for an async Python entrypoint
- **WHEN** `test <solution_path> <tests_dir> --lang python` runs the generated tester
- **THEN** the coroutine invocation completes before the test is classified as passed or failed

#### Scenario: JavaScript async entrypoint completes
- **GIVEN** `tests.py` contains a discovered test for a JavaScript entrypoint that returns a promise
- **WHEN** `test <solution_path> <tests_dir> --lang javascript` runs the generated tester
- **THEN** the promise settles before the test is classified as passed or failed

#### Scenario: TypeScript async entrypoint completes
- **GIVEN** `tests.py` contains a discovered test for a TypeScript entrypoint that returns a promise
- **WHEN** `test <solution_path> <tests_dir> --lang typescript` runs the generated tester
- **THEN** the promise settles before the test is classified as passed or failed

### Requirement: Test Listing
The `test` command SHALL support `--list-tests` to run discovery without executing entrypoint invocations. When discovery succeeds, `--list-tests` MUST output `status` as `pass`, include all discovered test IDs in `passed`, include an empty `failed` array, and exit with code 0.

#### Scenario: List discovered tests
- **GIVEN** `tests.py` contains discoverable tests
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked
- **THEN** the command outputs `status` as `pass`, `passed` contains all discovered test IDs, `failed` is empty, and no entrypoint invocation is executed

#### Scenario: List tests discovery failure
- **GIVEN** `tests.py` is missing, cannot be parsed, or contains unsupported test constructs
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Selected Test Execution
The `test` command SHALL support `--run <test_id>` to execute only the selected discovered test ID. When selection is requested and discovery succeeds, only the selected test ID MUST appear in `passed` or `failed`.

#### Scenario: Selected passing test
- **GIVEN** discovery succeeds and the selected test ID passes
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run <test_id>` is invoked
- **THEN** only the selected test ID appears in `passed`, `failed` is empty, and the command exits with code 0

#### Scenario: Selected failing test
- **GIVEN** discovery succeeds and the selected test ID fails
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run <test_id>` is invoked
- **THEN** only the selected test ID appears in `failed`, `passed` is empty, and the command exits with code 1

#### Scenario: Selected test is not discovered
- **GIVEN** discovery succeeds and the requested test ID is not among the discovered IDs
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run <test_id>` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test Execution Timeouts
The `test` command SHALL support `--timeout-ms <int>` as a per-test execution timeout and `--total-timeout-ms <int>` as a total timeout for the active execution scope. Timeout values MUST be interpreted as milliseconds. A timed-out test or a discovered test that is not executed because the total timeout has been exhausted MUST appear in `failed`.

#### Scenario: Per-test timeout fails the test
- **GIVEN** discovery succeeds and an active test invocation exceeds `--timeout-ms <int>`
- **WHEN** `test` reports execution results
- **THEN** that test ID appears in `failed` and does not appear in `passed`

#### Scenario: Total timeout fails remaining tests
- **GIVEN** discovery succeeds with multiple active test IDs
- **WHEN** `--total-timeout-ms <int>` is exhausted before all active tests complete
- **THEN** each timed-out or not-executed active test ID appears in `failed`

#### Scenario: Timeout with selected test
- **GIVEN** discovery succeeds and `--run <test_id>` selects one active test
- **WHEN** the selected test exceeds `--timeout-ms <int>` or cannot complete before `--total-timeout-ms <int>`
- **THEN** only the selected test ID appears in `failed`
