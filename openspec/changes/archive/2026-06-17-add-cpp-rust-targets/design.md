## Context

`babel_code_goat.py` currently centralizes language support in `SUPPORTED_LANGS`, uses `render_tester()` to write metadata-only tester files, discovers Python test cases into `TestCase` objects, serializes those cases through `case_to_json()`, and dispatches execution through `execute_case()`. Python runs through an embedded Python runner and JavaScript/TypeScript run through the embedded Node runner; C++ and Rust need equivalent generated tester files plus compiled execution paths.

## Related Work

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines allowed test constructs and exactly-one-entrypoint traceability — informs keeping discovery shared and language-neutral except for target-specific skip filtering because compiled targets must report the same discovered test IDs. _(see `babel-code-goat-cli/support-single-call-traceability`)_

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines loop statement tests and per-iteration assertion reporting — informs preserving loop cases in the common `TestCase` model because C++ and Rust runners should not reinterpret loops. _(see `babel-code-goat-cli/add-loop-as-test-support`)_

> **`babel-code-goat-cli/add-babel-code-goat`**: Defines CLI language validation, tester filenames, metadata, missing-tester errors, value/equality semantics, and callable resolution — informs extending `SUPPORTED_LANGS`, metadata validation, and runner dispatch instead of adding a separate compiled-target command path. _(see `babel-code-goat-cli/add-babel-code-goat`)_

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the existing `generate` and `test` command flow.
- Generate `tester.cpp` and `tester.rs` with metadata and enough target-language harness code to compile/run single-file solutions.
- Preserve existing JSON output, exit-code, missing-tester, tester-preservation, test ID, loop, tolerance, and value comparison behavior.
- Support nested `None`/null values through C++ optional and Rust option representations.
- Add target-specific value rendering and comparison helpers for collections, strings, sorting, decimals/floats, and exception-style tests.
- Let Rust skip deque-specific tests only when the source test explicitly marks that behavior as Rust-skipped.

**Non-Goals:**

- Supporting multi-file C++/Rust projects or package managers.
- Translating arbitrary Python test code beyond the existing constrained test subset.
- Providing exact arbitrary-precision decimal behavior for Rust; Rust follows the checkpoint's `f64` mapping.

## Decisions

1. Extend the existing language registry and metadata path.

   Add `cpp: tester.cpp` and `rust: tester.rs` to `SUPPORTED_LANGS`. Keep `render_tester()` responsible for writing the metadata marker for all languages, then dispatch to target-specific body renderers for C++ and Rust. This keeps missing-tester and metadata validation behavior aligned with the existing `python`, `javascript`, and `typescript` flow.

   Alternative considered: separate compiled-target metadata files. Rejected because it would duplicate `read_tester_metadata()` and weaken the existing `generate` to `test` contract.

2. Keep discovery and case serialization as the shared contract.

   Continue using `TestCase`, `encode_value()`, `encode_expr()`, and `case_to_json()` as the runner input contract. Add only a `target_lang` argument to `discover_tests()` so `generate` and `test` can filter Rust-only deque skip markers without changing case IDs for all other targets.

   Alternative considered: generate C++/Rust source directly from the AST. Rejected because the existing Python and Node runners already rely on the serialized case model, and the compiled targets need parity with those semantics.

3. Generate self-contained compiled runners.

   Add C++ and Rust harness templates that embed the serialized cases and include/link the single solution file at test time. C++ should compile with C++17 or newer, use standard-library containers and `std::optional`, and catch `std::exception`. Rust should compile with Rust 1.70-compatible code, use `Option`, standard collections, owned `String` lookup forms where needed, and `catch_unwind` for panic-style expectations.

   Alternative considered: run one process per case like the Node runner. Rejected for compiled targets because repeated compilation per case would be slow and would make stdout/stderr capture and compile diagnostics harder to control.

4. Use generated helper functions for value parity.

   Implement target-language helpers for structural equality, numeric tolerance, truthiness, expression evaluation, mutation checks, stdout/stderr capture, and exception matching. C++ decimal/high-precision values map to `long double`; Rust decimal checks map to `f64`, matching the checkpoint.

   Alternative considered: compare results by stringifying target values. Rejected because the active spec requires structural/container-semantic equality, not formatting equality.

5. Treat missing compilers as execution failures, not missing-tester errors.

   The explicit error case is a missing `tester.cpp` or `tester.rs`. If `g++`/`clang++` or `rustc` is unavailable, compilation fails and discovered tests should be reported as failed under the standard aggregate result behavior, consistent with the current Node runner returning failed cases when Node is unavailable.

## Risks / Trade-offs

- [Risk] C++/Rust type inference for nested null containers may be ambiguous. Mitigation: derive expected target types from paired argument/expected values where possible and fail generation for unsupported ambiguous shapes.
- [Risk] Rust deque skip handling could hide too much if modeled broadly. Mitigation: only skip tests with an explicit Rust-target skip marker and keep unguarded deque behavior subject to normal discovery/execution rules.
- [Risk] Compile times can grow with large generated case sets. Mitigation: compile once per `test` invocation and run all serialized cases inside that executable.
- [Risk] Callable resolution for C++/Rust is less dynamic than Python/JavaScript. Mitigation: document and test the single-file function-first path, then add class/static method forms where the language syntax can be detected reliably.

## Migration Plan

1. Extend tests for language validation, generated tester filenames, missing tester errors, metadata validation, and preservation behavior.
2. Add compiled-target generation and execution behind the existing `--lang cpp` and `--lang rust` options.
3. Add value-parity tests for nulls, nested containers, strings, sorting, maps/sets, numeric tolerance, and exception-style tests.
4. Run the existing Python/JavaScript/TypeScript suite to confirm unchanged behavior.

## Open Questions

- Which C++ compiler should be preferred when both `g++` and `clang++` are present?
- What exact syntax should the source tests use for Rust-specific deque skip markers if existing checkpoints do not already define one?
