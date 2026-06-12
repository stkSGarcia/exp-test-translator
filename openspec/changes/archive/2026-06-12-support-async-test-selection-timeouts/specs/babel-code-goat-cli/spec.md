## ADDED Requirements

### Requirement: Async Entrypoint Execution
The system SHALL run each target-language entrypoint invocation to completion before evaluating result expressions, mutation assertions, stdout/stderr expectations, or exception expectations. Python awaitables, JavaScript and TypeScript promises, C++ standard future-like results, and Rust future results MUST be completed by the generated harness before comparison. If an async invocation does not complete before the applicable timeout, the discovered test ID MUST appear in `failed`.

#### Scenario: Python async entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang python` runs a discovered test against a Python solution whose entrypoint is an `async def` coroutine function
- **THEN** the Python harness awaits the coroutine result before evaluating the test assertion

#### Scenario: JavaScript promise entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang javascript` runs a discovered test against a JavaScript solution whose entrypoint returns a `Promise`
- **THEN** the JavaScript harness awaits the promise result before evaluating the test assertion

#### Scenario: TypeScript promise entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang typescript` runs a discovered test against a TypeScript solution whose entrypoint returns a `Promise`
- **THEN** the TypeScript harness awaits the promise result before evaluating the test assertion

#### Scenario: C++ future entrypoint is completed
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs a discovered test against a C++ solution whose entrypoint returns a standard future-like result
- **THEN** the C++ harness completes the future and evaluates the resolved value for the test assertion

#### Scenario: Rust future entrypoint is completed
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs a discovered test against a Rust solution whose entrypoint returns a future
- **THEN** the Rust harness completes the future and evaluates the resolved value for the test assertion

#### Scenario: Async mutation completes before assertions
- **WHEN** a discovered mutation-style test invokes an async entrypoint and then asserts against a mutated argument or assigned result
- **THEN** the harness waits for the entrypoint invocation to complete before evaluating the mutation assertion

### Requirement: Test Discovery Listing and Selection
The `test` command SHALL accept `--list-tests` and `--run <test_id>` flags. `--list-tests` MUST perform validation and discovery without executing the solution. `--run <test_id>` MUST execute only the discovered test whose ID exactly matches `<test_id>`. Supplying both `--list-tests` and `--run <test_id>` in one invocation MUST be treated as a test command error.

#### Scenario: List tests reports discovered IDs
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked and discovery succeeds
- **THEN** the command prints a single JSON line with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` equal to `[]`, no extra keys, and exits with code 0

#### Scenario: List tests does not execute solution code
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked for a solution that would fail or time out if executed and discovery succeeds
- **THEN** the command reports the discovered IDs as passing discovery without invoking the solution entrypoint

#### Scenario: Run selected passing test
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2` is invoked and the discovered test with ID `tests.py:2` passes
- **THEN** the command prints a single JSON line with `status` set to `pass`, `passed` equal to `["tests.py:2"]`, and `failed` equal to `[]`

#### Scenario: Run selected failing test
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:3` is invoked and the discovered test with ID `tests.py:3` fails
- **THEN** the command prints a single JSON line with `status` set to `fail`, `passed` equal to `[]`, `failed` equal to `["tests.py:3"]`, and exits with code 1

#### Scenario: Unknown selected test ID errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --run missing.py:1` is invoked and no discovered test has ID `missing.py:1`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: List and run flags conflict
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests --run tests.py:1` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test Timeout Controls
The `test` command SHALL accept `--timeout-ms <int>` and `--total-timeout-ms <int>` flags. Timeout values MUST be positive integers. `--timeout-ms` MUST bound each selected executable test attempt. `--total-timeout-ms` MUST bound the full selected execution set after discovery and selection. After discovery succeeds, timed-out tests and selected tests not executed because the total timeout elapsed MUST appear in `failed`.

#### Scenario: Per-test timeout fails the timed-out test
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms 10` runs a discovered test whose entrypoint invocation does not complete within 10 milliseconds
- **THEN** that discovered test ID appears in `failed` and the command exits with code 1

#### Scenario: Total timeout fails not-executed selected tests
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 10` discovers three tests and the total timeout elapses before all three tests are executed
- **THEN** every selected discovered test that was not executed because of the elapsed total timeout appears in `failed`

#### Scenario: Selected timeout output contains only selected ID
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2 --timeout-ms 10` runs the selected test and it times out
- **THEN** the command prints a single JSON line with `status` set to `fail`, `passed` equal to `[]`, and `failed` equal to `["tests.py:2"]`

#### Scenario: Invalid per-test timeout errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Non-positive total timeout errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 0` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
