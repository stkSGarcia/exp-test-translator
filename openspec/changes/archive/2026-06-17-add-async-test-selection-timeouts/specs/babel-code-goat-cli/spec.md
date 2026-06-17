## ADDED Requirements

> Extends: babel-code-goat-cli

### Requirement: Async Entrypoint Completion Across Targets
For every accepted target language, the generated tester and `test` runner SHALL run async or awaitable entrypoint invocations to completion before evaluating the test result. If async completion exceeds an applicable timeout, the affected test MUST fail rather than being reported before the invocation settles.

#### Scenario: Python coroutine entrypoint is awaited
- **GIVEN** a Python solution whose configured entrypoint returns a coroutine
- **WHEN** `test` executes a discovered test for that entrypoint
- **THEN** the runner awaits the coroutine result before deciding whether the test passed or failed

#### Scenario: JavaScript promise entrypoint is awaited
- **GIVEN** a JavaScript solution whose configured entrypoint returns a promise
- **WHEN** `test` executes a discovered test for that entrypoint
- **THEN** the runner awaits the promise result before deciding whether the test passed or failed

#### Scenario: TypeScript promise entrypoint is awaited
- **GIVEN** a TypeScript solution whose configured entrypoint returns a promise
- **WHEN** `test` executes a discovered test for that entrypoint
- **THEN** the runner awaits the promise result before deciding whether the test passed or failed

### Requirement: Test Listing and Selection Flags
The `test` command SHALL accept `--list-tests` and `--run <test_id>` flags. `--list-tests` MUST perform discovery without executing entrypoint invocations, print `status` as `pass` when discovery succeeds, place every discovered test ID in `passed`, and set `failed` to an empty array. `--run <test_id>` MUST execute only the selected discovered test ID, and only that selected ID may appear in `passed` or `failed`.

#### Scenario: List tests reports discovered IDs
- **GIVEN** `tests.py` contains three discoverable tests
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked and discovery succeeds
- **THEN** `test` reports `status` as `pass`, `passed` contains all three discovered test IDs, and `failed` is empty

#### Scenario: List tests preserves discovery errors
- **GIVEN** `tests.py` contains unsupported test constructs
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked
- **THEN** `test` reports `status` as `error` with empty `passed` and `failed` arrays

#### Scenario: Run executes only selected test
- **GIVEN** `tests.py` contains multiple discoverable tests including `tests.py:5`
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:5` is invoked
- **THEN** the runner executes only `tests.py:5` and only `tests.py:5` appears in either `passed` or `failed`

### Requirement: Timeout Failure Coverage
The `test` command SHALL accept `--timeout-ms <int>` as a per-test timeout and `--total-timeout-ms <int>` as a total execution timeout. A test that times out MUST appear in `failed`; a discovered test that is not executed because the total timeout budget is exhausted MUST also appear in `failed` (adapts `babel-code-goat-cli/add-loop-as-test-support/coverage-and-execution-outcomes`).

#### Scenario: Per-test timeout fails affected test
- **GIVEN** a discovered test invokes an entrypoint that does not complete within `--timeout-ms`
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms 50` is invoked
- **THEN** that test ID appears in `failed`

#### Scenario: Total timeout marks remaining discovered tests failed
- **GIVEN** discovery succeeds and three test IDs are discovered
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 50` exhausts the total timeout before all discovered tests execute
- **THEN** every timed-out or not-executed discovered test ID appears in `failed`

#### Scenario: Timeout result preserves coverage rule
- **GIVEN** discovery succeeds and multiple test IDs are discovered
- **WHEN** one test passes and a later test times out
- **THEN** each discovered test ID appears exactly once across `passed` and `failed`
