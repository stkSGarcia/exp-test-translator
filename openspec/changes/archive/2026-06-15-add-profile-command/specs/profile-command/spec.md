## ADDED Requirements

> Extends: `async-test-execution-controls/add-async-test-selection-timeouts`
> Extends: `babel-code-goat-cli/support-single-call-traceability`
> Extends: `babel-code-goat-cli/support-rich-test-comparisons`

### Requirement: Profile Command Invocation
The CLI SHALL provide `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` to execute generated tests for profiling without regenerating tester files.

#### Scenario: Profile command uses generated tester
- **GIVEN** `<tests_dir>` contains the generated tester file for `<target_lang>`
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** the CLI executes the selected tests through that tester and prints one JSON result

### Requirement: Generated Tester Prerequisite
The `profile` command SHALL require `generate` to have already created the tester file for the requested language and MUST return an error result when that tester file is missing.

#### Scenario: Missing tester errors
- **GIVEN** `<tests_dir>` does not contain the tester file for `<target_lang>`
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** the CLI returns a non-zero exit code and prints JSON with `status` set to `error`

### Requirement: Trial and Warmup Controls
The `profile` command SHALL support `-n <trials>` with default `1` and `--warmup <k>` where `k` MUST be less than `n`.

#### Scenario: Warmup must be less than trial count
- **GIVEN** the user provides `-n 3 --warmup 3`
- **WHEN** the CLI validates the profile arguments
- **THEN** the CLI returns an error result without executing profile trials

#### Scenario: Warmup runs are excluded from statistics
- **GIVEN** the user provides `-n 5 --warmup 2`
- **WHEN** the profile command completes all runs
- **THEN** the reported runtime statistics are calculated from the 3 measured trials after warmup

### Requirement: Profile Test Flag Parity
The `profile` command SHALL support `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol <float>` with the same selection, timeout, and tolerance semantics as `test` where applicable (adapts `async-test-execution-controls/add-async-test-selection-timeouts/per-test-timeout`).

#### Scenario: Profile lists tests
- **GIVEN** generated tester metadata can enumerate available tests
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests`
- **THEN** the CLI prints the same test identifiers that `test --list-tests` would print for the same inputs

#### Scenario: Profile runs selected tests
- **GIVEN** multiple tests are available
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --run <test-id>`
- **THEN** only the selected test contributes to `passed`, `failed`, and reported statistics

### Requirement: Runtime Statistics Output
The `profile` command SHALL print JSON containing at least `status`, `passed`, `failed`, and `runtime_ns` where `runtime_ns` contains numeric `mean` and `std` fields.

#### Scenario: Runtime statistics are reported
- **GIVEN** the measured profile trials complete
- **WHEN** the profile command prints its JSON result
- **THEN** the JSON contains `runtime_ns.mean` and `runtime_ns.std` calculated from measured trials only

### Requirement: Memory Statistics Output
The `profile` command SHALL support `--memory` and, when provided, include `memory_kb` with numeric `mean` and `std` fields calculated from measured trials.

#### Scenario: Memory statistics are requested
- **GIVEN** the user provides `--memory`
- **WHEN** the profile command prints its JSON result
- **THEN** the JSON contains `memory_kb.mean` and `memory_kb.std`

#### Scenario: Memory statistics are omitted by default
- **GIVEN** the user does not provide `--memory`
- **WHEN** the profile command prints its JSON result
- **THEN** the JSON does not include `memory_kb`

### Requirement: Timeout Aggregation
When profile runs timeout via `--timeout-ms` or `--total-timeout-ms`, the `profile` command SHALL include timed-out tests in `failed` and include their timing and memory measurements in aggregate statistics (adapts `async-test-execution-controls/add-async-test-selection-timeouts/per-test-timeout`).

#### Scenario: Per-test timeout contributes to statistics
- **GIVEN** a selected test exceeds `--timeout-ms`
- **WHEN** the profile command reports the result
- **THEN** the timed-out test appears in `failed` and its measurement contributes to `runtime_ns`

#### Scenario: Total timeout contributes to statistics
- **GIVEN** the profile command reaches `--total-timeout-ms` before all selected tests finish
- **WHEN** the profile command reports the result
- **THEN** unfinished timed-out tests appear in `failed` and their measurements contribute to aggregate statistics
