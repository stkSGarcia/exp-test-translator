## ADDED Requirements

> Extends: babel-code-goat-cli/support-rich-python-test-comparisons
> Extends: async-test-execution-controls/support-async-test-selection-timeouts

### Requirement: Profile command interface (adapts babel-code-goat-cli/support-rich-python-test-comparisons/supported-command-interface)
The system SHALL provide a root-level `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command that profiles a generated tester against the provided solution for the requested target language.

#### Scenario: Profile accepts supported language
- **GIVEN** `generate` has produced a tester file for a supported target language
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** the command executes the generated tester for that solution and emits profiling JSON

#### Scenario: Missing tester is rejected
- **GIVEN** no tester file exists for the requested target language
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang>`
- **THEN** the command exits non-zero with an error indicating that `generate` must run before profiling

### Requirement: Profile execution controls
The `profile` command SHALL accept `-n <trials>` with default `1`, `--warmup <k>` where `k < n`, and `--memory` to request memory profiling.

#### Scenario: Trial count defaults to one
- **WHEN** the user runs `profile` without `-n`
- **THEN** the command performs one measured profiling trial

#### Scenario: Warmup must be smaller than trials
- **WHEN** the user runs `profile -n <trials> --warmup <k>` with `k >= trials`
- **THEN** the command exits non-zero with a validation error

#### Scenario: Warmup runs are excluded
- **GIVEN** the user requests warmup runs with `--warmup <k>` and measured trials with `-n <trials>`
- **WHEN** the command computes aggregate statistics
- **THEN** only the non-warmup trials contribute to the reported mean and standard deviation

### Requirement: Profile test flag parity
The `profile` command SHALL support the same selection, timeout, and tolerance flags as the `test` command: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol <float>`.

#### Scenario: List tests uses test discovery
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests`
- **THEN** the command lists the same in-scope discovered tests that the `test` command would list

#### Scenario: Run selection limits profiled tests
- **GIVEN** multiple tests are discoverable
- **WHEN** the user runs `profile` with one or more `--run` selectors
- **THEN** only the selected tests are profiled and reported

#### Scenario: Tolerance matches test behavior
- **WHEN** the user runs `profile` with `--tol <float>`
- **THEN** result comparison uses the same tolerance semantics as the `test` command

### Requirement: Profile JSON statistics
The `profile` command SHALL print JSON containing at least `status`, `passed`, `failed`, and `runtime_ns` with numeric `mean` and `std` fields, and SHALL include `memory_kb` with numeric `mean` and `std` fields when `--memory` is provided.

#### Scenario: Runtime statistics are always reported
- **WHEN** the user runs `profile` and profiling completes
- **THEN** the JSON output includes `status`, `passed`, `failed`, and `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Memory statistics are reported on request
- **WHEN** the user runs `profile --memory` and profiling completes
- **THEN** the JSON output includes `memory_kb.mean` and `memory_kb.std`

#### Scenario: Memory statistics are omitted without request
- **WHEN** the user runs `profile` without `--memory`
- **THEN** the JSON output does not include `memory_kb`

### Requirement: Profile timeout accounting (adapts async-test-execution-controls/support-async-test-selection-timeouts/timeout-result-accounting-adapts-babel-code-goat-cli-add-babel-code-goat-result-coverage-accounting)
The `profile` command SHALL apply `--timeout-ms <int>` per-test timeout enforcement and `--total-timeout-ms <int>` whole-run timeout enforcement, and SHALL include timed-out test results in the failed list and in runtime and memory aggregate statistics.

#### Scenario: Per-test timeout is failed and aggregated
- **GIVEN** a profiled test exceeds the `--timeout-ms` value
- **WHEN** the `profile` command reports results
- **THEN** that test ID appears in `failed` and its timing and memory data contribute to the aggregate statistics

#### Scenario: Total timeout is failed and aggregated
- **GIVEN** discovery succeeds for multiple in-scope tests
- **WHEN** `--total-timeout-ms` is reached before every selected test completes
- **THEN** each timed-out or not-executed selected test appears in `failed` and timeout timing and memory data contribute to the aggregate statistics
