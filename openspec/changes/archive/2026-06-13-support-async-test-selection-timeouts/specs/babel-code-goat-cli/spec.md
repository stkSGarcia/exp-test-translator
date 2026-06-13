## ADDED Requirements

### Requirement: Async Entrypoint Execution
The system SHALL run async-style entrypoint invocations to completion before evaluating assertions, exception expectations, mutation assertions, stdout expectations, or stderr expectations. This behavior MUST apply to `python`, `javascript`, `typescript`, `cpp`, and `rust` targets without changing synchronous entrypoint behavior.

#### Scenario: Python awaitable result is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang python` runs a discovered test whose entrypoint invocation returns an awaitable value
- **THEN** the harness awaits the value to completion before evaluating the discovered test result

#### Scenario: JavaScript promise result is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang javascript` runs a discovered test whose entrypoint invocation returns a Promise
- **THEN** the harness awaits the Promise to completion before evaluating the discovered test result

#### Scenario: TypeScript promise result is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang typescript` runs a discovered test whose entrypoint invocation returns a Promise
- **THEN** the harness awaits the Promise to completion before evaluating the discovered test result

#### Scenario: C++ future-like result is completed
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs a discovered test whose entrypoint invocation returns a standard future-like result
- **THEN** the harness completes the future-like result before evaluating the discovered test result

#### Scenario: Rust future result is completed
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs a discovered test whose entrypoint invocation returns a Future
- **THEN** the harness completes the Future before evaluating the discovered test result

### Requirement: Test Listing and Selection
The `test` command SHALL accept `--list-tests` and `--run <test_id>` flags. Listing tests MUST perform successful tester metadata validation and test discovery, MUST NOT execute solution entrypoints, and MUST print the standard JSON result shape with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, and `failed` set to an empty array. Selecting a test MUST execute only the selected discovered test and MUST include only that test ID in `passed` or `failed`.

#### Scenario: List tests reports discovered IDs
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked and discovery succeeds with test IDs `tests.py:1` and `tests.py:2`
- **THEN** the command prints exactly `{"status":"pass","passed":["tests.py:1","tests.py:2"],"failed":[]}` as one stdout line and exits with code 0

#### Scenario: List tests does not execute solution code
- **WHEN** `test <solution_path> <tests_dir> --lang javascript --list-tests` is invoked with a solution whose entrypoint would fail if called and discovery succeeds
- **THEN** the command reports discovered test IDs as passing without invoking the entrypoint

#### Scenario: Run selected test reports only that ID
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2` is invoked and discovery includes `tests.py:1` and `tests.py:2`
- **THEN** only `tests.py:2` appears in `passed` or `failed`

#### Scenario: Run unknown test ID errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --run missing.py:1` is invoked and discovery succeeds without that ID
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test Execution Timeouts
The `test` command SHALL accept `--timeout-ms <int>` and `--total-timeout-ms <int>` flags. Timeout values MUST be positive integers in milliseconds. A per-test timeout MUST fail the test whose execution exceeds the limit. A total timeout MUST fail the timed-out test and every discovered selected test that was not executed before the limit. Timeout failures after successful discovery MUST use `status` set to `fail`, include timed-out or not-executed test IDs in `failed`, and preserve the standard JSON output shape.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms 50` runs a discovered test whose entrypoint does not complete within 50 milliseconds
- **THEN** that test ID appears in `failed`, `status` is `fail`, and the command exits with code 1

#### Scenario: Total timeout fails remaining tests
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 50` runs multiple discovered tests and the total timeout expires before all selected tests execute
- **THEN** the timed-out test and every not-executed selected test ID appear in `failed`

#### Scenario: Timeout flags support selected tests
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2 --timeout-ms 50 --total-timeout-ms 100` is invoked and discovery includes additional test IDs
- **THEN** timeout accounting applies only to `tests.py:2`, and only `tests.py:2` appears in `passed` or `failed`

#### Scenario: Invalid timeout value errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms 0` or `--total-timeout-ms not-an-int` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
