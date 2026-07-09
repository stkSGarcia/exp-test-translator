## MODIFIED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat

### Requirement: Supported command interface (adapts babel-code-goat-cli/add-babel-code-goat/supported-command-interface)

The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`. The `test` command SHALL accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>` in addition to existing flags, and all successful `test` modes SHALL output exactly one JSON object with `status`, `passed`, and `failed`.

#### Scenario: list tests reports discovered ids
- **GIVEN** `<tests_dir>` contains discoverable tests
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests` runs
- **THEN** stdout contains `status` set to `"pass"`, `passed` containing every discovered test ID, and `failed` set to `[]`

#### Scenario: selected test reports only selected id
- **GIVEN** `<tests_dir>` contains multiple discovered test IDs including `tests.py:2`
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run tests.py:2` runs
- **THEN** only `tests.py:2` appears in either `passed` or `failed`

#### Scenario: unknown selected test is an error
- **GIVEN** `<tests_dir>` discovery succeeds and no discovered test has ID `missing`
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run missing` runs
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Result coverage accounting (adapts babel-code-goat-cli/add-babel-code-goat/result-coverage-accounting)

When tests are discoverable, the system SHALL place every in-scope discovered test ID exactly once in either `passed` or `failed`. For a normal run, every discovered test is in scope. For `--run <test_id>`, only the selected test is in scope. Any in-scope discovered test that times out, is interrupted by the total timeout, or is not executed for any reason MUST be listed in `failed`.

#### Scenario: every in-scope id is reported once
- **WHEN** discovery succeeds and the selected run scope completes
- **THEN** each in-scope discovered test ID appears exactly once across the `passed` and `failed` arrays

#### Scenario: total timeout fails remaining tests
- **WHEN** `--total-timeout-ms <int>` expires before all in-scope tests finish
- **THEN** every timed-out or not-executed in-scope test ID appears in `failed`

## ADDED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat
> Extends: babel-code-goat-cli/support-loop-construct-tests
> Extends: babel-code-goat-cli/support-mutation-style-tests
> Extends: babel-code-goat-cli/support-single-call-test-traceability
> Extends: compiled-language-targets/add-cpp-rust-targets

### Requirement: Async entrypoint completion

The system SHALL run async or awaitable entrypoint invocations to completion, or until timeout, in every supported target language before evaluating assertions, stream expectations, exception expectations, mutation-style outcomes, or expression-style comparisons.

#### Scenario: async target value is awaited before comparison
- **GIVEN** a generated runner invokes a target entrypoint that returns an awaitable value
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang>` runs
- **THEN** the runner waits for completion before comparing the resolved value to the expected result

#### Scenario: async target exception is awaited before exception check
- **GIVEN** a generated runner invokes a target entrypoint that raises or rejects asynchronously
- **WHEN** the discovered test expects an exception
- **THEN** the asynchronous exception is evaluated by the same pass/fail rules as a synchronous exception

### Requirement: Per-test timeout handling

The system SHALL honor `test --timeout-ms <int>` as a per-test execution bound for every supported target language. A test that exceeds the bound MUST be recorded in `failed`, and execution MAY continue with the remaining in-scope tests until the total timeout or run completion.

#### Scenario: slow selected test fails by per-test timeout
- **GIVEN** `tests.py:2` invokes a target that does not complete before the per-test timeout
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --run tests.py:2 --timeout-ms 10` runs
- **THEN** `tests.py:2` appears in `failed`

#### Scenario: later tests can still run after per-test timeout
- **GIVEN** one in-scope test times out and a later in-scope test can complete
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --timeout-ms 10` runs
- **THEN** the timed-out test appears in `failed` and the later completed test appears in `passed` or `failed` according to its assertion outcome

### Requirement: Total timeout handling

The system SHALL honor `test --total-timeout-ms <int>` as a bound for the complete `test` command after discovery and validation. If the total timeout expires, the command MUST return a valid result object and MUST fail every in-scope test that timed out or did not execute before the bound.

#### Scenario: total timeout returns coverage-preserving failure
- **GIVEN** multiple in-scope tests and the total timeout expires before all tests execute
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --total-timeout-ms 10` runs
- **THEN** the output result includes every not-executed in-scope test ID in `failed`

#### Scenario: list tests ignores execution timeout
- **GIVEN** discovery succeeds
- **WHEN** `test <solution_path> <tests_dir> --lang <target_lang> --list-tests --timeout-ms 10 --total-timeout-ms 10` runs
- **THEN** no solution entrypoint executes and the result is the same as `--list-tests` without timeout flags
