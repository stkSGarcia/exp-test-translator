## 1. Contract Tests

- [x] 1.1 Update `tests/test_babel_code_goat.py` language validation coverage so `cpp -> tester.cpp` and `rust -> tester.rs` generate successfully and unsupported languages preserve all tester files. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.2 Update `tests/test_babel_code_goat.py` missing-tester coverage so `test` returns exactly `{"status":"error","passed":[],"failed":[]}` with exit code 2 when `tester.cpp` or `tester.rs` is absent. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.3 Add `tests/test_babel_code_goat.py` compiled-target smoke tests for C++ and Rust single-file function solutions using generated testers. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.4 Add `tests/test_babel_code_goat.py` value-parity tests for nested `None`/null values, lists/tuples, maps/dicts, sets, strings, sorting, numeric tolerance, and exception-style assertions on C++ and Rust. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.5 Add `tests/test_babel_code_goat.py` Rust deque skip-marker coverage that verifies guarded deque tests are not executed for `--lang rust` while other targets retain normal deque behavior. [extends babel-code-goat-cli/add-babel-code-goat]

## 2. Language Registry and Discovery

- [x] 2.1 Update `babel_code_goat.py` `SUPPORTED_LANGS`, `tester_filename()`, `is_generated_tester_path()`, and metadata validation to include `cpp` and `rust` filenames. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 2.2 Update `babel_code_goat.py` `command_generate()` and `command_test()` to pass the selected language into discovery and preserve current error JSON and exit-code behavior. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 2.3 Extend `babel_code_goat.py` discovery to recognize only explicit Rust deque skip markers and filter those cases for `target_lang="rust"` without changing test IDs for other targets. [extends babel-code-goat-cli/support-single-call-traceability]
- [x] 2.4 Verify `babel_code_goat.py` generation failure paths still write no tester file and leave existing `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, and `tester.rs` contents unchanged. [extends babel-code-goat-cli/add-babel-code-goat]

## 3. Compiled Tester Generation

- [x] 3.1 Extend `babel_code_goat.py` `render_tester()` to append C++17 tester source for `cpp` while keeping the metadata marker readable by `read_tester_metadata()`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.2 Extend `babel_code_goat.py` `render_tester()` to append Rust 1.70-compatible tester source for `rust` while keeping the metadata marker readable by `read_tester_metadata()`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.3 Add C++ helper rendering in `babel_code_goat.py` for `std::optional`, standard containers, `long double`, `std::string` operations, `std::sort()`, structural equality, truthiness, stdout/stderr capture, and `std::exception` matching. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.4 Add Rust helper rendering in `babel_code_goat.py` for `Option`, `Vec`, `HashMap`, `BTreeMap`, `HashSet`, owned `String` lookups, `f64`, supported `String` methods, `.sort()`/`.sort_by()`, structural equality, truthiness, stdout/stderr capture, and `catch_unwind`. [extends babel-code-goat-cli/add-babel-code-goat]

## 4. Compiled Execution

- [x] 4.1 Add `babel_code_goat.py` C++ execution support that compiles the generated `tester.cpp` with the single solution file using a C++17-or-newer compiler and runs all discovered cases once per `test` invocation. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 4.2 Add `babel_code_goat.py` Rust execution support that compiles the generated `tester.rs` with the single solution file using `rustc` and runs all discovered cases once per `test` invocation. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 4.3 Update `babel_code_goat.py` `execute_case()` and `aggregate_results()` dispatch so compiled targets preserve loop-case handling and standard passed/failed aggregation. [extends babel-code-goat-cli/add-loop-as-test-support]
- [x] 4.4 Ensure missing compilers, compile errors, runtime errors, and unsupported compiled-target shapes result in failed discovered tests rather than the missing-tester error JSON. [extends babel-code-goat-cli/add-babel-code-goat]

## 5. Verification

- [x] 5.1 Run `python -m unittest tests.test_babel_code_goat` and fix regressions in existing Python, JavaScript, and TypeScript behavior.
- [x] 5.2 Run focused manual CLI checks for `generate` and `test` with `--lang cpp` and `--lang rust`, including missing tester files and passing/failing solution cases.
- [x] 5.3 Run `openspec status --change "add-cpp-rust-targets"` and confirm all required artifacts are complete before applying the change.
