## ADDED Requirements

> Extends: babel-code-goat-cli

### Requirement: Profile Command and Tester Validation
The system SHALL provide `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` as a CLI command. The `profile` command MUST accept only the target languages supported by `generate` and `test`, MUST require the expected tester file for the selected language to already exist in `<tests_dir>`, and MUST NOT create or modify tester files.

#### Scenario: Profile accepts a supported language with existing tester
- **GIVEN** `<tests_dir>/tester.py` exists
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is invoked
- **THEN** the command validates the language, uses the existing Python tester, and proceeds with profiling

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile <tests_dir> <solution_path> --lang ruby` is invoked
- **THEN** the command prints JSON with `status` set to `error`, empty `passed` and `failed` arrays, and exits with code 2

#### Scenario: Profile requires generated tester
- **GIVEN** `<tests_dir>/tester.js` is missing
- **WHEN** `profile <tests_dir> <solution_path> --lang javascript` is invoked
- **THEN** the command prints JSON with `status` set to `error`, empty `passed` and `failed` arrays, and exits with code 2

#### Scenario: Profile preserves existing tester
- **GIVEN** the expected tester file exists
- **WHEN** `profile` is invoked for that tester's language
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Profile Trial Statistics
The `profile` command SHALL accept `-n <trials>` with a default of `1`, `--warmup <k>` with a default of `0`, and `--memory`. The value of `--warmup` MUST be less than `-n`. The command MUST run each selected test for the requested trial count, exclude warmup runs from aggregate statistics, and print JSON containing at least `status`, `passed`, `failed`, and `runtime_ns` with numeric `mean` and `std` fields. When `--memory` is provided, the JSON MUST also contain `memory_kb` with numeric `mean` and `std` fields.

#### Scenario: Default single trial reports runtime statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python` runs one discovered passing test
- **THEN** the command prints JSON with `status` set to `pass`, the test ID in `passed`, an empty `failed` array, and `runtime_ns.mean` and `runtime_ns.std` numbers

#### Scenario: Warmup runs are excluded from statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 5 --warmup 2` runs one discovered test
- **THEN** the command excludes the first two trial measurements and computes `runtime_ns.mean` and `runtime_ns.std` from the remaining three trial measurements

#### Scenario: Warmup must be less than trials
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3` is invoked
- **THEN** the command prints JSON with `status` set to `error`, empty `passed` and `failed` arrays, and exits with code 2

#### Scenario: Memory flag reports memory statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python --memory` runs one discovered passing test
- **THEN** the command prints JSON containing both `runtime_ns` and `memory_kb`, each with numeric `mean` and `std` fields

### Requirement: Profile Test Flag Parity
The `profile` command SHALL support `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol <float>` with the same selection, timeout, and tolerance semantics as `test` where applicable. List-only invocations MUST enumerate matching discovered test IDs without running profiling trials.

#### Scenario: Profile lists tests without profiling
- **WHEN** `profile <tests_dir> <solution_path> --lang python --list-tests` is invoked
- **THEN** the command reports discovered test IDs without executing profiling trials

#### Scenario: Profile runs selected tests
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run tests.py:12` is invoked
- **THEN** only the matching discovered test contributes to `passed`, `failed`, and aggregate statistics

#### Scenario: Profile applies default tolerance
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol 0.01` runs a discovered assertion comparing `1.005` with `1.0`
- **THEN** the comparison passes because the numeric difference is within the default tolerance

> Extends: babel-code-goat-cli/add-async-test-selection-timeouts

### Requirement: Profile Timeout Aggregation
The `profile` command SHALL apply `--timeout-ms <int>` as a per-test timeout and `--total-timeout-ms <int>` as a total execution timeout. Tests that time out MUST appear in `failed`, and timeout measurements MUST be included in `runtime_ns` and, when requested, `memory_kb` aggregate statistics. (adapts babel-code-goat-cli/add-async-test-selection-timeouts/timeout-failure-coverage)

#### Scenario: Per-test timeout contributes to failure and statistics
- **GIVEN** a discovered test invokes an entrypoint that does not complete within `--timeout-ms`
- **WHEN** `profile <tests_dir> <solution_path> --lang python --timeout-ms 50` is invoked
- **THEN** that test ID appears in `failed` and its timeout measurement contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Total timeout marks remaining tests failed and contributes to statistics
- **GIVEN** discovery succeeds and three test IDs are selected
- **WHEN** `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 50` exhausts the total timeout before all selected tests finish
- **THEN** any unfinished selected test IDs appear in `failed` and their timeout measurements contribute to aggregate statistics
