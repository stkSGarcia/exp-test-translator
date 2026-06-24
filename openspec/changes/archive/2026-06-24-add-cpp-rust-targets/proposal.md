## Why

The CLI currently accepts only interpreted targets, leaving generated tests unusable for C++ and Rust solutions. Adding compiled targets broadens the tool to common contest and systems-language workflows while preserving the existing Python-authored test discovery model.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` for C++ and `tester.rs` for Rust from the same discovered Python tests used by the existing targets.
- Require `test` to fail with the standard error JSON when the selected compiled tester file is missing.
- Preserve the existing result JSON contract, pass/fail/error exit codes, test IDs, tolerance semantics, exception-style tests, stdout/stderr expectations, mutation tests, loop tests, and primitive expression evaluation for compiled targets.
- Extend runtime value encoding/comparison for compiled targets to cover the same supported values as Python, including nested `None`/null values anywhere arguments or expected values can appear.
- Skip Python `collections.deque` operation tests for Rust where no standard translation is available, while keeping other supported value behaviors aligned.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Extend supported target languages and generated tester behavior to include C++ and Rust with value-model parity.

## Impact

- Affects `babel_code_goat.py` language registry, generator selection, tester generation, and test execution paths.
- Adds C++17+ and Rust 1.70+ tester templates/runtime helpers.
- Expands tests in `tests/test_babel_code_goat.py` to cover C++/Rust generation, missing tester errors, null/None values, rich containers, tolerance, mutation, exceptions, and the Rust deque skip behavior.
- Requires local availability of a C++ compiler and Rust toolchain for end-to-end compiled target tests, with graceful skip behavior when unavailable.
