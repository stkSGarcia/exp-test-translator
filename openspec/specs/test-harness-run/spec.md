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
The `test` command SHALL reject any `--lang` value that is not `python`, `javascript`, or `typescript`.

#### Scenario: Invalid lang rejected
- **WHEN** `test <solution> <tests_dir> --lang ruby` is run
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`
