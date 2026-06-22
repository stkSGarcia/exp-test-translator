## ADDED Requirements

### Requirement: Async Entrypoint Execution
The system SHALL run each discovered entrypoint invocation to completion before evaluating the test result when the target language produces an async or awaitable result. Async completion MUST apply consistently for direct assertions, loop-discovered assertions, mutation-style tests, raw output expectations, and exception expectation blocks. If an async invocation does not complete before the effective timeout, the corresponding test ID MUST appear in `failed`.

#### Scenario: Python awaitable result is awaited
- **GIVEN** a generated Python tester and a Python solution whose configured entrypoint is `async def solve(...)`
- **WHEN** `test <solution.py> <tests_dir> --lang python` runs a discovered assertion against that entrypoint
- **THEN** the harness awaits the coroutine result before evaluating the assertion outcome

#### Scenario: JavaScript promise result is awaited
- **GIVEN** a generated JavaScript tester and a JavaScript solution whose configured entrypoint returns a `Promise`
- **WHEN** `test <solution.js> <tests_dir> --lang javascript` runs a discovered assertion against that entrypoint
- **THEN** the harness waits for the promise to settle before evaluating the assertion outcome

#### Scenario: TypeScript promise result is awaited
- **GIVEN** a generated TypeScript tester and a TypeScript solution whose configured entrypoint returns a `Promise`
- **WHEN** `test <solution.ts> <tests_dir> --lang typescript` runs a discovered assertion against that entrypoint
- **THEN** the harness waits for the promise to settle before evaluating the assertion outcome

#### Scenario: C++ future-like result is completed
- **GIVEN** a generated C++ tester and a C++ solution whose configured entrypoint returns a supported future-like result such as `std::future<T>`
- **WHEN** `test <solution.cpp> <tests_dir> --lang cpp` runs a discovered assertion against that entrypoint
- **THEN** the harness obtains the completed value before evaluating the assertion outcome

#### Scenario: Rust future result is completed
- **GIVEN** a generated Rust tester and a Rust solution whose configured entrypoint returns a supported future result
- **WHEN** `test <solution.rs> <tests_dir> --lang rust` runs a discovered assertion against that entrypoint
- **THEN** the harness drives the future to completion before evaluating the assertion outcome

#### Scenario: Async exception expectation is evaluated after completion
- **GIVEN** a discovered raise-any or typed exception expectation whose configured entrypoint raises, rejects, throws, or panics asynchronously
- **WHEN** `test` runs the expectation for any supported target language
- **THEN** the expectation passes only when the completed async outcome matches the expected exception behavior

### Requirement: Test Listing and Selection
The `test` command SHALL accept `--list-tests` and `--run <test_id>` flags. Listing tests MUST perform normal validation and discovery but MUST NOT execute the solution entrypoint. Selecting a test MUST execute only the discovered test with the requested ID. `--list-tests` and `--run` MUST NOT be used together.

#### Scenario: List tests reports discovered IDs
- **GIVEN** the expected tester file exists and discovery succeeds
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked
- **THEN** the command prints exactly one JSON line with `status` set to `pass`, `passed` containing every discovered test ID in discovery order, `failed` set to an empty array, and exits with code 0

#### Scenario: List tests does not execute the solution
- **GIVEN** discovery succeeds and the supplied solution path is missing, invalid, or would fail if executed
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked
- **THEN** the command reports the discovered IDs without loading or invoking the solution

#### Scenario: Run selected test reports only that ID
- **GIVEN** discovery includes test IDs `tests.py:1` and `tests.py:2`
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run tests.py:2` is invoked
- **THEN** only `tests.py:2` appears in either `passed` or `failed`

#### Scenario: Unknown selected test is an error
- **GIVEN** discovery succeeds and does not include the requested test ID
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run missing.py:1` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Listing and selection are mutually exclusive
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests --run tests.py:1` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test Execution Timeouts
The `test` command SHALL accept `--timeout-ms <int>` as the per-test execution timeout and `--total-timeout-ms <int>` as the whole-command execution timeout. Timeout values MUST be positive integer millisecond durations. Timed out tests and tests not executed because the total timeout has elapsed MUST appear in `failed` according to the coverage rule. Timeout failures after successful discovery MUST use `status` `fail` and exit code 1.

#### Scenario: Per-test timeout fails the timed out test
- **GIVEN** discovery includes `tests.py:1` and its entrypoint invocation does not complete within the requested per-test timeout
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --timeout-ms 50` is invoked
- **THEN** `tests.py:1` appears in `failed`, does not appear in `passed`, the output status is `fail`, and the command exits with code 1

#### Scenario: Total timeout marks remaining in-scope tests failed
- **GIVEN** discovery includes `tests.py:1`, `tests.py:2`, and `tests.py:3`
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --total-timeout-ms 100` exhausts the total timeout before all in-scope tests execute
- **THEN** every not-yet-executed in-scope test ID appears in `failed`, already passed tests remain in `passed`, the output status is `fail`, and the command exits with code 1

#### Scenario: Total timeout respects selected test scope
- **GIVEN** discovery includes `tests.py:1` and `tests.py:2`
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run tests.py:2 --total-timeout-ms 100` times out before the selected test completes
- **THEN** only `tests.py:2` appears in `failed`

#### Scenario: Timeout values are validated
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --timeout-ms 0`, `--timeout-ms -1`, or `--total-timeout-ms nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
