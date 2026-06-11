## ADDED Requirements

### Requirement: Async Entrypoint Completion
The `test` command SHALL run asynchronous entrypoint invocations to completion before evaluating assertions for every supported target language. Async completion MUST use the same JSON output and exit-code contract as synchronous tests, and an async invocation that does not complete before the applicable timeout MUST fail that test.

#### Scenario: Async entrypoint resolves before assertion
- **WHEN** `test` runs a discovered case whose configured entrypoint returns an awaitable, promise, future, or equivalent asynchronous result for `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the target runner waits for the asynchronous result to complete before comparing the result, captured output, mutation side effects, or raised exception expectation

#### Scenario: Async entrypoint timeout fails the test
- **WHEN** `test --timeout-ms <int>` runs a discovered case whose asynchronous entrypoint invocation does not complete before the per-test timeout
- **THEN** that test ID appears in `failed`, does not appear in `passed`, and the command exits according to the standard fail status contract

### Requirement: Test Selection and Timeout Controls
The `test` command SHALL accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`. These flags MUST preserve the existing single-line JSON object with only `status`, `passed`, and `failed`.

#### Scenario: List tests succeeds
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked and tester metadata plus discovery succeed
- **THEN** the command prints one JSON line with `status` set to `pass`, `passed` containing every discovered test ID in discovery order, `failed` set to an empty array, and exits with code 0

#### Scenario: List tests does not execute solution code
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` is invoked against a solution that would fail, raise, hang, or be missing
- **THEN** successful tester metadata and discovery are sufficient for the command to report the discovered IDs with `status` set to `pass`

#### Scenario: Run selected test
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run <test_id>` is invoked with an ID discovered in `<tests_dir>`
- **THEN** only the selected test ID appears in `passed` or `failed`, and no other discovered test IDs appear in the result

#### Scenario: Unknown selected test errors
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run <test_id>` is invoked with an ID that is not discovered in `<tests_dir>`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Per-test timeout fails only the timed-out selected test
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --timeout-ms <int>` runs a discovered test whose entrypoint invocation exceeds the per-test timeout
- **THEN** the timed-out test ID appears in `failed` and previously completed passing test IDs remain in `passed`

#### Scenario: Total timeout marks not-executed tests failed
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --total-timeout-ms <int>` reaches the total timeout before all selected discovered tests have executed
- **THEN** every timed-out or not-executed selected test ID appears in `failed`

#### Scenario: Invalid timeout value errors
- **WHEN** `test` is invoked with `--timeout-ms` or `--total-timeout-ms` set to a non-integer or an integer less than 1
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
