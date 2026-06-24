## ADDED Requirements

### Requirement: Async entrypoint execution
The system SHALL run asynchronous entrypoint invocations to completion before evaluating a discovered test result for every supported target language. Async completion MUST apply to equality, inequality, truthy, falsy, primitive-expression, stdout/stderr expectation, exception-style, loop-body assertion, and mutation-style test execution. If an async invocation completes with an error, the test MUST be evaluated using the same failure or exception-style semantics as a synchronous invocation.

#### Scenario: Python async entrypoint completes
- **WHEN** a Python solution entrypoint returns an awaitable for a discovered assertion
- **THEN** the Python tester awaits the result before evaluating the assertion

#### Scenario: JavaScript async entrypoint completes
- **WHEN** a JavaScript solution entrypoint returns a Promise for a discovered assertion
- **THEN** the JavaScript tester awaits the Promise before evaluating the assertion

#### Scenario: TypeScript async entrypoint completes
- **WHEN** a TypeScript solution entrypoint returns a Promise for a discovered assertion
- **THEN** the TypeScript tester awaits the Promise before evaluating the assertion

#### Scenario: C++ async entrypoint completes
- **WHEN** a C++ solution entrypoint returns a supported future-like value for a discovered assertion
- **THEN** the C++ tester obtains the completed value before evaluating the assertion

#### Scenario: Rust async entrypoint completes
- **WHEN** a Rust solution entrypoint returns a supported future for a discovered assertion
- **THEN** the Rust tester drives the future to completion before evaluating the assertion

#### Scenario: Async exception-style test passes
- **WHEN** an async entrypoint completes by raising, rejecting, throwing, or panicking in the way expected by a discovered exception-style test
- **THEN** that test ID appears in `passed`

### Requirement: Test listing and selection
The `test` command SHALL support `--list-tests` and `--run <test_id>`. With `--list-tests`, the command MUST discover tests and report the discovered IDs without invoking the solution entrypoint. With `--run <test_id>`, the command MUST execute only the selected discovered test ID. `--list-tests` and `--run` MUST NOT be used together.

#### Scenario: List tests reports discovered IDs
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery succeeds
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, and `failed` equal to `[]`

#### Scenario: List tests does not invoke solution
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript --list-tests`
- **THEN** the command reports discovered test IDs without invoking the JavaScript solution entrypoint

#### Scenario: Selected test is the only reported result
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run nested/test_math.py:4`
- **THEN** only `nested/test_math.py:4` appears across the `passed` and `failed` arrays

#### Scenario: Selected missing test is an error
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run missing.py:1` and discovery succeeds without that ID
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: List and run together is an error
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests --run tests.py:1`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Test timeout controls
The `test` command SHALL support `--timeout-ms <int>` and `--total-timeout-ms <int>`. `--timeout-ms` MUST bound each executed test invocation. `--total-timeout-ms` MUST bound the full execution phase after discovery and generated-tester validation. Timeout values MUST be positive integers. When discovery succeeds and an executed or not-yet-executed test is affected by a timeout, the command MUST report `status="fail"` and place affected discovered test IDs in `failed`.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 10` and one discovered test exceeds 10 milliseconds
- **THEN** that timed-out test ID appears in `failed`

#### Scenario: Total timeout fails not-yet-executed tests
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --total-timeout-ms 10` and the total timeout expires before all discovered tests execute
- **THEN** every not-yet-executed discovered test ID appears in `failed`

#### Scenario: Selected test timeout reports only selected ID
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:3 --timeout-ms 10` and the selected test times out
- **THEN** only `tests.py:3` appears in `failed`

#### Scenario: Invalid timeout value is an error
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 0`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Earliest timeout wins
- **WHEN** both `--timeout-ms` and `--total-timeout-ms` are provided and one deadline expires first
- **THEN** the command reports results according to the first timeout that affects execution

## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable. The `test` command MUST also accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate` or `test` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Test accepts listing flag
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests`
- **THEN** the command accepts the flag and uses list-only test reporting semantics

#### Scenario: Test accepts run selection flag
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:1`
- **THEN** the command accepts the flag and uses selected-test execution semantics

#### Scenario: Test accepts timeout flags
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 100 --total-timeout-ms 1000`
- **THEN** the command accepts the timeout flags and applies the configured execution deadlines

### Requirement: Result coverage accounting
When tests are discoverable and the user has not selected a single test with `--run`, the system SHALL place every discovered test ID exactly once in either `passed` or `failed`. Any discovered test that is not executed for any reason MUST be listed in `failed`. When `--run <test_id>` selects one discovered test, the system SHALL place only that selected test ID exactly once in either `passed` or `failed`.

#### Scenario: Unexecuted discovered test is failed
- **WHEN** discovery succeeds for a full test run but a discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Every discovered ID is reported once
- **WHEN** discovery succeeds for a full test run and the run completes
- **THEN** each discovered test ID appears exactly once across the `passed` and `failed` arrays

#### Scenario: Selected run reports only selected ID once
- **WHEN** discovery succeeds and `--run tests.py:2` selects `tests.py:2`
- **THEN** only `tests.py:2` appears exactly once across the `passed` and `failed` arrays

#### Scenario: Timeout preserves full-run coverage
- **WHEN** discovery succeeds for a full test run and timeout prevents later discovered tests from executing
- **THEN** each not-yet-executed discovered test ID appears in `failed`
