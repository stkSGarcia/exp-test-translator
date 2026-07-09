## Why

The translator currently needs compiled-language parity so Python test descriptions can drive generated C++ and Rust runner workflows with the same value coverage expected from interpreted targets. This is especially important for `None`/`null` values, which must round-trip through generated assertions and mutation-style tests without losing type intent.

## What Changes

- Add combined C++ and Rust target support for `generate` and `test` via `--lang cpp` and `--lang rust`.
- Generate single-file C++17+ solution/tester integration using standard containers, `std::optional<T>`/`std::nullopt`, `long double`, standard string operations, sorting, and exception assertions.
- Generate single-file Rust 1.70+ solution/tester integration using `Option<T>`, common collections, `f64`, standard string operations, sorting, and `catch_unwind`/`panic!` exception-style assertions.
- Extend value-model support for compiled targets to match Python-supported tests, including `None`/`null` anywhere in nested values.
- Ensure `test` fails clearly when the compiled target's generated tester file is missing (`tester.cpp` for C++, `tester.rs` for Rust).
- Skip Python `collections.deque` behavior for Rust-target tests when the translation cannot map those operations to the standard Rust target model.

## Capabilities

### New Capabilities
- `compiled-language-targets`: C++ and Rust generation/test support with compiled target value-model parity, null handling, collection/string/sort/exception behavior, and missing tester validation.

### Modified Capabilities
- None.

## Related Work

### Related Changes
- `add-babel-code-goat`: Established the root CLI, supported language selection, generated runner files, and predictable `generate` then `test` workflow. This change extends that foundation by adding compiled-language targets and target-specific tester validation.

### Related Specs
- `babel-code-goat-cli/add-babel-code-goat`: Defines the core CLI, target language argument, test discovery, runner generation, and generate/test workflow. This change reuses that interface for `--lang cpp` and `--lang rust`.
- `babel-code-goat-cli/support-single-call-test-traceability`: Defines traceable assertion constraints for calls under test. This change preserves that constraint while emitting equivalent assertions for C++ and Rust.
- `babel-code-goat-cli/support-loop-construct-tests`: Extends supported Python test constructs around loops and simple assignments. This change adapts those construct translations to compiled target syntax where value-model parity requires it.
- `babel-code-goat-cli/support-mutation-style-tests`: Extends discovery and execution for mutation-style tests. This change carries mutation behavior into generated C++/Rust harnesses, including nullable and nested value mutation cases.

## Impact

- CLI language validation and dispatch for `generate` and `test`.
- Test discovery and value serialization for C++ and Rust, especially nullable nested values.
- Generated runner/tester files: `tester.cpp` and `tester.rs`.
- Execution harnesses for C++17+ and Rust 1.70+ toolchains.
- Target-specific skip handling for Rust deque cases.
