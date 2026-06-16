## 1. Language Registry and Validation

- [x] 1.1 Update `babel_code_goat.py` starting at `SUPPORTED_LANGS`, `tester_filename()`, `generated_tester_filenames()`, and `read_tester_metadata()` so `cpp -> tester.cpp` and `rust -> tester.rs` are first-class supported languages. [extends `babel-code-goat-cli/add-babel-code-goat`]
- [x] 1.2 Update `tests/test_babel_code_goat.py` language validation coverage so `test_generate_language_validation_and_tester_names` and `test_missing_tester_errors_and_does_not_create_files` assert C++ and Rust filenames and metadata. [extends `babel-code-goat-cli/add-babel-code-goat`]

## 2. Native Tester Generation

- [x] 2.1 Add C++ tester rendering in `babel_code_goat.py` that emits C++17-or-newer `tester.cpp` code from discovered `TestCase` data and existing `case_to_json()`, `encode_value()`, and `encode_expr()` payloads. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 2.2 Add Rust tester rendering in `babel_code_goat.py` that emits Rust 1.70-or-newer `tester.rs` code from the same encoded case model, including `Option<T>`, `String`, map/set, numeric, string, sorting, and exception-style helper support. [extends `babel-code-goat-cli/support-single-call-traceability`]
- [x] 2.3 Add Rust deque detection and skip handling in `babel_code_goat.py` for encoded values or expressions that contain `deque`, leaving non-deque Rust cases generated normally. [extends `babel-code-goat-cli/support-mutation-directory-discovery`]

## 3. Native Test Execution

- [x] 3.1 Wire `generate` in `babel_code_goat.py` to call the C++ and Rust renderers and write `tester.cpp` or `tester.rs` atomically without changing existing Python, JavaScript, or TypeScript generation behavior.
- [x] 3.2 Add C++ compile/run support in `babel_code_goat.py` for `test <solution_path> <tests_dir> --lang cpp`, preserving the standard JSON result shape and status exit codes. [extends `babel-code-goat-cli/add-babel-code-goat`]
- [x] 3.3 Add Rust compile/run support in `babel_code_goat.py` for `test <solution_path> <tests_dir> --lang rust`, preserving the standard JSON result shape and status exit codes. [extends `babel-code-goat-cli/add-babel-code-goat`]
- [x] 3.4 Ensure `test` returns exactly `{"status":"error","passed":[],"failed":[]}` and does not create or modify tester files when `tester.cpp` or `tester.rs` is missing. [extends `babel-code-goat-cli/add-babel-code-goat`]

## 4. Regression Coverage

- [x] 4.1 Add generation tests in `tests/test_babel_code_goat.py` that inspect `tester.cpp` and `tester.rs` for metadata, target-native null markers, collection helpers, and expected entrypoint references.
- [x] 4.2 Add value parity tests in `tests/test_babel_code_goat.py` covering nested `None`, strings, lists, tuples, dictionaries, sets, decimals/floats, sorting, and exception expectations for C++ and Rust renderers.
- [x] 4.3 Add toolchain-gated C++ smoke tests in `tests/test_babel_code_goat.py` using `shutil.which()` to skip when no C++17 compiler is available.
- [x] 4.4 Add toolchain-gated Rust smoke tests in `tests/test_babel_code_goat.py` using `shutil.which("rustc")` to skip when Rust is unavailable.
- [x] 4.5 Add a Rust deque skip regression in `tests/test_babel_code_goat.py` proving deque-dependent Rust cases do not fail unrelated Rust cases.

## 5. Verification

- [x] 5.1 Run `python -m unittest tests.test_babel_code_goat` and confirm existing interpreted target behavior still passes.
- [x] 5.2 Run the C++ and Rust smoke tests where toolchains are installed, or confirm they are skipped by explicit toolchain guards.
- [x] 5.3 Run `openspec status --change "add-cpp-rust-targets"` and confirm the change is complete before implementation begins.
