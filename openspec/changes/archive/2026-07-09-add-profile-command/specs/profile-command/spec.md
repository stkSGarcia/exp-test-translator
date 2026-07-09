## ADDED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat
> Extends: babel-code-goat-cli/add-async-test-selection-timeouts
> Extends: compiled-language-targets/add-cpp-rust-targets

### Requirement: Supported profile command interface (adapts babel-code-goat-cli/add-babel-code-goat/supported-command-interface)
The system SHALL provide a root-level `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command that profiles the generated tester for the selected target language against the provided solution.

#### Scenario: Profile accepts supported language
- **GIVEN** `<tests_dir>` contains the generated tester file for the requested language
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** the command profiles the tests for that language and prints a single JSON result object

### Requirement: Generated tester prerequisite (adapts babel-code-goat-cli/add-babel-code-goat/test-command-requires-generated-tester)
The `profile` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `profile` command MUST NOT create or modify any tester file.

#### Scenario: Missing tester errors
- **GIVEN** the expected tester file for the selected language is missing from `<tests_dir>`
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** stdout reports an error result and the command does not create or modify a tester file

#### Scenario: Missing compiled tester errors
- **GIVEN** `<tests_dir>/tester.cpp` or `<tests_dir>/tester.rs` is missing for a compiled target
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang cpp` or `--lang rust`
- **THEN** stdout reports an error result and identifies the missing generated tester for that target

### Requirement: Profile flag parity
The `profile` command SHALL support the same selection, timeout, and tolerance flags as `test`: `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>`.

#### Scenario: Profile lists tests
- **GIVEN** tests are discoverable in `<tests_dir>`
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests`
- **THEN** the JSON result lists the discoverable test IDs using the same semantics as `test --list-tests`

#### Scenario: Profile runs selected test
- **GIVEN** tests are discoverable in `<tests_dir>`
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --run <test_id>`
- **THEN** only the selected test ID appears in `passed` or `failed`

#### Scenario: Profile applies tolerance
- **GIVEN** a test contains tolerance-applicable comparisons
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --tol <float>`
- **THEN** the comparisons use the same default tolerance semantics as `test`

### Requirement: Trial count and warmup
The `profile` command SHALL support `-n <trials>` with default `1` and `--warmup <k>`, and SHALL reject invocations where `k >= n`.

#### Scenario: Default single trial
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>` without `-n`
- **THEN** one measured trial contributes to the aggregate statistics

#### Scenario: Warmup excluded from statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> -n 5 --warmup 2`
- **THEN** the command performs warmup executions before measured executions and excludes warmup samples from mean and standard deviation

#### Scenario: Invalid warmup is rejected
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> -n 3 --warmup 3`
- **THEN** stdout reports an error result without profiling measured trials

### Requirement: Runtime statistics output
The `profile` command SHALL print JSON including at least `status`, `passed`, `failed`, and `runtime_ns` as an object containing numeric `mean` and `std` fields.

#### Scenario: Runtime statistics are emitted
- **WHEN** profiling completes for one or more measured trials
- **THEN** stdout contains exactly one JSON object with `runtime_ns.mean` and `runtime_ns.std` computed from measured trial samples

### Requirement: Memory statistics output
The `profile` command SHALL support `--memory` and, when provided, include `memory_kb` as an object containing numeric `mean` and `std` fields.

#### Scenario: Memory statistics requested
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --memory`
- **THEN** stdout contains `memory_kb.mean` and `memory_kb.std` computed from measured trial samples

#### Scenario: Memory statistics omitted by default
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>` without `--memory`
- **THEN** stdout does not require a `memory_kb` field

### Requirement: Timeout sample aggregation
The `profile` command SHALL include timeout results from `--timeout-ms` and `--total-timeout-ms` in the aggregated runtime and memory statistics, and SHALL list timed-out or not-executed tests in `failed`.

#### Scenario: Per-test timeout contributes to profile result
- **WHEN** a profiled test times out due to `--timeout-ms`
- **THEN** the test ID appears in `failed` and its timing and memory sample contributes to the aggregate statistics

#### Scenario: Total timeout contributes to profile result
- **WHEN** profiling stops because `--total-timeout-ms` is exceeded
- **THEN** timed-out or not-executed test IDs appear in `failed` and available timeout samples contribute to the aggregate statistics
