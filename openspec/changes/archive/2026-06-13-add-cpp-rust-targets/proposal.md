## Why

The CLI currently targets Python, JavaScript, and TypeScript, leaving C++ and Rust solutions outside the generate/test workflow. Adding these compiled targets expands the translator to common interview and systems-language submissions while preserving the same Python-test value model users already rely on.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` files that can run the discovered Python test cases against single-file C++ or Rust solutions.
- Require `test` to fail with the standard error JSON and exit code 2 when the expected compiled-target tester file is missing.
- Preserve value-model parity with interpreted targets, including nested `None`/null values, structural equality, supported containers, numeric tolerance behavior, raw output expectations, mutation-style tests, and exception-style expectations where applicable.
- Map Python values into idiomatic C++17 and Rust 1.70+ representations, including optional/nullable values, vectors/lists, maps, sets, strings, decimal-like numbers, and supported exception/panic checks.
- Skip Python `collections.deque` behavior for Rust targets where the standard translation cannot map it reliably.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expands supported target languages to C++ and Rust, adds compiled-target tester filenames and missing-tester behavior, and requires C++/Rust generated testers to support the same discovered-test value model as existing interpreted targets.

## Impact

- Updates CLI language validation, tester filename selection, generation, and test dispatch for `cpp` and `rust`.
- Adds C++17 and Rust 1.70+ tester generation/execution paths, including compile/run orchestration and result normalization into the existing JSON schema.
- Extends value encoding, comparison helpers, output capture, mutation handling, and exception-style expectation support for compiled targets.
- Adds regression coverage for generated C++/Rust testers, missing tester files, null/optional values, nested containers, dictionaries/maps, sets, strings, numeric comparisons, mutation tests, and Rust deque skips.
