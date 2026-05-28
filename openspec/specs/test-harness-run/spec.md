# Spec: test-harness-run

## Purpose

The `test` sub-command executes a pre-generated tester file against a solution and reports pass/fail results in a structured JSON format.

## Requirements

### Requirement: Test command requires pre-generated tester file
The `test` sub-command SHALL error if the expected tester file for the given `--lang` does not already exist in `<tests_dir>`. It MUST NOT create or modify any tester file.

#### Scenario: Missing tester.py for python
- **WHEN** `test <solution> <tests_dir> --lang python` is run and `<tests_dir>/tester.py` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}`, process exits `2`, and `tester.py` is not created

#### Scenario: Missing tester.js for javascript
- **WHEN** `test <solution> <tests_dir> --lang javascript` is run and `<tests_dir>/tester.js` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}`, process exits `2`, and `tester.js` is not created

#### Scenario: Missing tester.ts for typescript
- **WHEN** `test <solution> <tests_dir> --lang typescript` is run and `<tests_dir>/tester.ts` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}`, process exits `2`, and `tester.ts` is not created

#### Scenario: Missing tester.cpp for cpp
- **WHEN** `test <solution> <tests_dir> --lang cpp` is run and `<tests_dir>/tester.cpp` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}`, process exits `2`, and `tester.cpp` is not created

#### Scenario: Missing tester.rs for rust
- **WHEN** `test <solution> <tests_dir> --lang rust` is run and `<tests_dir>/tester.rs` does not exist
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}`, process exits `2`, and `tester.rs` is not created

### Requirement: Test command output format
The `test` command SHALL print exactly one line to stdout: a JSON object with exactly the keys `status`, `passed`, and `failed`. No other output SHALL appear on stdout.

- `status` SHALL be one of `"pass"`, `"fail"`, or `"error"`
- `passed` SHALL be an array of test IDs that passed
- `failed` SHALL be an array of test IDs that failed or could not run

#### Scenario: All tests pass
- **WHEN** all discovered tests pass
- **THEN** stdout is `{"status":"pass","passed":[<ids>],"failed":[]}` and process exits `0`

#### Scenario: Some tests fail
- **WHEN** at least one test fails
- **THEN** stdout is `{"status":"fail","passed":[<passing ids>],"failed":[<failing ids>]}` and process exits `1`

#### Scenario: No extra keys in output
- **WHEN** `test` runs successfully
- **THEN** the JSON object contains exactly the keys `status`, `passed`, and `failed`

### Requirement: Exit codes
The `test` command SHALL use the following exit codes:
- `0` when `status` is `"pass"`
- `1` when `status` is `"fail"`
- `2` when `status` is `"error"`

#### Scenario: Pass exit code
- **WHEN** all tests pass
- **THEN** exit code is `0`

#### Scenario: Fail exit code
- **WHEN** one or more tests fail
- **THEN** exit code is `1`

#### Scenario: Error exit code
- **WHEN** test discovery fails or tester file is missing
- **THEN** exit code is `2`

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

### Requirement: Test discovery failure output
If test discovery itself fails (e.g., the tester subprocess crashes before reporting any results), the `test` command SHALL output `{"status":"error","passed":[],"failed":[]}` and exit `2`.

#### Scenario: Tester subprocess crash
- **WHEN** the tester subprocess exits with an unhandled exception before writing results
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and exit code is `2`

### Requirement: Unsupported language is an error
The `test` command SHALL reject any `--lang` value that is not `python`, `javascript`, `typescript`, `cpp`, or `rust`.

#### Scenario: Invalid lang rejected
- **WHEN** `test <solution> <tests_dir> --lang ruby` is run
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

### Requirement: test command compiles before running for compiled targets
For `--lang cpp` and `--lang rust`, the `test` sub-command SHALL compile the tester file together with the solution file before executing the resulting binary. Compilation failure SHALL be treated as an error: stdout is `{"status":"error","passed":[],"failed":[]}` and the process exits `2`.

#### Scenario: C++ compile failure is an error
- **WHEN** `test <solution> <tests_dir> --lang cpp` is run and `g++` compilation fails
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

#### Scenario: Rust compile failure is an error
- **WHEN** `test <solution> <tests_dir> --lang rust` is run and `rustc` compilation fails
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

#### Scenario: Compiler not found is an error
- **WHEN** `test <solution> <tests_dir> --lang cpp` is run and `g++` is not on PATH
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

#### Scenario: Successful C++ compilation and run
- **WHEN** `test <solution> <tests_dir> --lang cpp` is run with valid `tester.cpp` and `solution.cpp`
- **THEN** the compilation succeeds, the binary runs, and test results are reported normally

#### Scenario: Successful Rust compilation and run
- **WHEN** `test <solution> <tests_dir> --lang rust` is run with valid `tester.rs` and `solution.rs`
- **THEN** the compilation succeeds, the binary runs, and test results are reported normally

### Requirement: Compiled binary temp files are cleaned up
The `test` sub-command SHALL write compiled binaries to a temporary location and clean them up after the run, regardless of whether the run succeeds or fails.

#### Scenario: Temp binary removed on success
- **WHEN** `test --lang cpp` completes successfully
- **THEN** no compiled binary remains in the temp directory

#### Scenario: Temp binary removed on run failure
- **WHEN** the compiled binary exits non-zero or crashes
- **THEN** no compiled binary remains in the temp directory

### Requirement: test command accepts --tol flag
The `test` sub-command SHALL accept an optional `--tol <float>` argument that sets the default absolute tolerance used for floating-point comparisons in generated testers. When `--tol` is not supplied, exact equality is used for floats (matching checkpoint 1 behavior).

The tolerance is applied to:
- `kind="eq"` and `kind="ne"` comparisons where the expected value is a float or Decimal, or a nested structure containing floats or Decimals
- It is NOT applied to `kind="truthy"`, `kind="falsy"`, or `kind="raises"` cases

Per-assert tolerance overrides (from `math.isclose`, `abs(a-b) < tol`) take precedence over the global `--tol`.

#### Scenario: --tol enables near-equal float comparison
- **WHEN** `test <solution> <tests_dir> --lang python --tol 0.01` is run and the solution returns a float within 0.01 of the expected value
- **THEN** the test case is reported as passed

#### Scenario: --tol failure when difference exceeds tolerance
- **WHEN** `test <solution> <tests_dir> --lang python --tol 0.001` is run and the solution returns a float differing from expected by more than 0.001
- **THEN** the test case is reported as failed

#### Scenario: Per-assert override takes precedence over --tol
- **WHEN** `test` is run with `--tol 0.5` and a specific test case was generated from `math.isclose(solve(x), y, abs_tol=0.001)`
- **THEN** that test case uses `abs_tol=0.001`, not `0.5`

#### Scenario: No --tol means exact float comparison
- **WHEN** `test` is run without `--tol` and the solution returns `3.14` but the expected value is `3.1400000001`
- **THEN** the test case is reported as failed (exact equality required)

#### Scenario: --tol applies to nested float in list
- **WHEN** `test` is run with `--tol 0.01` and the test asserts `solve() == [1.0, 2.0]` but the solution returns `[1.005, 1.995]`
- **THEN** the test case is reported as passed (tolerance applied recursively)

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
