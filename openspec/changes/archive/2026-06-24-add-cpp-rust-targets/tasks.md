## 1. Language Registry and Workflow

- [x] 1.1 Add `cpp` and `rust` entries to the supported language metadata with `tester.cpp` and `tester.rs` filenames.
- [x] 1.2 Update CLI language validation so `generate` and `test` accept only `python`, `javascript`, `typescript`, `cpp`, and `rust`.
- [x] 1.3 Extend failed-generation preservation checks so existing `tester.cpp` and `tester.rs` files are not modified on discovery/generation failure.
- [x] 1.4 Extend `test` missing-tester checks so missing `tester.cpp` or `tester.rs` returns the standard error JSON and exit code `2`.

## 2. Shared Value and Type Support

- [x] 2.1 Audit normalized value handling for `None` and ensure nulls are preserved anywhere inside arguments, expected values, dictionary keys where supported, and nested containers.
- [x] 2.2 Add shared type-inference helpers for compiled target call signatures, including optional wrappers when any observed value is null.
- [x] 2.3 Ensure deep comparison metadata remains sufficient for maps, sets, counters, deques, defaultdicts, decimals, tolerance-aware numbers, and primitive expressions.
- [x] 2.4 Add harness error handling that preserves the one-line result JSON contract for type inference, compile, and runtime harness failures.

## 3. C++ Target

- [x] 3.1 Implement C++17 tester generation that emits `tester.cpp` as a self-contained file with discovered cases and runtime helpers.
- [x] 3.2 Generate idiomatic C++ calls using `std::optional<T>`/`std::nullopt`, `std::string`, `std::vector`, map/set types, `long double`, and `std::sort` where required.
- [x] 3.3 Implement C++ structural comparison, tolerance handling, stdout/stderr capture, primitive expression evaluation, mutation assertions, loop results, and result JSON reporting.
- [x] 3.4 Implement C++ exception-style test handling with `try`/`catch (const std::exception& e)` and message matching.
- [x] 3.5 Implement C++ compile-and-run orchestration in `test`, preferring an available C++17 compiler and mapping compile failures to the standard error result.

## 4. Rust Target

- [x] 4.1 Implement Rust 1.70+ tester generation that emits `tester.rs` as a self-contained file with discovered cases and runtime helpers.
- [x] 4.2 Generate idiomatic Rust calls using `Option<T>`, `Some(...)`, `None`, `String`, `Vec`, `HashMap`, `BTreeMap`, `HashSet`, and `f64` where required.
- [x] 4.3 Ensure generated Rust supports owned `String` lookup keys for `HashMap<String, V>` solution workflows.
- [x] 4.4 Implement Rust structural comparison, tolerance handling, stdout/stderr capture where practical, primitive expression evaluation, mutation assertions, loop results, and result JSON reporting.
- [x] 4.5 Implement Rust exception-style test handling with `catch_unwind` and `panic!` message matching.
- [x] 4.6 Implement Rust compile-and-run orchestration in `test`, mapping compile failures to the standard error result.
- [x] 4.7 Add Rust-specific skip handling in the pytest suite for cases that require Python `collections.deque` behavior.

## 5. Test Coverage and Validation

- [x] 5.1 Update existing language-generation tests to include `cpp` and `rust` tester filenames.
- [x] 5.2 Add missing-tester tests for `tester.cpp` and `tester.rs`.
- [x] 5.3 Add cross-target parity tests for nested nulls, supported containers, numeric tolerance, decimals, sets, counters, maps, primitive expressions, mutation tests, loops, and exception-style tests.
- [x] 5.4 Add C++ and Rust compile failure tests that verify strict stdout JSON and exit code `2`.
- [x] 5.5 Add compiler/toolchain availability probes so end-to-end compiled target tests skip cleanly when `g++`/`clang++` or `rustc` is unavailable.
- [x] 5.6 Run the full Python test suite and targeted compiled-target tests, then fix any regressions.
