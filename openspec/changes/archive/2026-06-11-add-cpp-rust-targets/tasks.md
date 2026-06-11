## 1. CLI and Tester Artifacts

- [x] 1.1 Add `cpp` and `rust` to the supported language map with `tester.cpp` and `tester.rs`.
- [x] 1.2 Update tester rendering so C++ and Rust generated files include valid metadata comments and target-appropriate scaffold content.
- [x] 1.3 Update generated tester detection so recursive discovery ignores `tester.cpp` and `tester.rs`.
- [x] 1.4 Add CLI tests for C++ and Rust language validation, generated tester filenames, unsupported-language preservation, and missing-tester error output.

## 2. Shared Compiled Runner Infrastructure

- [x] 2.1 Add temporary source, binary, compile, run, timeout, and cleanup helpers for compiled target execution.
- [x] 2.2 Add compiler discovery for C++ (`g++` or `clang++`) and Rust (`rustc`) while preserving standard pass/fail/error JSON behavior.
- [x] 2.3 Reuse existing `TestCase` JSON metadata for compiled targets, including actual expressions, tolerances, exception metadata, output expectations, and mutation argument references.
- [x] 2.4 Ensure tester files are read only by `test` and remain unchanged after C++ and Rust execution.

## 3. C++ Backend

- [x] 3.1 Generate C++17 harness code that includes or references a single-file solution and invokes the configured free function.
- [x] 3.2 Translate tagged values into C++ helpers/literals for `std::optional`, `std::vector`, maps, unordered maps, sets, `long double`, `std::string`, and nested `None` / `std::nullopt`.
- [x] 3.3 Implement C++ deep comparison, truthiness, numeric tolerance, primitive expression evaluation, string operations, sorting, and container semantics.
- [x] 3.4 Implement C++ stdout/stderr capture, mutation-style post-call checks, and exception-style checks with `try` / `catch`.
- [x] 3.5 Add C++ smoke and regression tests for free functions, nulls anywhere, rich values, mutation, output expectations, tolerance, and exception-style assertions.

## 4. Rust Backend

- [x] 4.1 Generate Rust 1.70+ harness code that includes or references a single-file solution and invokes the configured free function.
- [x] 4.2 Translate tagged values into Rust helpers/literals for `Option`, `Vec`, `HashMap`, `BTreeMap`, `HashSet`, `f64`, `String`, and nested `None`.
- [x] 4.3 Ensure generated `HashMap<String, V>` values support owned `String` key mutation patterns such as `get_mut(String::from("items"))`.
- [x] 4.4 Implement Rust deep comparison, truthiness, numeric tolerance, primitive expression evaluation, string operations, sorting, and non-deque container semantics.
- [x] 4.5 Implement Rust stdout/stderr capture, mutation-style post-call checks, and exception-style checks with `catch_unwind` and `panic!`.
- [x] 4.6 Add Rust smoke and regression tests for free functions, nulls anywhere, rich non-deque values, owned string map lookups, mutation, output expectations, tolerance, and panic-style assertions.

## 5. Rust Deque Scope

- [x] 5.1 Detect translated cases whose arguments, expected values, or expression metadata require Python `collections.deque` behavior.
- [x] 5.2 Exclude or skip Rust verification coverage for deque-dependent behavior without mapping it to `VecDeque`.
- [x] 5.3 Add tests documenting that deque-dependent Rust cases are skipped or excluded while C++ continues to support deque-equivalent behavior.

## 6. Verification

- [x] 6.1 Run the unit test suite with available local toolchains and ensure optional C++/Rust smoke tests skip cleanly when compilers are absent.
- [x] 6.2 Run `openspec status --change add-cpp-rust-targets` and confirm all required artifacts are apply-ready.
