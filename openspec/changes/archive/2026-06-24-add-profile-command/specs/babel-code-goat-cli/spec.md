## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` and `profile` commands MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate`, `test`, or `profile` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Profile accepts default tolerance
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

## ADDED Requirements

### Requirement: Profile command requires generated tester
The `profile` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `profile` command MUST NOT create or modify any tester file.

#### Scenario: Missing generated tester errors
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` and `<tests_dir>/tester.py` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile does not create testers
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang javascript` and `<tests_dir>/tester.js` is missing
- **THEN** the command exits non-zero and `<tests_dir>/tester.js` is not created

### Requirement: Profile command supports test selection
The `profile` command SHALL support `--list-tests` and `--run <test-id>` with the same semantics as `test`. Listing tests MUST discover and report test IDs without executing the solution or producing aggregate profiling statistics.

#### Scenario: Profile lists tests without profiling
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests` after successful generation
- **THEN** stdout contains one JSON line with only `status`, `passed`, and `failed`, `status` is `pass`, `passed` contains all discovered test IDs, and `failed` is empty

#### Scenario: Profile runs selected test only
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:2 -n 3`
- **THEN** each measured trial executes only `tests.py:2` and the JSON result reports pass/fail status for that selected test only

#### Scenario: Profile rejects unknown selected test
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run missing.py:1`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile command reports runtime statistics
The `profile` command SHALL run selected tests `-n <trials>` measured times with a default of `1` measured trial. The command SHALL print exactly one JSON line containing at least `status`, `passed`, `failed`, and `runtime_ns`, where `runtime_ns` is an object with numeric `mean` and `std` fields computed across measured trials. The command MUST exit `0` for `pass`, `1` for `fail`, and `2` for `error`.

#### Scenario: Passing profile reports runtime aggregate
- **WHEN** every selected test passes across one measured profiling trial
- **THEN** stdout contains one JSON line with `status` set to `pass`, all selected test IDs in `passed`, no test IDs in `failed`, and numeric `runtime_ns.mean` and `runtime_ns.std` values

#### Scenario: Failing profile reports runtime aggregate
- **WHEN** at least one selected test fails during profiling and no harness error prevents reporting
- **THEN** stdout contains one JSON line with `status` set to `fail`, failing test IDs in `failed`, and numeric `runtime_ns.mean` and `runtime_ns.std` values, and the command exits `1`

#### Scenario: Profile trial count controls measured executions
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 5`
- **THEN** the aggregate runtime statistics are computed from exactly five measured executions of the selected tests

### Requirement: Profile warmup runs are excluded from statistics
The `profile` command SHALL support `--warmup <k>` to run selected tests before measured trials. The warmup count MUST satisfy `k < n`. Warmup executions MUST affect pass/fail reporting if they expose a harness error, but successful warmup measurements MUST be excluded from runtime and memory statistics.

#### Scenario: Warmup precedes measured trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 2`
- **THEN** the selected tests are executed for two warmup runs before the three measured runs

#### Scenario: Warmup is excluded from aggregate statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 2`
- **THEN** `runtime_ns.mean` and `runtime_ns.std` are computed from the three measured runs only

#### Scenario: Invalid warmup count is rejected
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile command optionally reports memory statistics
The `profile` command SHALL support `--memory`. When `--memory` is provided, the JSON output MUST include `memory_kb` as an object with numeric `mean` and `std` fields computed across measured trials. When `--memory` is omitted, `memory_kb` MUST be omitted.

#### Scenario: Memory profiling is requested
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory -n 2`
- **THEN** stdout contains one JSON line with numeric `memory_kb.mean` and `memory_kb.std` values

#### Scenario: Memory profiling is omitted by default
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 2` without `--memory`
- **THEN** the JSON output does not include a `memory_kb` key

### Requirement: Profile command honors timeout flags in aggregates
The `profile` command SHALL support `--timeout-ms <milliseconds>` and `--total-timeout-ms <milliseconds>` with the same selection semantics as `test`. When a timeout occurs during a measured trial, the timed-out result MUST be included in aggregate runtime statistics, the timed-out test IDs MUST appear in `failed`, and profiling MUST still print a JSON result unless a harness error prevents reporting.

#### Scenario: Per-test timeout is included in profile aggregate
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 250 -n 3` and one selected test times out in a measured trial
- **THEN** stdout contains a JSON result with `status` set to `fail`, the timed-out test ID in `failed`, and runtime statistics that include the timeout measurement

#### Scenario: Total timeout is included in profile aggregate
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 250 -n 3` and the selected run exceeds the total timeout in a measured trial
- **THEN** stdout contains a JSON result with `status` set to `fail`, all selected IDs not completed before timeout in `failed`, and runtime statistics that include the timeout measurement

#### Scenario: Timeout memory data is included when requested
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory --timeout-ms 250 -n 3` and a measured trial times out
- **THEN** the timed-out trial contributes to both `runtime_ns` and `memory_kb` aggregate statistics
