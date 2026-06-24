## Why

The CLI currently supports only interpreted targets, which leaves generated test harnesses unavailable for C++ and Rust solutions. Adding both compiled targets now brings the tool in line with common coding challenge workflows while preserving the Python-authored test discovery model.

## What Changes

- Add `cpp` and `rust` as supported `--lang` values for both `generate` and `test`.
- Generate `tester.cpp` for C++ and `tester.rs` for Rust from discovered Python tests.
- Require `test` to find the generated tester file for the selected compiled target before running, returning the standard error JSON and exit code when it is missing.
- Extend generated testers so C++ and Rust support the same allowed value model and comparison behaviors as existing interpreted targets, including `None`/`null` values at any nesting depth.
- Support compiled-target execution with language-appropriate build/run steps while preserving the existing single-line JSON result contract.
- Skip Python `collections.deque` behavior for Rust targets because the standard translation does not map those tests to Rust `VecDeque`.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Expands supported target languages and value-model requirements for generated tester execution.

## Impact

- Affects `babel_code_goat.py` language metadata, tester generation, target execution, and value serialization/rendering paths.
- Adds C++17-or-newer and Rust 1.70-or-newer tester expectations, including build-tool invocation through system compilers.
- Adds or updates tests covering `--lang cpp`, `--lang rust`, missing tester errors, `None`/`null` values, nested values, exception-style tests, and Rust deque skip behavior.
