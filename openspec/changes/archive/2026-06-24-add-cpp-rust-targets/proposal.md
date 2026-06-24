## Why

The harness currently generates and executes translated testers for Python, JavaScript, and TypeScript only, leaving compiled-language solutions outside the supported `generate -> test` workflow. Checkpoint 6 requires C++ and Rust to participate in the same value model and result contract, including explicit support for `None`/`null` anywhere values can appear.

## What Changes

- Add `--lang cpp` and `--lang rust` support to both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` files that execute discovered Python test cases against same-language C++ and Rust solutions.
- Require `test` to error with the existing JSON error contract when the selected C++ or Rust tester file is missing.
- Extend compiled target execution so all currently supported Python test values and comparison behaviors are represented, including nested `None`/`null`, rich containers, numeric tolerance, mutation-style tests, loop-expanded tests, stdout/stderr expectations, and exception-style tests.
- Document target-specific mappings for nullable values, collections, decimal precision, string operations, sorting, and exception-style checks.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `babel-code-goat-cli`: Expand the CLI language matrix, generated tester files, missing-tester preconditions, solution execution, and value/comparison semantics to include C++ and Rust targets.

## Impact

- Affects `babel_code_goat.py` language validation, tester filename mapping, generated tester source, target runner behavior, value encoding/decoding, comparison helpers, and error handling.
- Requires C++17-or-later and Rust 1.70-or-later execution paths for generated tests.
- Requires new focused and end-to-end tests for `generate` and `test` across `cpp` and `rust`, including missing tester errors and rich value parity.
