## Why

The CLI currently translates and runs tests only for Python, JavaScript, and TypeScript, which leaves C++ and Rust solutions outside the same generate-to-test workflow. Adding these compiled targets closes that gap while requiring the rich Python value model, especially `None`/`null`, to remain consistent across target languages.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` files and require those files to exist before `test` runs for the corresponding target.
- Execute C++17-or-newer and Rust 1.70-or-newer single-file solutions through target-specific tester programs.
- Preserve the supported Python test value model for C++ and Rust targets, including nested `None`/`null` values, structural equality, container semantics, numeric tolerance behavior, raw output expectations, mutation-style tests, and exception-style tests.
- Map supported Python value and operation forms to idiomatic C++ and Rust representations, including `std::optional<T>` / `Option<T>` for nullability.
- Skip Python `collections.deque`-dependent tests for Rust target execution while preserving discovery and execution behavior for other targets.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend CLI language validation, tester generation, tester-file requirements, target execution, supported value mapping, and language-specific runtime behavior for C++ and Rust.

## Impact

- Updates `babel_code_goat.py` command validation, tester generation, test execution dispatch, and generated runner code.
- Adds compiler/runtime integration for C++ and Rust where local toolchains are available.
- Expands tests to cover C++ and Rust generation, missing tester errors, null propagation, rich values, mutation behavior, output expectations, tolerance handling, and exception-style expectations.
- Keeps the existing one-line JSON `test` output contract and exit-code semantics unchanged.
