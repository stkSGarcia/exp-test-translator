## Why

The CLI currently treats Python, JavaScript, and TypeScript as the only generated and executable targets, leaving C++ and Rust solutions outside the same generate-to-test workflow. Adding these compiled targets now closes that gap while preserving the existing Python test authoring model and value semantics across all supported languages.

## What Changes

- Add `cpp` and `rust` as supported `--lang` values for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` files for C++ and Rust respectively.
- Require `test` to error when the expected compiled-target tester file is missing, matching the existing generate-before-test workflow.
- Extend target-language execution so C++ and Rust solutions can run the same discovered Python tests as interpreted targets.
- Preserve value-model parity for C++ and Rust, including `None`/`null` values anywhere in nested supported values.
- Support target-specific translations for collections, strings, sorting, numeric tolerance, and exception-style tests, while skipping Python `collections.deque` behavior for Rust where the standard translation cannot represent it.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `babel-code-goat-cli`: Expands the CLI language contract, tester-file contract, and cross-language execution requirements to include C++ and Rust with full supported-value parity.

## Impact

- Updates `babel_code_goat.py` language validation, tester filename mapping, metadata handling, code generation, and execution paths.
- Adds C++17+ tester generation using `std::optional`, standard containers, `long double`, string helpers, sorting, and exception handling.
- Adds Rust 1.70+ tester generation using `Option<T>`, standard collections, `f64`, string helpers, sorting, and `catch_unwind`/`panic!`-based exception checks.
- Adds regression tests for C++ and Rust generation, missing tester errors, supported values including nested nulls, and target-specific runtime behavior.
