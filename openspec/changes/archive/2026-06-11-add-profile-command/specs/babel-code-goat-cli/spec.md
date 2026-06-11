## ADDED Requirements

### Requirement: Profile Command and Preconditions
The system SHALL provide `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` for `python`, `javascript`, `typescript`, `cpp`, and `rust`. The `profile` command MUST require the expected generated tester file for the selected language to exist before profiling and MUST NOT create or modify tester files.

#### Scenario: Profile accepts a supported language
- **WHEN** `profile <tests_dir> <solution_path> --lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust` is invoked with a valid existing tester file
- **THEN** the command validates the language and proceeds with profile discovery and execution

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile <tests_dir> <solution_path> --lang nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile requires generated tester
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang>` is invoked and the expected tester file for `<target_lang>` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile preserves existing tester
- **WHEN** `profile` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Profile Trial Flags
The `profile` command SHALL accept `-n <trials>`, `--warmup <k>`, and `--memory`. `-n` MUST default to `1` and represent the total number of profile trials. `--warmup` MUST default to `0`, represent the number of leading trials excluded from statistics, and satisfy `0 <= k < n`. Invalid trial or warmup values MUST be treated as profile command errors.

#### Scenario: Default trial count runs one measured trial
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang>` is invoked without `-n` or `--warmup`
- **THEN** the command executes one measured profile trial and reports statistics computed from that one trial

#### Scenario: Warmup trials are excluded from statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> -n 5 --warmup 2` completes
- **THEN** the command computes `runtime_ns` statistics from the final three trials only

#### Scenario: Invalid trial count errors
- **WHEN** `profile` is invoked with `-n` set to a non-integer or an integer less than `1`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Invalid warmup count errors
- **WHEN** `profile` is invoked with `--warmup` set to a non-integer, an integer less than `0`, or an integer greater than or equal to the effective `-n` value
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile Test Flag Parity
The `profile` command SHALL accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>` with the same discovery, selection, timeout, and tolerance behavior as the `test` command where applicable.

#### Scenario: Profile lists tests without executing solution code
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests` is invoked and tester metadata plus discovery succeed
- **THEN** the command prints one JSON line with `status` set to `pass`, `passed` containing every discovered test ID in discovery order, `failed` set to an empty array, exits with code 0, and does not execute solution code

#### Scenario: Profile runs selected test
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --run <test_id>` is invoked with an ID discovered in `<tests_dir>`
- **THEN** only the selected test ID appears in `passed` or `failed`, and no other discovered test IDs appear in the result

#### Scenario: Profile unknown selected test errors
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --run <test_id>` is invoked with an ID that is not discovered in `<tests_dir>`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile invalid timeout value errors
- **WHEN** `profile` is invoked with `--timeout-ms` or `--total-timeout-ms` set to a non-integer or an integer less than `1`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile default tolerance matches test behavior
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol 0.01` runs a discovered assertion comparing `[1.0, {"x": 2.005}]` with `[1.0, {"x": 2.0}]`
- **THEN** the comparison passes because the nested float difference is within the default tolerance

#### Scenario: Profile invalid tolerance errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile JSON Output and Statistics
The `profile` command MUST print exactly one line to stdout containing a JSON object. For profile executions that run solution code, the object MUST include at least `status`, `passed`, `failed`, and `runtime_ns`; `runtime_ns` MUST be an object with numeric `mean` and `std` fields. The status MUST be one of `pass`, `fail`, or `error`; `passed` and `failed` MUST be arrays. The command MUST exit with code 0 for `pass`, code 1 for `fail`, and code 2 for `error`. A test ID MUST appear in `failed` if it fails in any profile trial, including warmup trials; a test ID MUST appear in `passed` only if it passes in every profile trial.

#### Scenario: Successful profile reports runtime statistics
- **WHEN** all selected tests pass across all profile trials
- **THEN** `profile` prints a single JSON line with `status` set to `pass`, all selected test IDs in `passed`, an empty `failed` array, `runtime_ns.mean` as a number, `runtime_ns.std` as a number, and exits with code 0

#### Scenario: Failing profile reports runtime statistics
- **WHEN** at least one selected test fails during any profile trial after successful discovery
- **THEN** `profile` prints a single JSON line with `status` set to `fail`, includes failed test IDs in `failed`, includes only test IDs that passed every profile trial in `passed`, includes numeric `runtime_ns.mean` and `runtime_ns.std`, and exits with code 1

#### Scenario: Single measured trial has zero standard deviation
- **WHEN** `profile` completes with exactly one non-warmup measured trial
- **THEN** `runtime_ns.std` is `0`

#### Scenario: Memory profile reports memory statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --memory` runs solution code
- **THEN** the output JSON includes `memory_kb` with numeric `mean` and `std` fields computed from the measured non-warmup trials

#### Scenario: Profile error uses standard error JSON
- **WHEN** `profile` encounters an error condition before successful profile execution
- **THEN** `profile` prints a single JSON line with `status` set to `error`, `passed` set to an empty array, `failed` set to an empty array, and exits with code 2

### Requirement: Profile Timeout Statistics
The `profile` command MUST include timeout results from `--timeout-ms` and `--total-timeout-ms` in aggregated runtime statistics and, when `--memory` is provided, aggregated memory statistics. Timed-out tests and selected tests not executed because of total-timeout exhaustion MUST appear in `failed`.

#### Scenario: Per-test timeout contributes to profile statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --timeout-ms <int>` runs a selected test whose entrypoint invocation exceeds the per-test timeout during a measured trial
- **THEN** the timed-out test ID appears in `failed`, the command exits with code 1, and the measured timeout duration contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Total timeout contributes to profile statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --total-timeout-ms <int>` reaches the total timeout during a measured trial before all selected discovered tests have executed
- **THEN** every timed-out or not-executed selected test ID appears in `failed`, the command exits with code 1, and the measured timeout duration contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Timeout memory data contributes when requested
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --memory --timeout-ms <int>` records a timeout during a measured trial
- **THEN** the output JSON includes `memory_kb.mean` and `memory_kb.std` computed from the measured trials, including the timed-out measured trial
