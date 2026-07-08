## Why

The translator currently supports interpreted targets, but checkpoint 6 requires compiled C++ and Rust targets to participate in the same `generate` and `test` workflow. Adding both targets together keeps the target-language contract honest across primitive values, nested collections, exceptions, mutation-style tests, and `None`/`null` values anywhere in discovered test data.

## What Changes

- Add `--lang cpp` and `--lang rust` support for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` files that can run the discovered Python tests against single-file C++17+ and Rust 1.70+ solution files.
- Preserve value-model parity with the Python-driven tests, including booleans, numbers, strings, decimals, lists/tuples, dictionaries/maps, sets, counters, defaultdict-style mappings, nested structures, and `None`/`null` in any supported position.
- Represent nullable values idiomatically as `std::optional<T>` / `std::nullopt` in C++ and `Option<T>` / `None` in Rust.
- Make `test --lang cpp` and `test --lang rust` fail with the standard JSON error result and exit code when the generated tester file is missing.
- Skip Python `collections.deque` cases for Rust when no direct generated Rust mapping is available, while keeping other targets unaffected.

## Related Work

### Related Changes

- `support-loop-construct-tests`: Established that compact Python test forms may expand into multiple concrete cases; the C++ and Rust testers must consume those discovered cases without narrowing supported test shapes.
- `support-rich-python-test-comparisons`: Motivated richer expected values and exception assertions in translated harnesses; this change extends that breadth to compiled targets.
- `add-mutation-style-test-discovery`: Added in-place mutation patterns and arbitrary Python test file discovery; generated C++ and Rust testers must execute those discovered mutation cases and preserve entrypoint traceability.
- `add-babel-code-goat`: Introduced the generate-then-test workflow and predictable target-language runner files; this change adds two compiled target runners to that workflow.
- `support-single-call-test-traceability`: Broadened expression support while preserving a single entrypoint call; compiled target testers must evaluate those expressions consistently.

### Related Specs

- `python-test-discovery/add-mutation-style-test-discovery`: Defines mutation-style test grouping and path-qualified discovered test cases. This change builds on those discovered cases by generating C++ and Rust testers that execute them without changing discovery semantics.

## Capabilities

### New Capabilities

- `compiled-targets`: C++ and Rust generation/testing support, including target-specific tester files, compilation/execution, nullable value representation, and parity with discovered Python test values.

### Modified Capabilities

- None.

## Impact

- `babel_code_goat.py`: Extend supported language registration, tester generation, target-specific rendering, compilation/execution, value serialization, exception handling, and missing tester checks for `tester.cpp` and `tester.rs`.
- `tests/test_babel_code_goat.py`: Add coverage for C++ and Rust generation, missing tester failures, value-model parity including nested `None`/`null`, mutation cases, exception-style checks, and Rust deque skip behavior.
- Runtime tooling: Requires local `g++`/compatible C++17 compiler and `rustc` for executing compiled-target tests; absence should produce the standard JSON error result rather than a partial harness.
