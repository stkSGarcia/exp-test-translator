## ADDED Requirements

### Requirement: Profile Command
The system SHALL provide `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` for every supported target language. The command MUST require the expected generated tester file for the selected language to already exist, MUST NOT create or modify tester files, and MUST use the same supported language set as `generate` and `test`.

#### Scenario: Profile requires an existing tester
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang>` is invoked and the expected tester file for `<target_lang>` is missing from `<tests_dir>`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile <tests_dir> <solution_path> --lang nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile preserves the generated tester
- **GIVEN** the expected tester file exists in `<tests_dir>`
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang>` exits
- **THEN** the tester file content is unchanged

### Requirement: Profile Trials and Warmups
The `profile` command SHALL accept `-n <trials>` with default `1` and `--warmup <k>` with default `0`. Trial counts MUST be positive integers. Warmup counts MUST be non-negative integers and MUST satisfy `k < n`. Warmup runs MUST execute before measured trials and MUST be excluded from reported runtime and memory statistics.

#### Scenario: Default profile run measures one trial
- **GIVEN** discovery succeeds and every in-scope test passes
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang>` is invoked without `-n` or `--warmup`
- **THEN** each in-scope test is executed once as a measured trial

#### Scenario: Warmup runs are excluded from statistics
- **GIVEN** discovery succeeds and every in-scope test passes
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> -n 3 --warmup 1` is invoked
- **THEN** each in-scope test is executed once as an unmeasured warmup before the three measured trials and only the measured trials contribute to aggregate statistics

#### Scenario: Trial and warmup values are validated
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> -n 0`, `-n nope`, `--warmup -1`, or `-n 2 --warmup 2` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile Selection, Tolerance, and Timeouts
The `profile` command SHALL accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>` with the same validation and discovery semantics as `test` where applicable. Listing tests MUST perform normal validation and discovery without loading or executing the solution. Selecting a test MUST profile only the selected discovered test. `--list-tests` and `--run` MUST NOT be used together. Timeout values MUST be positive integer millisecond durations.

#### Scenario: Profile list tests reports discovered IDs
- **GIVEN** the expected tester file exists and discovery succeeds
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests` is invoked
- **THEN** the command prints exactly one JSON line with `status` set to `pass`, `passed` containing every discovered test ID in discovery order, `failed` set to an empty array, `runtime_ns` present with numeric `mean` and `std` values of `0`, and exits with code 0

#### Scenario: Profile list tests does not execute the solution
- **GIVEN** discovery succeeds and the supplied solution path is missing, invalid, or would fail if executed
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests` is invoked
- **THEN** the command reports the discovered IDs without loading or invoking the solution

#### Scenario: Profile selected test reports only that ID
- **GIVEN** discovery includes test IDs `tests.py:1` and `tests.py:2`
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --run tests.py:2` is invoked
- **THEN** only `tests.py:2` appears in either `passed` or `failed`

#### Scenario: Profile selected test accepts tolerance
- **GIVEN** discovery includes a floating point assertion that passes under tolerance `0.01` and fails under the default tolerance
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --tol 0.01 --run tests.py:1` is invoked
- **THEN** `tests.py:1` appears in `passed`

#### Scenario: Profile rejects invalid selection or timeout flags
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests --run tests.py:1`, `--run missing.py:1`, `--timeout-ms 0`, or `--total-timeout-ms nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile JSON Output and Exit Codes
The `profile` command MUST print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object containing numeric `mean` and `std` fields computed over measured profile attempts. The status MUST be one of `pass`, `fail`, or `error`; `passed` and `failed` MUST be arrays. The command MUST exit with code 0 for `pass`, code 1 for `fail`, and code 2 for `error`.

#### Scenario: Profile all tests pass
- **GIVEN** every in-scope measured test attempt passes
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> -n 2` is invoked
- **THEN** the command prints a single JSON line with `status` set to `pass`, all in-scope test IDs in `passed`, an empty `failed` array, `runtime_ns.mean` and `runtime_ns.std` as numbers, and exits with code 0

#### Scenario: Profile reports failed tests
- **GIVEN** at least one in-scope measured test attempt fails after successful discovery
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> -n 2` is invoked
- **THEN** the command prints a single JSON line with `status` set to `fail`, includes failed test IDs in `failed`, includes passing test IDs in `passed`, includes numeric runtime statistics for measured attempts, and exits with code 1

#### Scenario: Profile command errors
- **WHEN** `profile` encounters an error condition before successful profile execution
- **THEN** `profile` prints a single JSON line with `status` set to `error`, `passed` set to an empty array, `failed` set to an empty array, no required profiling statistic keys, and exits with code 2

### Requirement: Profile Memory Statistics
The `profile` command SHALL accept `--memory` to include memory statistics in the profile output. When `--memory` is provided and profiling reaches measured execution, the JSON output MUST include `memory_kb` as an object containing numeric `mean` and `std` fields computed over measured profile attempts. Warmup runs MUST be excluded from memory statistics.

#### Scenario: Memory profiling adds memory statistics
- **GIVEN** discovery succeeds and every in-scope measured test attempt passes
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --memory -n 2` is invoked
- **THEN** the command prints a single JSON line with `memory_kb.mean` and `memory_kb.std` as numbers in addition to `runtime_ns`

#### Scenario: Memory profiling excludes warmups
- **GIVEN** discovery succeeds and every in-scope measured test attempt passes
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --memory -n 3 --warmup 1` is invoked
- **THEN** `memory_kb.mean` and `memory_kb.std` are computed only from the three measured trials per in-scope test

### Requirement: Profile Timeout Statistics
The `profile` command SHALL include timed out measured attempts in aggregate runtime and memory statistics. When an in-scope test times out via `--timeout-ms` or `--total-timeout-ms`, that test ID MUST appear in `failed`; any timing and memory data collected for the timeout attempt MUST contribute to the reported mean and standard deviation.

#### Scenario: Per-test timeout contributes to profile statistics
- **GIVEN** discovery includes `tests.py:1` and its entrypoint invocation does not complete within the requested per-test timeout
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --timeout-ms 50` is invoked
- **THEN** `tests.py:1` appears in `failed`, the output status is `fail`, and `runtime_ns.mean` and `runtime_ns.std` include the timed out measured attempt

#### Scenario: Total timeout contributes to profile statistics
- **GIVEN** discovery includes `tests.py:1`, `tests.py:2`, and `tests.py:3`
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --total-timeout-ms 100` exhausts the total timeout before all in-scope measured attempts complete
- **THEN** every timed out or not-yet-completed in-scope test ID appears in `failed`, already passed tests remain in `passed`, the output status is `fail`, and collected timeout timing data contributes to `runtime_ns`
