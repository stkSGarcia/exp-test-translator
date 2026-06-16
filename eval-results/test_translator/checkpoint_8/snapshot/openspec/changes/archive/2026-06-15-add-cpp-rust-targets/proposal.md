## Why

The CLI currently limits generated and executed targets to Python, JavaScript, and TypeScript, leaving compiled-language translations outside the supported `generate` -> `test` workflow. Adding C++ and Rust targets now extends the same tester contract to native solutions while preserving the existing value-model and error-output guarantees.

## Related Work

### Related Changes

- `add-loop-as-test-support`: Motivated by preserving traceable test discovery for loop-driven parameterization. This change complements it by requiring C++ and Rust generated testers to execute the same discovered loop tests and report the same IDs.
- `support-mutation-directory-discovery`: Motivated by broader discovery layouts and mutation-style calls. This change builds on the same CLI testing surface but focuses on native-language tester generation and execution.
- `support-single-call-traceability`: Motivated by ensuring each discovered test maps to one configured entrypoint invocation. This change preserves that contract for C++ and Rust solution call sites.

### Related Specs

- `babel-code-goat-cli/add-babel-code-goat`: Defines CLI commands, accepted languages, tester file generation, missing-tester behavior, JSON test output, allowed values, callable resolution, and coverage outcomes. This change adapts that capability by adding `cpp` and `rust` to the language set and by specifying native representations for the same discovered values and assertions.
- `babel-code-goat-cli/add-loop-as-test-support`: Defines loop-based test discovery and reporting. This change reuses those discovery and reporting expectations for generated C++ and Rust testers.
- `babel-code-goat-cli/support-mutation-directory-discovery`: Defines additional discovery behavior over the same `test` command surface. This change does not alter that behavior, but native targets must remain compatible with tests produced by that discovery model.

## What Changes

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` for C++ targets and `tester.rs` for Rust targets.
- Require `test` to fail with the standard error JSON and exit code 2 when the selected native tester file is missing.
- Extend allowed value and equality behavior to C++ and Rust, including `None`/null in nested values.
- Specify native target idioms for optionals, collections, strings, sorting, decimal-like numeric values, and exception-style tests.
- Skip Python `collections.deque` behavior for Rust targets when the translation cannot map it to `VecDeque`.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Add C++ and Rust as supported target languages and extend tester generation, test execution, value support, and native-language behavior requirements.

## Impact

- CLI language validation for `generate` and `test`.
- Tester generation paths for `tester.cpp` and `tester.rs`.
- Native target test runners and solution invocation behavior.
- Value serialization, equality comparison, null handling, collection conversion, numeric tolerance, and exception assertion handling for C++17+ and Rust 1.70+ targets.
