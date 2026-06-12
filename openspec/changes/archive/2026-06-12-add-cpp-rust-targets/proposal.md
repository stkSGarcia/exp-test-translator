## Why

The CLI currently supports only Python, JavaScript, and TypeScript tester generation and execution, leaving C++ and Rust solutions outside the same generate-to-test workflow. Checkpoint 6 expands the target surface while requiring the compiled targets to preserve the value-model behavior already covered by interpreted targets, including `None`/null values.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` for C++ and Rust targets.
- Require `test` to fail with the standard error JSON and exit code 2 when the expected C++ or Rust tester file is missing.
- Extend value serialization, comparison, primitive operations, stdout/stderr checks, exception expectations, loops, and mutation-style test behavior to C++ and Rust targets.
- Represent nullable values in generated C++ with `std::optional<T>` / `std::nullopt` and in generated Rust with `Option<T>` / `None`.
- Map supported Python value types to idiomatic C++17+ and Rust 1.70+ constructs, while explicitly skipping Python `collections.deque` behavior for Rust where translation cannot map it reliably.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Add C++ and Rust as supported target languages and extend tester generation, tester presence checks, and allowed-value parity requirements for those targets.

## Impact

- Affects CLI language validation, tester filename resolution, `generate` output, and `test` preflight checks.
- Affects Python test discovery translation into C++ and Rust tester programs.
- Affects value-model serialization and comparison for nullable values, nested containers, numeric tolerances, output expectations, and exception-style tests.
- May require invoking C++ and Rust toolchains during `test` for compiled target execution.
