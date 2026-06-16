## 1. Language Registry and CLI Contract

- [x] 1.1 Update `babel_code_goat.py` `SUPPORTED_LANGS`, `tester_filename`, and metadata validation to include `cpp -> tester.cpp` and `rust -> tester.rs`. [extends babel-code-goat-cli]
- [x] 1.2 Update `tests/test_babel_code_goat.py` language validation and missing-tester coverage to assert C++ and Rust tester filenames, unsupported-language preservation, and standard error JSON behavior. [extends babel-code-goat-cli]
- [x] 1.3 Verify `generate` failure paths in `babel_code_goat.py` preserve existing `tester.cpp` and `tester.rs` contents just like existing tester files. [extends babel-code-goat-cli]

## 2. Native Tester Rendering

- [x] 2.1 Refactor `babel_code_goat.py` `render_tester` into shared metadata rendering plus language-specific body renderers for Python, JavaScript, TypeScript, C++, and Rust. [extends babel-code-goat-cli]
- [x] 2.2 Add C++ value and type rendering helpers in `babel_code_goat.py` for nested `None`, booleans, integers, floats, strings, lists/tuples, maps, sets, counters, deques, default dictionaries, decimals as `long double`, and structural comparisons. [extends babel-code-goat-cli]
- [x] 2.3 Add Rust value and type rendering helpers in `babel_code_goat.py` for nested `None`, booleans, integers, floats, strings, vectors, maps, sets, counters, default dictionaries, decimals as `f64`, structural comparisons, and owned `String` map lookups. [extends babel-code-goat-cli]
- [x] 2.4 Add expression rendering in `babel_code_goat.py` for native string methods, sorting, numeric tolerance comparisons, truthy/not assertions, mutation-style actual expressions, stdout/stderr expectations, and exception-style tests. [extends babel-code-goat-cli]
- [x] 2.5 Implement Rust deque handling in `babel_code_goat.py` so unsupported `collections.deque` cases are marked skipped in generated Rust tests without failing generation. [extends babel-code-goat-cli]

## 3. Native Execution

- [x] 3.1 Add C++ `test` execution in `babel_code_goat.py` that compiles a single solution file with `tester.cpp` using C++17 or later, runs the binary, and maps compile/runtime failures to the existing JSON output contract. [extends babel-code-goat-cli]
- [x] 3.2 Add Rust `test` execution in `babel_code_goat.py` that compiles a single solution file with `tester.rs` using `rustc`, runs the binary, and maps compile/runtime failures to the existing JSON output contract. [extends babel-code-goat-cli]
- [x] 3.3 Keep native compiler diagnostics off stdout in `babel_code_goat.py` so `test` always prints exactly one JSON line. [extends babel-code-goat-cli]

## 4. Verification

- [x] 4.1 Add generated-source assertions in `tests/test_babel_code_goat.py` for C++ `std::optional`, `std::nullopt`, STL containers, `long double`, string methods, sorting, and exception handling. [extends babel-code-goat-cli]
- [x] 4.2 Add generated-source assertions in `tests/test_babel_code_goat.py` for Rust `Option`, `None`, `Vec`, `HashMap`, `BTreeMap`, `HashSet`, `f64`, owned `String` lookups, string methods, sorting, `catch_unwind`, and deque skips. [extends babel-code-goat-cli]
- [x] 4.3 Add compiler-gated integration tests in `tests/test_babel_code_goat.py` for a passing C++ solution and a passing Rust solution, skipped when the required compiler is unavailable. [extends babel-code-goat-cli]
- [x] 4.4 Run `python -m unittest tests/test_babel_code_goat.py` and `openspec status --change "add-cpp-rust-targets"` to confirm the implementation and proposal artifacts remain valid. [extends babel-code-goat-cli]
