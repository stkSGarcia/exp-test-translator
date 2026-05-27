## MODIFIED Requirements

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

### Requirement: Unsupported language is an error
The `test` command SHALL reject any `--lang` value that is not `python`, `javascript`, `typescript`, `cpp`, or `rust`.

#### Scenario: Invalid lang rejected
- **WHEN** `test <solution> <tests_dir> --lang ruby` is run
- **THEN** stdout is `{"status":"error","passed":[],"failed":[]}` and process exits `2`

## ADDED Requirements

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
