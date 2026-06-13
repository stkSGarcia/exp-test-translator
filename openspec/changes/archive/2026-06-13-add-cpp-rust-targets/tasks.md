## 1. CLI Language Contract

- [x] 1.1 Add `cpp` and `rust` to the supported language registry with `tester.cpp` and `tester.rs` filenames.
- [x] 1.2 Ensure `generate` accepts `--lang cpp` and `--lang rust` and still rejects every unsupported language without creating or modifying tester files.
- [x] 1.3 Ensure `test` accepts `--lang cpp` and `--lang rust` and rejects every unsupported language with the standard error JSON and exit code 2.
- [x] 1.4 Extend missing-tester checks so `test --lang cpp` requires `tester.cpp` and `test --lang rust` requires `tester.rs`.
- [x] 1.5 Preserve tester metadata validation and tester-file immutability during `test` for all five target languages.

## 2. Shared Compiled Target Infrastructure

- [x] 2.1 Add target-aware tester rendering that can emit metadata plus compiled-target harness code for C++ and Rust.
- [x] 2.2 Reuse discovered `TestCase` records as the single source of truth for compiled-target case generation.
- [x] 2.3 Add shared value-shape analysis for nested nullability, containers, dictionary keys, sets, counters, default dictionaries, deques, decimals, strings, and numeric tolerances.
- [x] 2.4 Add target literal/rendering helpers that preserve Python `None` values anywhere in nested data for C++ optional/null semantics and Rust option semantics.
- [x] 2.5 Add compile/run orchestration that uses temporary build artifacts, detects unavailable compilers, captures stdout/stderr, and maps pre-execution preparation failures to standard command errors.

## 3. C++ Target

- [x] 3.1 Generate C++17-compatible `tester.cpp` code with required standard-library includes and embedded comparison/output helpers.
- [x] 3.2 Invoke single-file C++ solution functions named by the configured entrypoint.
- [x] 3.3 Support C++ representations for strings, vectors/sequences, maps, sets, counters, deques, default dictionaries, optional/null values, and `long double` decimal-like values.
- [x] 3.4 Implement C++ evaluation for supported primitive operations, string methods, sorting, membership, truthiness, equality/inequality, and tolerance comparisons.
- [x] 3.5 Implement C++ mutation-style test execution, raw stdout/stderr expectation checks, and raise-any/typed exception-style expectation checks.

## 4. Rust Target

- [x] 4.1 Generate Rust 1.70+-compatible `tester.rs` code with embedded comparison/output helpers and no Cargo project requirement.
- [x] 4.2 Invoke single-file Rust solution functions named by the configured entrypoint.
- [x] 4.3 Support Rust representations for strings, vectors/sequences, maps, sets, counters, default dictionaries, option/null values, and `f64` decimal-like values.
- [x] 4.4 Implement Rust evaluation for supported primitive operations, string methods, sorting, membership, truthiness, equality/inequality, and tolerance comparisons.
- [x] 4.5 Ensure generated Rust map access for `HashMap<String, V>` compiles when Python tests use string keys.
- [x] 4.6 Implement Rust mutation-style test execution, raw stdout/stderr expectation checks, and raise-any/typed panic expectation checks using `catch_unwind`.
- [x] 4.7 Mark Rust-specific repository regressions requiring Python `collections.deque` operations as skipped until a first-class `VecDeque` mapping exists.

## 5. Regression Coverage

- [x] 5.1 Add CLI tests for C++ and Rust generation, tester filenames, unsupported-language rejection, missing-tester errors, and tester preservation.
- [x] 5.2 Add C++ execution tests for direct assertions, nested `None`/optional values, containers, maps with non-string keys, sets, counters, deques, default dictionaries, decimals, strings, sorting, tolerances, mutation tests, raw output, and exception expectations.
- [x] 5.3 Add Rust execution tests for direct assertions, nested `None`/option values, containers, string-keyed maps, sets, counters, default dictionaries, decimals, strings, sorting, tolerances, mutation tests, raw output, and panic expectations.
- [x] 5.4 Guard compiled-target regression tests with compiler-availability checks for C++ and Rust toolchains.
- [x] 5.5 Run the repository test suite and `openspec status --change "add-cpp-rust-targets"` to confirm the change is apply-ready.
