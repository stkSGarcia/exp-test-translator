## ADDED Requirements

### Requirement: profile command requires pre-generated tester file
The `profile` sub-command SHALL error with JSON `{"status":"error","passed":[],"failed":[]}` and exit code `2` if the expected tester file for the given `--lang` does not exist in `<tests_dir>`. It MUST NOT create or modify any tester file.

#### Scenario: Missing tester exits with error JSON
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is run and `<tests_dir>/tester.py` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and the process exits `2`

### Requirement: profile command basic output format
The `profile` command SHALL print exactly one line to stdout: a JSON object containing at least `status`, `passed`, `failed`, and `runtime_ns`. `runtime_ns` SHALL be an object with keys `mean` (float, arithmetic mean of trial durations in nanoseconds) and `std` (float, population standard deviation of trial durations in nanoseconds). No other output SHALL appear on stdout.

#### Scenario: Successful profile with default flags
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is run with a valid tester and solution
- **THEN** stdout is a single JSON line containing `status`, `passed`, `failed`, and `runtime_ns` with `mean` and `std` keys

#### Scenario: runtime_ns values are non-negative numbers
- **WHEN** `profile` runs at least one trial
- **THEN** `runtime_ns.mean` and `runtime_ns.std` are non-negative numbers

### Requirement: profile command -n flag controls trial count
The `-n <trials>` flag (default `1`) SHALL set the number of timed execution trials. Statistics are computed over all `n` trials. Warmup runs are not counted in `n`.

#### Scenario: Single trial by default
- **WHEN** `profile` is run without `-n`
- **THEN** exactly one timed trial is executed and `runtime_ns.std` is `0.0`

#### Scenario: Multiple trials produce aggregated stats
- **WHEN** `profile -n 5` is run
- **THEN** five timed trials are executed and `runtime_ns` reflects all five

### Requirement: profile command --warmup flag excludes runs from statistics
The `--warmup <k>` flag (default `0`) SHALL cause `k` warm-up runs to execute before timed trials begin. Warm-up results are excluded from `runtime_ns` and `memory_kb` statistics. `k` MUST satisfy `k < n`; if not, `profile` SHALL exit non-zero with an error message to stderr.

#### Scenario: Warmup runs excluded from statistics
- **WHEN** `profile -n 3 --warmup 2` is run
- **THEN** five total subprocess invocations occur, but statistics are computed over the three timed trials only

#### Scenario: Warmup equal to n is rejected
- **WHEN** `profile -n 3 --warmup 3` is run
- **THEN** the process exits non-zero with an error message to stderr before executing any trial

#### Scenario: Warmup greater than n is rejected
- **WHEN** `profile -n 2 --warmup 5` is run
- **THEN** the process exits non-zero with an error message to stderr before executing any trial

### Requirement: profile command --memory flag adds memory statistics
When `--memory` is provided, the `profile` command SHALL additionally include `memory_kb` in the output JSON. `memory_kb` SHALL be an object with keys `mean` and `std` representing the arithmetic mean and population standard deviation of peak RSS memory usage across all timed trials, measured in kilobytes.

#### Scenario: memory_kb absent without --memory
- **WHEN** `profile` is run without `--memory`
- **THEN** the output JSON does NOT contain a `memory_kb` key

#### Scenario: memory_kb present with --memory
- **WHEN** `profile --memory` is run
- **THEN** the output JSON contains `memory_kb` with `mean` and `std` keys

#### Scenario: memory_kb values are non-negative
- **WHEN** `profile --memory` runs at least one trial
- **THEN** `memory_kb.mean` and `memory_kb.std` are non-negative numbers

### Requirement: profile command supports selection and timeout flags
The `profile` command SHALL accept `--list-tests`, `--run <id>`, `--timeout-ms <ms>`, `--total-timeout-ms <ms>`, and `--tol <float>` with the same semantics as the `test` command.

#### Scenario: --list-tests returns IDs without running trials
- **WHEN** `profile --list-tests` is run
- **THEN** the output JSON contains `status`, `passed` (all test IDs), `failed` (empty), and `runtime_ns` with `mean` and `std` both `0.0`

#### Scenario: --run filters to a single test ID
- **WHEN** `profile --run tests.py:1` is run
- **THEN** only the test with ID `tests.py:1` appears in `passed` or `failed`

#### Scenario: --timeout-ms applies per-test within each trial
- **WHEN** `profile --timeout-ms 100` is run and a test exceeds 100 ms
- **THEN** that test ID appears in `failed`

### Requirement: profile command includes timeout results in statistics
When tests timeout (via `--timeout-ms` or `--total-timeout-ms`), the timed-out trial's duration and memory SHALL still be included in the aggregated statistics. Timed-out test IDs SHALL appear in `failed`.

#### Scenario: Timed-out trial included in runtime_ns
- **WHEN** `profile -n 3` is run and one trial is cut short by `--total-timeout-ms`
- **THEN** the elapsed time of that trial is included in `runtime_ns` statistics and affected test IDs appear in `failed`

### Requirement: profile command exit codes
The `profile` command SHALL use the same exit codes as `test`:
- `0` when `status` is `"pass"`
- `1` when `status` is `"fail"`
- `2` when `status` is `"error"`

#### Scenario: All tests pass across all trials
- **WHEN** every trial completes with all tests passing
- **THEN** `status` is `"pass"` and exit code is `0`

#### Scenario: At least one test fails in any trial
- **WHEN** any trial produces a failing test
- **THEN** `status` is `"fail"` and exit code is `1`

#### Scenario: Missing tester file
- **WHEN** the tester file does not exist
- **THEN** `status` is `"error"` and exit code is `2`

### Requirement: profile passed and failed reflect final timed trial
The `passed` and `failed` arrays in the output SHALL reflect the test results from the last timed trial. If all `n` trials agree on pass/fail for a given test, the result is stable. If they differ, the last trial is authoritative.

#### Scenario: passed and failed come from last timed trial
- **WHEN** `profile -n 3` is run and the solution is deterministic
- **THEN** `passed` and `failed` match what a single `test` run would produce
