## Why

The translator currently specifies interpreted target behavior, but the checkpoint requires native C++ and Rust targets with the same generated-test workflow and value coverage. Adding both targets under the existing CLI contract prevents native generation from drifting from Python, JavaScript, and TypeScript behavior.

## Related Work

### Related Changes

- `add-babel-code-goat`: Established the core generator and runner contract for cross-language tests. This change extends that foundation with C++ and Rust target languages instead of replacing the existing CLI.
- `add-loop-as-test-support`: Expanded test discovery to cover loop-driven Python test patterns. This change complements that work by requiring discovered cases to remain representable in native target testers.
- `support-mutation-directory-discovery`: Added broader discovery behavior for mutation-style and recursive tests. This change builds on that by requiring native testers to handle the same generated cases and value shapes.

### Related Specs

- `babel-code-goat-cli/add-babel-code-goat`: Defines `generate` and `test` command shapes, language validation, missing tester behavior, and allowed values/equality. This change adapts those capabilities for `--lang cpp` and `--lang rust`.
- `babel-code-goat-cli/support-single-call-traceability`: Defines traceable discovered test execution. This change preserves that traceability when emitted tests target C++ or Rust.
- `babel-code-goat-cli/support-mutation-directory-discovery`: Defines expanded test discovery inputs. This change reuses that discovery surface and focuses on native target generation and execution parity.

## What Changes

- Add `--lang cpp` and `--lang rust` support to both `generate` and `test`.
- Generate C++17-or-newer single-file solution/tester scaffolding with `std::optional`, standard containers, `long double`, strings, sorting, and exception-style checks.
- Generate Rust 1.70-or-newer single-file solution/tester scaffolding with `Option<T>`, `Vec`, maps, sets, `f64`, strings, sorting, and `catch_unwind`-based exception-style checks.
- Extend value model parity so C++ and Rust tests support every value type and behavior supported by Python tests, including `None`/`null` anywhere in nested containers.
- Require `test` to error without creating or modifying target tester files when `tester.cpp` or `tester.rs` is missing.
- Skip Python `collections.deque` behavior for Rust targets when translation cannot map it to standard target behavior.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend CLI language validation, tester generation/execution, allowed value/equality behavior, and missing tester validation for C++ and Rust.

## Impact

- Affects CLI parsing and language validation for `generate` and `test`.
- Affects tester generation, target solution templates, runtime comparison helpers, and target execution for native languages.
- May require C++ and Rust toolchain checks in test execution paths.
- Adds fixture and regression coverage for native value serialization, null handling, missing tester errors, and generated tester execution.
