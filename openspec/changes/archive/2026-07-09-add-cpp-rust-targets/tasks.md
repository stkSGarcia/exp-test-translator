## 1. Language Registry and Workflow

- [x] 1.1 Update `SUPPORTED_LANGS` and generated tester exclusion in `babel_code_goat.py` to include `cpp` -> `tester.cpp` and `rust` -> `tester.rs`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.2 Extend `generate_tester()` in `babel_code_goat.py` to dispatch to C++ and Rust tester renderers while preserving atomic tester writes. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.3 Extend `command_test()` in `babel_code_goat.py` so missing `tester.cpp` and `tester.rs` return the existing error result without creating tester files. [extends babel-code-goat-cli/add-babel-code-goat]

## 2. Compiled Tester Generation

- [x] 2.1 Add `cpp_tester_source()` in `babel_code_goat.py` that embeds the existing payload, supports C++17-or-later helper code, and invokes the single-file C++ solution entrypoint. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 2.2 Add `rust_tester_source()` in `babel_code_goat.py` that embeds the existing payload, supports Rust 1.70-or-later helper code, and invokes the single-file Rust solution entrypoint. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 2.3 Extend `extract_tester_payload()` in `babel_code_goat.py` to read the embedded payload from `tester.cpp` and `tester.rs` for stale-tester validation. [extends babel-code-goat-cli/add-babel-code-goat]

## 3. Value and Assertion Semantics

- [x] 3.1 Implement C++ payload decoding and comparison helpers for nulls, booleans, integers, floats, strings, vectors, maps, unordered maps, sets, decimal-like values, and nested tagged values in `babel_code_goat.py`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.2 Implement Rust payload decoding and comparison helpers for nulls, booleans, integers, floats, strings, vectors, hash maps, B-tree maps, hash sets, decimal-like values, owned `String` key lookups, and nested tagged values in `babel_code_goat.py`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.3 Carry expression evaluation, tolerance policies, stdout/stderr checks, exception-style assertions, loop sentinel tests, and mutation argument comparisons into both compiled tester renderers. [extends babel-code-goat-cli/support-single-call-test-traceability]
- [x] 3.4 Detect Rust deque cases during generation or tester execution and mark them skipped for Rust instead of emitting invalid Rust code. [extends babel-code-goat-cli/support-loop-construct-tests]

## 4. Compiled Execution

- [x] 4.1 Add C++ compile/run handling in `command_test()` using a temporary output binary and a C++17-or-later compiler invocation. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 4.2 Add Rust compile/run handling in `command_test()` using a temporary output binary and `rustc` compatible with Rust 1.70-or-later. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 4.3 Normalize compiler, runtime, malformed output, and payload validation failures to the existing `{status:error,passed:[],failed:[]}` behavior in `babel_code_goat.py`. [extends babel-code-goat-cli/add-babel-code-goat]

## 5. Tests

- [x] 5.1 Update `tests/test_babel_code_goat.py::test_supported_languages_generate_expected_files` to assert `tester.cpp` and `tester.rs` generation. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 5.2 Extend missing-tester tests in `tests/test_babel_code_goat.py` to cover `cpp` and `rust` without creating tester files. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 5.3 Add C++ execution tests in `tests/test_babel_code_goat.py` for passing/failing assertions, nested `None`/`null`, standard collections, sorting, strings, tolerance, exceptions, and mutation-style tests. [extends babel-code-goat-cli/support-mutation-style-tests]
- [x] 5.4 Add Rust execution tests in `tests/test_babel_code_goat.py` for passing/failing assertions, nested `None`/`null`, standard collections, sorting, strings, tolerance, exceptions, owned `String` map lookups, and mutation-style tests. [extends babel-code-goat-cli/support-mutation-style-tests]
- [x] 5.5 Add Rust deque skip coverage in `tests/test_babel_code_goat.py` and guard compiled execution tests when the required system compiler is unavailable.
- [ ] 5.6 Run `uv run pytest` and fix regressions across Python, JavaScript, TypeScript, C++, and Rust workflows.
