## ADDED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat
> Extends: python-test-discovery/add-mutation-style-test-discovery
> Extends: compiled-targets/add-cpp-rust-targets

### Requirement: Async target completion
The test harness SHALL run async/await-style entrypoint invocations to completion in every supported target language before evaluating the test result, unless the invocation exceeds an applicable timeout.

#### Scenario: Awaited result is reported after completion
- **GIVEN** a discovered test whose target-language entrypoint invocation performs asynchronous work before returning
- **WHEN** the `test` command executes the generated runner for any supported `--lang`
- **THEN** the harness waits for the async invocation to complete before placing the test ID in `passed` or `failed`

#### Scenario: Async failure is reported as failed
- **GIVEN** a discovered test whose async entrypoint invocation rejects, raises, or otherwise fails before producing the expected value
- **WHEN** the `test` command executes the generated runner
- **THEN** the test ID appears in `failed`

### Requirement: Test discovery listing (adapts python-test-discovery/add-mutation-style-test-discovery/path-based-test-ids-adapts-babel-code-goat-cli-support-loop-construct-tests-test-ids)
The `test` command SHALL accept `--list-tests` and, when discovery succeeds, output `status="pass"`, `passed` containing every discovered test ID, and `failed=[]` without executing target-language test bodies.

#### Scenario: Successful discovery list
- **GIVEN** the configured tests directory contains discoverable tests
- **WHEN** the user runs `test` with `--list-tests`
- **THEN** the output has `status="pass"`
- **AND** `passed` contains all discovered test IDs
- **AND** `failed` is empty

#### Scenario: Listing uses discovered IDs
- **GIVEN** discovery assigns path-based or parameterized test IDs
- **WHEN** the user runs `test` with `--list-tests`
- **THEN** each listed ID matches the ID that would be used by normal test execution

### Requirement: Selected test execution (adapts python-test-discovery/add-mutation-style-test-discovery/path-based-test-ids-adapts-babel-code-goat-cli-support-loop-construct-tests-test-ids)
The `test` command SHALL accept `--run <test_id>` and execute only the discovered test matching `<test_id>`, with no other discovered test ID appearing in `passed` or `failed`.

#### Scenario: Single selected test passes
- **GIVEN** discovery finds multiple tests and one test ID matches the `--run` value
- **WHEN** the selected test passes
- **THEN** only the selected test ID appears in `passed`
- **AND** `failed` is empty

#### Scenario: Single selected test fails
- **GIVEN** discovery finds multiple tests and one test ID matches the `--run` value
- **WHEN** the selected test fails
- **THEN** only the selected test ID appears in `failed`
- **AND** `passed` is empty

### Requirement: Timeout result accounting (adapts babel-code-goat-cli/add-babel-code-goat/result-coverage-accounting)
The `test` command SHALL accept `--timeout-ms <int>` for per-test timeout enforcement and `--total-timeout-ms <int>` for whole-run timeout enforcement. Timed-out tests and tests not executed because a total timeout is reached MUST appear in `failed`.

#### Scenario: Per-test timeout fails selected test
- **GIVEN** a discovered test exceeds the `--timeout-ms` value
- **WHEN** the `test` command reports results
- **THEN** that test ID appears in `failed`

#### Scenario: Total timeout fails remaining tests
- **GIVEN** discovery succeeds for multiple tests
- **WHEN** `--total-timeout-ms` is reached before every discovered test executes
- **THEN** each timed-out or not-executed discovered test ID appears in `failed`

#### Scenario: Completed tests remain covered once
- **GIVEN** discovery succeeds and a timeout option is provided
- **WHEN** the run completes or stops due to timeout
- **THEN** every in-scope discovered test ID appears exactly once across `passed` and `failed`
