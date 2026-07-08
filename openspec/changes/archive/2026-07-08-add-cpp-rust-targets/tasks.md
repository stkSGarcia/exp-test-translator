## 1. Language Registration

- [x] 1.1 Update `SUPPORTED_LANGS` in `babel_code_goat.py` with `cpp` -> `tester.cpp` and `rust` -> `tester.rs`. [extends python-test-discovery/add-mutation-style-test-discovery]
- [x] 1.2 Verify `GENERATED_TESTERS` excludes `tester.cpp` and `tester.rs` from discovery without adding separate filtering logic in `babel_code_goat.py`. [extends python-test-discovery/add-mutation-style-test-discovery]
- [x] 1.3 Extend `tests/test_babel_code_goat.py::test_supported_languages_generate_expected_files` to assert C++ and Rust tester filenames are generated.

## 2. Compiled Tester Generation

- [x] 2.1 Add `cpp_tester_source()` in `babel_code_goat.py` that embeds the existing `TestCase.to_jsonable()` payload and emits a self-contained C++17 harness for single-file C++ solutions.
- [x] 2.2 Add `rust_tester_source()` in `babel_code_goat.py` that embeds the existing `TestCase.to_jsonable()` payload and emits a self-contained Rust 1.70+ harness for single-file Rust solutions.
- [x] 2.3 Route `generate_tester()` in `babel_code_goat.py` to the new C++ and Rust source functions while preserving atomic tester file writes.
- [x] 2.4 Add recursive Rust deque detection in `babel_code_goat.py` so Rust generation omits or skips deque-dependent cases without dropping non-deque cases.

## 3. Value and Assertion Runtime

- [x] 3.1 Implement C++ generated helpers for primitive values, nested lists, maps, unordered maps, sets, counters, decimals as `long double`, strings, `std::optional<T>` nulls, unordered comparison, numeric tolerance, expression evaluation, mutation variables, stdout/stderr expectations, and exception matching.
- [x] 3.2 Implement Rust generated helpers for primitive values, nested `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, `HashSet<T>`, decimals as `f64`, strings, `Option<T>` nulls, unordered comparison, numeric tolerance, expression evaluation, mutation variables, stdout/stderr expectations, and `catch_unwind` panic matching.
- [x] 3.3 Ensure Rust map lookup generation handles owned `String` keys, including `get_mut(String::from("items"))` style cases when mutation tests require mutable map access.

## 4. Compiled Test Execution

- [x] 4.1 Extend `extract_tester_payload()` in `babel_code_goat.py` to recover embedded payloads from `tester.cpp` and `tester.rs`.
- [x] 4.2 Add a C++ compile-and-run path in `command_test()` using a temporary build directory and a C++17-or-newer compiler, returning the standard error JSON on compiler or process failures.
- [x] 4.3 Add a Rust compile-and-run path in `command_test()` using a temporary build directory and `rustc`, returning the standard error JSON on compiler or process failures.
- [x] 4.4 Preserve the existing missing tester check in `command_test()` so absent `tester.cpp` or `tester.rs` returns `{"status":"error","passed":[],"failed":[]}` with exit code `2` and does not generate a tester.

## 5. Test Coverage

- [x] 5.1 Add missing tester tests in `tests/test_babel_code_goat.py` for `test --lang cpp` and `test --lang rust`.
- [x] 5.2 Add C++ and Rust pass/fail execution tests covering single-file function solutions and the standard JSON result envelope.
- [x] 5.3 Add C++ and Rust value parity tests covering nested `None`/`null`, strings, booleans, integers, floats, decimals, lists/tuples, dictionaries/maps, sets, counters, and defaultdict-style mappings.
- [x] 5.4 Add C++ and Rust expression and mutation-style tests that reuse discovered path-qualified ids from Python test discovery. [extends python-test-discovery/add-mutation-style-test-discovery]
- [x] 5.5 Add C++ exception and Rust panic expectation tests, including message matching where supported by the generated tester.
- [x] 5.6 Add a Rust deque test showing deque-dependent cases are skipped or omitted while non-deque cases still execute.

## 6. Verification

- [ ] 6.1 Run the focused compiled-target tests in `tests/test_babel_code_goat.py`.
- [ ] 6.2 Run the full Python test suite for the repository.
- [ ] 6.3 Manually verify `generate --lang cpp`, `generate --lang rust`, `test --lang cpp`, and `test --lang rust` commands against small temporary fixtures when local compilers are available.
