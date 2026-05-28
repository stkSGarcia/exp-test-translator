## ADDED Requirements

### Requirement: test command accepts --list-tests flag
The `test` sub-command SHALL accept an optional `--list-tests` flag. When present, the command SHALL output all discovered test IDs as passed without executing the solution, and exit `0`. The solution path argument is still syntactically required but SHALL NOT be opened or executed.

Output when `--list-tests` is used: `{"status":"pass","passed":[<all discovered IDs>],"failed":[]}`.

#### Scenario: --list-tests outputs all IDs and exits 0
- **WHEN** `test <solution> <tests_dir> --lang python --list-tests` is run and the tester file exists
- **THEN** stdout is `{"status":"pass","passed":[<all test IDs>],"failed":[]}` and process exits `0`

#### Scenario: --list-tests does not execute the solution
- **WHEN** `test <solution> <tests_dir> --lang python --list-tests` is run and `<solution>` does not exist
- **THEN** the command still exits `0` with all IDs in `passed` (solution is not opened)

#### Scenario: --list-tests with missing tester file is still an error
- **WHEN** `test <solution> <tests_dir> --lang python --list-tests` is run and `<tests_dir>/tester.py` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

### Requirement: test command accepts --run flag for single-test selection
The `test` sub-command SHALL accept an optional `--run <test_id>` argument. When present, only the test case with that exact ID SHALL be executed. All other test cases SHALL be omitted from both `passed` and `failed`. If the specified ID does not exist in the tester, the output SHALL be `{"status":"error","passed":[],"failed":[]}` and process exits `2`.

#### Scenario: --run executes only the specified test
- **WHEN** `test <solution> <tests_dir> --lang python --run tests.py:3` is run
- **THEN** only the test with ID `tests.py:3` appears in `passed` or `failed`, and no other IDs appear

#### Scenario: --run with unknown ID is an error
- **WHEN** `test <solution> <tests_dir> --lang python --run no_such_id` is run
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

#### Scenario: --run with passing test outputs status pass
- **WHEN** `--run <id>` is used and the selected test passes
- **THEN** stdout is `{"status":"pass","passed":[<id>],"failed":[]}` and process exits `0`

#### Scenario: --run with failing test outputs status fail
- **WHEN** `--run <id>` is used and the selected test fails
- **THEN** stdout is `{"status":"fail","passed":[],"failed":[<id>]}` and process exits `1`

### Requirement: test command accepts --timeout-ms for per-test timeout
The `test` sub-command SHALL accept an optional `--timeout-ms <int>` argument specifying a per-test wall-clock time limit in milliseconds. A test that does not complete within this limit SHALL be cancelled and its ID placed in `failed`. Tests that complete within the limit are unaffected.

#### Scenario: --timeout-ms causes slow test to fail
- **WHEN** `test <solution> <tests_dir> --lang python --timeout-ms 100` is run and a test takes longer than 100 ms
- **THEN** that test ID appears in `failed`

#### Scenario: --timeout-ms does not affect fast tests
- **WHEN** `test <solution> <tests_dir> --lang python --timeout-ms 5000` is run and all tests complete within 5000 ms
- **THEN** all tests are evaluated normally and not moved to `failed` due to timeout

### Requirement: test command accepts --total-timeout-ms for run-wide timeout
The `test` sub-command SHALL accept an optional `--total-timeout-ms <int>` argument specifying a total wall-clock time budget in milliseconds for the entire test run. When the budget expires, any test IDs not yet recorded in `passed` or `failed` SHALL be placed in `failed`. The process SHALL exit `1` (at least one failure) unless no tests were discovered (in which case it exits `2`).

#### Scenario: --total-timeout-ms causes unrun tests to appear in failed
- **WHEN** `test <solution> <tests_dir> --lang python --total-timeout-ms 50` is run and execution time exceeds 50 ms before all tests complete
- **THEN** all test IDs not yet recorded appear in `failed`

#### Scenario: --total-timeout-ms does not affect runs that finish in time
- **WHEN** `test <solution> <tests_dir> --lang python --total-timeout-ms 60000` is run and all tests complete within 60 seconds
- **THEN** the run proceeds normally and exit code reflects actual pass/fail

## MODIFIED Requirements

### Requirement: Coverage rule — all discovered tests accounted for
If tests are discoverable, every discovered test ID SHALL appear exactly once in either `passed` or `failed`. Tests that could not be executed for any reason SHALL be listed in `failed`. This includes tests that timed out (per `--timeout-ms`) or were not reached before the total-run budget expired (per `--total-timeout-ms`). When `--run <id>` is active, only that single ID is subject to the coverage rule; all other IDs are intentionally excluded and do not need to appear.

#### Scenario: Unexecuted test listed as failed
- **WHEN** a test is discovered but fails to execute due to a runtime error in the solution
- **THEN** that test ID appears in `failed`, not silently omitted

#### Scenario: No duplicate IDs
- **WHEN** `test` runs with any result
- **THEN** no test ID appears in both `passed` and `failed`, and no ID appears more than once in either array

#### Scenario: Timed-out test appears in failed
- **WHEN** a test exceeds the per-test `--timeout-ms` limit
- **THEN** that test ID appears in `failed`

#### Scenario: Not-yet-executed test appears in failed after total timeout
- **WHEN** `--total-timeout-ms` expires before a test has been executed
- **THEN** that test ID appears in `failed`

#### Scenario: --run excludes other IDs from coverage
- **WHEN** `--run tests.py:3` is passed and 10 tests exist
- **THEN** only `tests.py:3` appears in `passed` or `failed`; the remaining 9 IDs do not appear
