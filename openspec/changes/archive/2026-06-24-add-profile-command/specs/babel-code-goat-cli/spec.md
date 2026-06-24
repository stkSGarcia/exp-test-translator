## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` and `profile` commands MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable. The `test` and `profile` commands MUST also accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`. The `profile` command MUST accept `-n <trials>`, `--warmup <k>`, and `--memory`.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate`, `test`, or `profile` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
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

#### Scenario: Profile accepts default tolerance
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Profile accepts listing flag
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests`
- **THEN** the command accepts the flag and uses list-only profile reporting semantics

#### Scenario: Profile accepts run selection flag
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:1`
- **THEN** the command accepts the flag and uses selected-test profiling semantics

#### Scenario: Profile accepts timeout flags
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 100 --total-timeout-ms 1000`
- **THEN** the command accepts the timeout flags and applies the configured execution deadlines

#### Scenario: Profile accepts trial and warmup flags
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 5 --warmup 2`
- **THEN** the command accepts the flags and excludes the two warmup trials from reported statistics

#### Scenario: Profile accepts memory flag
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory`
- **THEN** the command accepts the flag and includes memory statistics in the profile output when profiling succeeds

## ADDED Requirements

### Requirement: Profile command requires generated tester
The `profile` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `profile` command MUST NOT create or modify any tester file.

#### Scenario: Missing Python tester errors during profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` and `<tests_dir>/tester.py` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing JavaScript tester errors during profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang javascript` and `<tests_dir>/tester.js` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing TypeScript tester errors during profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang typescript` and `<tests_dir>/tester.ts` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing C++ tester errors during profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang cpp` and `<tests_dir>/tester.cpp` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing Rust tester errors during profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang rust` and `<tests_dir>/tester.rs` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile trial controls
The `profile` command SHALL support `-n <trials>` with default `1` and `--warmup <k>` with default `0`. Trial and warmup values MUST be non-negative integers, `trials` MUST be at least `1`, and `warmup` MUST be less than `trials`. Warmup executions MUST be excluded from all reported runtime and memory statistics.

#### Scenario: Default profile trial count
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` without `-n`
- **THEN** the command performs one measured trial

#### Scenario: Multiple measured trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3`
- **THEN** the reported runtime statistics are computed from the three measured trials

#### Scenario: Warmup excluded from statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 1`
- **THEN** the command performs one warmup trial before three measured trials and excludes the warmup timing and memory observations from reported statistics

#### Scenario: Warmup must be less than trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Invalid trial count is an error
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 0`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile output and exit codes
The `profile` command SHALL print exactly one line to stdout containing a JSON object. On success or test failure, the object MUST include `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object containing numeric `mean` and `std` values. If `--memory` is provided, the object MUST also include `memory_kb` with numeric `mean` and `std` values. The `status` value MUST be `pass`, `fail`, or `error`. The command MUST exit `0` for `pass`, `1` for `fail`, and `2` for `error`. Error output MUST use the existing strict error object `{"status":"error","passed":[],"failed":[]}`.

#### Scenario: Passing profile reports runtime statistics
- **WHEN** every selected discovered test passes during measured profile trials
- **THEN** stdout contains one JSON line with `status` set to `pass`, passing test IDs in `passed`, no test IDs in `failed`, and `runtime_ns` containing numeric `mean` and `std`

#### Scenario: Failing profile reports runtime statistics
- **WHEN** at least one selected discovered test fails during measured profile trials and no harness error prevents reporting
- **THEN** stdout contains one JSON line with `status` set to `fail`, passing test IDs in `passed`, failing test IDs in `failed`, and `runtime_ns` containing numeric `mean` and `std`

#### Scenario: Memory profile reports memory statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory` and profiling succeeds
- **THEN** stdout contains one JSON line with `memory_kb` containing numeric `mean` and `std`

#### Scenario: Profile error keeps strict error output
- **WHEN** discovery fails, generated-tester validation fails, profile flags are invalid, or a required profile precondition is not met
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile list tests reports discovered IDs
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests` and discovery succeeds
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` equal to `[]`, and `runtime_ns` containing numeric `mean` and `std`

### Requirement: Profile timeout statistics
The `profile` command SHALL apply `--timeout-ms <int>` and `--total-timeout-ms <int>` using the same execution deadline semantics as `test`. When a selected test times out or a total timeout prevents later selected tests from executing, affected test IDs MUST appear in `failed`, `status` MUST be `fail`, and the timeout observations MUST be included in the reported runtime statistics and memory statistics when `--memory` is provided.

#### Scenario: Per-test timeout is included in profile statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 10` and one selected discovered test exceeds 10 milliseconds
- **THEN** that timed-out test ID appears in `failed` and the timed-out execution contributes to `runtime_ns`

#### Scenario: Total timeout fails not-yet-executed profile tests
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 10` and the total timeout expires before all selected discovered tests execute
- **THEN** every not-yet-executed selected discovered test ID appears in `failed` and timeout observations contribute to `runtime_ns`

#### Scenario: Selected profile timeout reports only selected ID
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:3 --timeout-ms 10` and the selected test times out
- **THEN** only `tests.py:3` appears in `failed` and the timed-out execution contributes to `runtime_ns`

#### Scenario: Timeout memory observation is included when requested
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory --timeout-ms 10` and one selected discovered test times out after memory is observed
- **THEN** that memory observation contributes to `memory_kb`
