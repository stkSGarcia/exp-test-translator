## ADDED Requirements

### Requirement: Async entrypoint completion
The system SHALL run awaitable or async-like entrypoint invocations to completion before evaluating the discovered test outcome for every supported target language. If async completion does not finish before an applicable timeout, the affected test MUST be reported as failed rather than passed.

#### Scenario: Python coroutine result is awaited
- **WHEN** a Python solution exposes an `async def` entrypoint and the user runs `test <solution_path> <tests_dir> --lang python`
- **THEN** each selected test awaits the coroutine result before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: JavaScript promise result is awaited
- **WHEN** a JavaScript solution entrypoint returns a Promise and the user runs `test <solution_path> <tests_dir> --lang javascript`
- **THEN** each selected test awaits the Promise before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: TypeScript promise result is awaited
- **WHEN** a TypeScript solution entrypoint returns a Promise and the user runs `test <solution_path> <tests_dir> --lang typescript`
- **THEN** each selected test awaits the Promise before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: C++ future result is completed
- **WHEN** a C++ solution entrypoint returns a standard future-like result and the user runs `test <solution_path> <tests_dir> --lang cpp`
- **THEN** each selected test waits for the future result before applying comparisons, stream expectations, or exception expectation checks

#### Scenario: Rust future result is completed
- **WHEN** a Rust solution entrypoint returns a future and the user runs `test <solution_path> <tests_dir> --lang rust`
- **THEN** each selected test drives the future to completion before applying comparisons, stream expectations, or panic expectation checks

### Requirement: Test listing
The `test` command SHALL accept `--list-tests`. When discovery and tester payload revalidation succeed, `--list-tests` MUST output a pass result with every discovered test ID in `passed`, an empty `failed` array, and no solution entrypoint execution.

#### Scenario: List tests reports discovered IDs
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery succeeds for tests with IDs `tests.py:1` and `tests.py:2`
- **THEN** stdout contains exactly one JSON line with `status` set to `pass`, `passed` set to `["tests.py:1","tests.py:2"]`, and `failed` set to `[]`

#### Scenario: List tests does not execute solution
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript --list-tests` with a solution whose entrypoint would fail if called
- **THEN** the command reports discovered IDs as passing without invoking the solution entrypoint

#### Scenario: List tests preserves discovery errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery fails
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Single test selection
The `test` command SHALL accept `--run <test_id>`. When a discovered ID is selected, only that selected ID MUST appear in `passed` or `failed`; no unselected discovered IDs may appear in the result.

#### Scenario: Selected passing test is the only reported ID
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:1` and `tests.py:1` passes while other tests are discoverable
- **THEN** stdout contains exactly one JSON line with `status` set to `pass`, `passed` set to `["tests.py:1"]`, and `failed` set to `[]`

#### Scenario: Selected failing test is the only reported ID
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2` and `tests.py:2` fails while other tests are discoverable
- **THEN** stdout contains exactly one JSON line with `status` set to `fail`, `passed` set to `[]`, and `failed` set to `["tests.py:2"]`

#### Scenario: Unknown selected test is an error
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run missing.py:1` and no discovered test has ID `missing.py:1`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Test execution timeouts
The `test` command SHALL accept `--timeout-ms <int>` to bound each executed test and `--total-timeout-ms <int>` to bound the selected run. Timed-out tests and selected tests that are not executed before the total timeout expires MUST appear in `failed`.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 10` and one selected test does not complete within 10 milliseconds
- **THEN** that test ID appears in `failed` and the command reports `status` as `fail`

#### Scenario: Per-test timeout continues reporting completed tests
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript --timeout-ms 50` and one selected test passes before the timeout while another selected test times out
- **THEN** the completed passing test ID appears in `passed` and the timed-out test ID appears in `failed`

#### Scenario: Total timeout fails not-executed selected tests
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --total-timeout-ms 50` and the total timeout expires before all selected tests execute
- **THEN** every selected test ID that did not execute before the timeout appears in `failed`

#### Scenario: Run selection limits timeout reporting
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2 --timeout-ms 10` and the selected test times out while other tests are discoverable
- **THEN** only `tests.py:2` appears in `failed`

#### Scenario: Timeout result preserves JSON contract
- **WHEN** a selected run times out after discovery succeeds
- **THEN** stdout contains exactly one JSON object with only the keys `status`, `passed`, and `failed`
