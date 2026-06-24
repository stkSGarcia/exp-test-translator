## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable. The `test` command MUST accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate` or `test` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Test accepts discovery listing
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests`
- **THEN** the command uses discovery-listing behavior instead of executing the solution

#### Scenario: Test accepts single test selection
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2`
- **THEN** the command limits execution and reporting to the discovered test with ID `tests.py:2`

#### Scenario: Test accepts timeout controls
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 100 --total-timeout-ms 500`
- **THEN** the command applies the requested per-test and total-run timeout limits

### Requirement: Result coverage accounting
When tests are discoverable, the system SHALL place every in-scope discovered test ID exactly once in either `passed` or `failed`. For a normal full run, every discovered test is in scope. For `--run <test_id>`, only the selected discovered test is in scope. Any in-scope discovered test that is not executed for any reason, including timeout exhaustion, MUST be listed in `failed`.

#### Scenario: Unexecuted discovered test is failed
- **WHEN** discovery succeeds but an in-scope discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Every discovered ID is reported once
- **WHEN** discovery succeeds and a full run completes
- **THEN** each discovered test ID appears exactly once across the `passed` and `failed` arrays

#### Scenario: Selected run reports only selected ID
- **WHEN** discovery succeeds and the user runs `test` with `--run tests.py:2`
- **THEN** only `tests.py:2` appears across the `passed` and `failed` arrays

#### Scenario: Timed-out test is failed
- **WHEN** discovery succeeds but an in-scope test exceeds a configured timeout
- **THEN** that test ID appears in `failed`

## ADDED Requirements

### Requirement: Async entrypoint completion
The system SHALL run async or awaitable entrypoint invocations to completion before evaluating the discovered test result for every supported target language. If an async or awaitable invocation does not complete before an applicable timeout, the corresponding test MUST fail through normal timeout result semantics.

#### Scenario: Python async entrypoint is awaited
- **WHEN** a Python solution entrypoint returns an awaitable result for a discovered test
- **THEN** the harness awaits the result before applying that test's assertion semantics

#### Scenario: JavaScript async entrypoint is awaited
- **WHEN** a JavaScript solution entrypoint returns a Promise for a discovered test
- **THEN** the harness awaits the Promise before applying that test's assertion semantics

#### Scenario: TypeScript async entrypoint is awaited
- **WHEN** a TypeScript solution entrypoint returns a Promise for a discovered test
- **THEN** the harness awaits the Promise before applying that test's assertion semantics

#### Scenario: C++ async-like entrypoint is completed
- **WHEN** a C++ solution entrypoint returns a supported future-like result for a discovered test
- **THEN** the harness waits for the result before applying that test's assertion semantics

#### Scenario: Rust async entrypoint is completed
- **WHEN** a Rust solution entrypoint returns a supported future for a discovered test
- **THEN** the harness drives the future to completion before applying that test's assertion semantics

### Requirement: Test discovery listing
The `test --list-tests` command SHALL perform discovery and generated-tester consistency validation without executing the supplied solution. If discovery succeeds, the command MUST output `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, and `failed` as an empty array. If discovery fails or generated-tester consistency validation fails, the command MUST use the standard error result.

#### Scenario: Discovery list succeeds
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery succeeds
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered IDs, and `failed` set to `[]`

#### Scenario: Discovery list fails
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery fails
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Single test selection
The `test --run <test_id>` command SHALL execute only the discovered test whose ID exactly matches `<test_id>`. The result MUST include only that selected test ID in `passed` or `failed`. If `<test_id>` is not discovered, the command MUST output the standard error result and exit `2`.

#### Scenario: Selected passing test reports only itself
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2` and `tests.py:2` passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` set to `["tests.py:2"]`, and `failed` set to `[]`

#### Scenario: Selected failing test reports only itself
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:3` and `tests.py:3` fails
- **THEN** stdout contains one JSON line with `status` set to `fail`, `passed` set to `[]`, and `failed` set to `["tests.py:3"]`

#### Scenario: Unknown selected test errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:999` and no discovered test has that ID
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Test execution timeouts
The `test --timeout-ms <int>` option SHALL bound each in-scope test's execution time. The `test --total-timeout-ms <int>` option SHALL bound the total execution time for all in-scope tests in a single `test` command invocation. Timed-out tests and in-scope tests that are not executed because the total timeout has been exhausted MUST appear in `failed`. Completed passing tests before timeout exhaustion MUST remain in `passed`.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** the user runs `test` with `--timeout-ms 50` and one in-scope test exceeds 50 milliseconds
- **THEN** that test ID appears in `failed`

#### Scenario: Total timeout fails remaining tests
- **WHEN** the user runs `test` with `--total-timeout-ms 100` and total execution time is exhausted before all in-scope tests execute
- **THEN** each not-executed in-scope test ID appears in `failed`

#### Scenario: Completed tests remain reported after timeout
- **WHEN** some in-scope tests pass before a later test exceeds a configured timeout
- **THEN** the earlier passing test IDs appear in `passed` and the timed-out or not-executed test IDs appear in `failed`
