## 1. Language Registration and Workflow

- [x] 1.1 Extend the central language-to-tester mapping to include `cpp: tester.cpp` and `rust: tester.rs`.
- [x] 1.2 Update language validation, metadata validation, and unsupported-language preservation tests for the two new targets.
- [x] 1.3 Update `generate` so successful C++ and Rust generation writes metadata-bearing `tester.cpp` and `tester.rs` files.
- [x] 1.4 Update `test` so missing `tester.cpp` or `tester.rs` prints the standard error JSON, exits with code 2, and does not create the tester file.

## 2. Compiled Target Harness Generation

- [x] 2.1 Add a C++17+ tester template with metadata, case decoding hooks, solution inclusion or linking, result aggregation, and one-line JSON output.
- [x] 2.2 Add a Rust 1.70+ tester template with metadata, case decoding hooks, solution inclusion or module wiring, result aggregation, and one-line JSON output.
- [x] 2.3 Add temporary-build execution helpers that compile C++ and Rust testers with their single-file solutions without modifying files in `<tests_dir>`.
- [x] 2.4 Treat missing `g++`/`clang++` or `rustc`, compile failures before execution, and invalid tester metadata as standard test command errors.

## 3. Value Model and Expression Runtime

- [x] 3.1 Preserve explicit null values in encoded cases so expected `None` differs from an omitted optional field.
- [x] 3.2 Implement C++ runtime value decoding, deep equality, numeric tolerance, collection semantics, string helpers, sorting, membership, indexing, slicing, and mutation expression evaluation.
- [x] 3.3 Implement Rust runtime value decoding, deep equality, numeric tolerance, collection semantics, string helpers, sorting, membership, indexing, slicing, and mutation expression evaluation.
- [x] 3.4 Map nullable C++ solution-facing values through `std::optional<T>`/`std::nullopt` where a concrete target type can be inferred.
- [x] 3.5 Map nullable Rust solution-facing values through `Option<T>` with `Some(...)` and `None` where a concrete target type can be inferred.
- [x] 3.6 Detect Rust deque-specific cases and handle them according to the scoped Rust skip behavior rather than claiming full `collections.deque` parity.

## 4. Target Execution Semantics

- [x] 4.1 Invoke C++ single-file functions, no-argument class methods, and static methods named by the configured entrypoint where the harness can resolve them.
- [x] 4.2 Invoke Rust single-file functions named by the configured entrypoint through the generated harness module wiring.
- [x] 4.3 Implement C++ exception expectation support using `std::exception`-derived throws and message checks where available.
- [x] 4.4 Implement Rust exception-style expectation support using `catch_unwind` and `panic!` payload matching where available.
- [x] 4.5 Ensure stdout and stderr expectations are evaluated for C++ and Rust cases without changing the final single-line JSON output contract.

## 5. Tests and Verification

- [x] 5.1 Add generation and metadata tests proving `cpp` and `rust` produce `tester.cpp` and `tester.rs`.
- [x] 5.2 Add missing-tester tests for `--lang cpp` and `--lang rust`.
- [x] 5.3 Add compiled-target passing and failing tests for simple functions, nested values with `None`, numeric tolerance, string operations, sorting, and collection comparison.
- [x] 5.4 Add compiled-target tests for exception expectations and mutation-style cases.
- [x] 5.5 Add Rust-specific coverage for owned `String` map lookups and deque-skipped test coverage.
- [x] 5.6 Run the full Python test suite and focused CLI generate/test flows for Python, JavaScript, TypeScript, C++, and Rust when toolchains are available.
- [x] 5.7 Run `openspec status --change "add-cpp-rust-targets"` and confirm the change is apply-ready.
