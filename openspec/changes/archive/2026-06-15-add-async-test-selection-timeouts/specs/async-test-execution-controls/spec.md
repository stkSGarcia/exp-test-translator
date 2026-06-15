## ADDED Requirements

> Extends: `babel-code-goat-cli/support-mutation-directory-discovery`
> Extends: `babel-code-goat-cli/support-single-call-traceability`
> Extends: `babel-code-goat-cli/support-rich-test-comparisons`

### Requirement: Async Entrypoint Completion
The harness SHALL run each target-language entrypoint invocation to completion before evaluating the test result. If an invocation uses async/await semantics, promises, futures, coroutines, tasks, or the target-language equivalent, the harness MUST await or drive that asynchronous result until it completes or times out.

#### Scenario: async entrypoint resolves before assertion
- **GIVEN** a discovered test invokes an entrypoint that returns an asynchronous result
- **WHEN** the `test` command runs that test
- **THEN** the harness waits for the asynchronous result to complete before evaluating pass or failure

### Requirement: Test Discovery Listing
The `test` command SHALL accept `--list-tests`. When discovery succeeds, the command MUST return `status="pass"`, put every discovered test ID in `passed`, and return `failed=[]` without executing any test entrypoint. Discovered IDs MUST use the existing path-based test ID contract (adapts `babel-code-goat-cli/support-mutation-directory-discovery/path-based-test-ids`).

#### Scenario: list tests reports discovered IDs
- **GIVEN** test discovery finds `tests.py:10` and `tests.py:14`
- **WHEN** the user runs `test --list-tests`
- **THEN** the result status is `pass`
- **AND** `passed` contains only `tests.py:10` and `tests.py:14`
- **AND** `failed` is empty

### Requirement: Selected Test Execution
The `test` command SHALL accept `--run <test_id>`. When a discovered test ID is selected, the command MUST execute only that test and MUST include only the selected ID in `passed` or `failed` (adapts `babel-code-goat-cli/support-mutation-directory-discovery/path-based-test-ids`).

#### Scenario: run selected test only
- **GIVEN** test discovery finds `tests.py:10` and `tests.py:14`
- **WHEN** the user runs `test --run tests.py:14`
- **THEN** only `tests.py:14` appears in the combined `passed` and `failed` results
- **AND** `tests.py:10` is not executed

### Requirement: Per-Test Timeout
The `test` command SHALL accept `--timeout-ms <int>` as a per-test execution timeout. If a selected or scheduled test exceeds that timeout, the command MUST stop waiting for that test and report its test ID in `failed`.

#### Scenario: per-test timeout fails running test
- **GIVEN** a discovered test does not complete within the configured per-test timeout
- **WHEN** the user runs `test --timeout-ms 100`
- **THEN** that test ID appears in `failed`
- **AND** the command does not report that test ID in `passed`

### Requirement: Total Timeout Coverage
The `test` command SHALL accept `--total-timeout-ms <int>` as a whole-run timeout. If the total timeout prevents any discovered, scheduled, or selected tests from executing to completion, the command MUST report each timed-out or not-executed affected test ID in `failed` to preserve coverage accounting.

#### Scenario: total timeout marks not executed tests failed
- **GIVEN** test discovery finds `tests.py:10`, `tests.py:14`, and `tests.py:18`
- **AND** the total timeout expires after `tests.py:10` completes
- **WHEN** the `test` command reports results
- **THEN** each timed-out or not-executed test ID appears in `failed`
- **AND** only tests completed successfully before the timeout may appear in `passed`
