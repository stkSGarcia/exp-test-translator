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
If tests are discoverable, every discovered test ID SHALL appear exactly once in either `passed` or `failed`. Tests that could not be executed for any reason SHALL be listed in `failed`.

#### Scenario: Unexecuted test listed as failed
- **WHEN** a test is discovered but fails to execute due to a runtime error in the solution
- **THEN** that test ID appears in `failed`, not silently omitted

#### Scenario: No duplicate IDs
- **WHEN** `test` runs with any result
- **THEN** no test ID appears in both `passed` and `failed`, and no ID appears more than once in either array

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
