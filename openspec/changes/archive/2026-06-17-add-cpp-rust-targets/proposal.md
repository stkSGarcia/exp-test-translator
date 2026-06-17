## Why

The CLI currently validates and runs only interpreted targets, leaving generated test harnesses unable to exercise C++ and Rust solutions. This change adds compiled-target support while preserving the existing value-model and `generate` to `test` workflow guarantees, including explicit `None`/null behavior.

## Related Work

### Related Changes

- `support-rich-test-comparisons`: Expanded the translated test surface beyond simple literals and assertions. This change complements it by requiring the same rich value and comparison behavior in C++ and Rust targets.
- `add-babel-code-goat`: Established the cross-language CLI, tester generation, missing-tester error handling, and value comparison contract. This change extends that foundation with two additional target languages and their tester files.
- `support-single-call-traceability`: Tightened test discovery around exactly one entrypoint invocation per discovered test. This change preserves that traceability requirement for compiled target execution.

### Related Specs

- `babel-code-goat-cli/support-single-call-traceability`: Defines allowed test constructs and single-call traceability. This change reuses that discovery model and only changes target-language generation/execution.
- `babel-code-goat-cli/add-loop-as-test-support`: Defines loop-based test parameterization and per-iteration reporting. This change requires C++ and Rust generated testers to preserve the same loop test IDs and outcomes.
- `babel-code-goat-cli/add-babel-code-goat`: Defines the core CLI commands, tester file expectations, missing tester behavior, value/equality support, and solution callable resolution. This change adapts those existing requirements for `cpp` and `rust`.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` for C++ and `tester.rs` for Rust.
- Require `test` to fail with the standard error JSON and exit code 2 when the selected compiled-target tester file is missing.
- Preserve the existing Python-test value model for compiled targets, including `None`/null anywhere supported by the model.
- Map Python nulls to `std::optional<T>` / `std::nullopt` in C++ and `Option<T>` / `None` in Rust.
- Support target-appropriate collections, string operations, sorting, numeric handling, and exception-style assertions for generated C++ and Rust testers.
- Skip Python `collections.deque` behavior for Rust targets when a test requires deque semantics.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend language validation, tester generation, missing-tester validation, value/equality support, and target execution to cover C++ and Rust.

## Impact

- Affected CLI behavior: `generate` and `test` language validation, expected tester filename selection, and error handling.
- Affected generation behavior: emitted C++17+ and Rust 1.70+ tester code.
- Affected execution behavior: compiling/running C++ and Rust solutions through generated testers while preserving existing JSON output and exit-code contracts.
- Affected value model: null/optional values, nested containers, decimals/floats, strings, sorting, maps/sets, and exception-style tests.
