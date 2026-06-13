## ADDED Requirements

### Requirement: Profile Command Availability and Validation
The system SHALL provide `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]`. The `profile` command MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The expected tester file for the selected language MUST already exist in `<tests_dir>` before profiling begins, and `profile` MUST NOT create or modify tester files.

#### Scenario: Profile accepts a supported language after generation
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` succeeds and `profile <tests_dir> <solution_path> --lang python` is invoked
- **THEN** the command validates the existing `tester.py` metadata and proceeds with profiling

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile <tests_dir> <solution_path> --lang ruby` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile requires existing tester
- **WHEN** `profile <tests_dir> <solution_path> --lang javascript` is invoked and `<tests_dir>/tester.js` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Existing tester is preserved during profile
- **WHEN** `profile` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Profile JSON Output and Exit Codes
For non-listing profile runs, the `profile` command MUST print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The status MUST be one of `pass`, `fail`, or `error`; `passed` and `failed` MUST be arrays; `runtime_ns` MUST be an object containing numeric `mean` and `std` values in nanoseconds. The command MUST exit with code 0 for `pass`, code 1 for `fail`, and code 2 for `error`.

#### Scenario: Profile reports passing tests with runtime statistics
- **WHEN** all selected measured profile executions pass
- **THEN** `profile` prints a single JSON line with `status` set to `pass`, all selected test IDs in `passed`, an empty `failed` array, and `runtime_ns` containing non-negative numeric `mean` and `std`

#### Scenario: Profile reports failing tests with runtime statistics
- **WHEN** at least one selected measured profile execution fails after successful discovery
- **THEN** `profile` prints a single JSON line with `status` set to `fail`, includes failed test IDs in `failed`, includes passing test IDs in `passed`, includes `runtime_ns`, and exits with code 1

#### Scenario: Profile command errors
- **WHEN** `profile` encounters an error condition before successful profile execution
- **THEN** `profile` prints a single JSON line with `status` set to `error`, empty `passed` and `failed` arrays, and exits with code 2

### Requirement: Profile Trial and Warmup Statistics
The `profile` command SHALL accept `-n <trials>` with default `1` and `--warmup <k>` with default `0`. Trial counts MUST be positive integers. Warmup counts MUST be non-negative integers and MUST satisfy `k < n`. The command MUST run warmup executions before measured executions and MUST exclude warmup executions from `runtime_ns` and `memory_kb` statistics. Measured statistics MUST aggregate measured selected test executions and report the population mean and population standard deviation.

#### Scenario: Default profile runs one measured trial
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is invoked without `-n` or `--warmup`
- **THEN** the command runs one measured profile trial for each selected discovered test

#### Scenario: Multiple trials aggregate measured executions
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3` is invoked and two tests are selected
- **THEN** runtime statistics are calculated from the measured executions for all selected tests across the three trials

#### Scenario: Warmup executions are excluded from statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 1` is invoked
- **THEN** the command runs one warmup trial before the three measured trials and excludes the warmup trial from `runtime_ns` and `memory_kb`

#### Scenario: Invalid trial or warmup values error
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 0`, `-n nope`, `--warmup -1`, or `--warmup 2 -n 2` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile Flag Parity with Test
The `profile` command SHALL support the same selection, timeout, and tolerance flags as `test`: `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>`. These flags MUST preserve the corresponding `test` semantics unless a profile-specific requirement states otherwise.

#### Scenario: Profile list tests reports discovered IDs without execution
- **WHEN** `profile <tests_dir> <solution_path> --lang python --list-tests` is invoked and discovery succeeds with test IDs `tests.py:1` and `tests.py:2`
- **THEN** the command prints exactly `{"status":"pass","passed":["tests.py:1","tests.py:2"],"failed":[]}` as one stdout line and exits with code 0

#### Scenario: Profile list tests does not execute solution code
- **WHEN** `profile <tests_dir> <solution_path> --lang javascript --list-tests` is invoked with a solution whose entrypoint would fail if called and discovery succeeds
- **THEN** the command reports discovered test IDs as passing without invoking the entrypoint

#### Scenario: Profile run selected test reports only that ID
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run tests.py:2` is invoked and discovery includes `tests.py:1` and `tests.py:2`
- **THEN** only `tests.py:2` appears in `passed` or `failed`

#### Scenario: Profile run unknown test ID errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run missing.py:1` is invoked and discovery succeeds without that ID
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile tolerance matches test tolerance behavior
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol 0.01` runs a discovered assertion comparing `[1.0, {"x": 2.005}]` with `[1.0, {"x": 2.0}]`
- **THEN** the comparison passes because the nested float difference is within the default tolerance

#### Scenario: Profile invalid tolerance errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile Timeout Accounting
The `profile` command SHALL support `--timeout-ms <int>` and `--total-timeout-ms <int>` with the same positive-integer validation as `test`. Timeout failures after successful discovery MUST use `status` set to `fail`, include timed-out or not-executed selected test IDs in `failed`, preserve profile JSON output, and include timeout outcomes in aggregate runtime statistics. If `--memory` is provided, timeout outcomes MUST also be included in aggregate memory statistics.

#### Scenario: Profile per-test timeout contributes to failed results and runtime stats
- **WHEN** `profile <tests_dir> <solution_path> --lang python --timeout-ms 50` runs a discovered test whose entrypoint does not complete within 50 milliseconds
- **THEN** that test ID appears in `failed`, `status` is `fail`, and `runtime_ns` includes the timed-out execution in its aggregate statistics

#### Scenario: Profile total timeout fails remaining selected tests
- **WHEN** `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 50` runs multiple discovered tests and the total timeout expires before all selected tests execute
- **THEN** the timed-out test and every not-executed selected test ID appear in `failed`

#### Scenario: Profile timeout flags support selected tests
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run tests.py:2 --timeout-ms 50 --total-timeout-ms 100` is invoked and discovery includes additional test IDs
- **THEN** timeout accounting applies only to `tests.py:2`, and only `tests.py:2` appears in `passed` or `failed`

#### Scenario: Profile invalid timeout value errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --timeout-ms 0` or `--total-timeout-ms not-an-int` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile Memory Statistics
The `profile` command SHALL accept a `--memory` flag. When `--memory` is provided for a non-listing profile run, the output JSON MUST include `memory_kb` as an object containing numeric `mean` and `std` values in kilobytes. When `--memory` is omitted, the output JSON MUST omit `memory_kb`.

#### Scenario: Profile memory flag reports memory statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python --memory` runs selected measured tests
- **THEN** the command output includes `memory_kb` containing non-negative numeric `mean` and `std`

#### Scenario: Profile without memory flag omits memory statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python` runs selected measured tests without `--memory`
- **THEN** the command output does not contain `memory_kb`

#### Scenario: Warmup memory samples are excluded
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 2 --warmup 1 --memory` runs selected tests
- **THEN** `memory_kb` is calculated from measured executions only and excludes the warmup trial
