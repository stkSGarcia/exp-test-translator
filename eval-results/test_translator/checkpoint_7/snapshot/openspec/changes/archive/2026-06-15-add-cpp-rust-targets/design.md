## Context

`babel_code_goat.py` currently centralizes language support in `SUPPORTED_LANGS`, tester metadata, discovery, encoded test-case payloads, and per-target execution helpers. Python execution uses the encoded case model directly, while JavaScript and TypeScript reuse a Node runner over the same discovered cases. C++ and Rust should plug into that same pipeline so discovery, traceable IDs, mutation tests, loop-expanded cases, and JSON result formatting remain consistent.

## Related Work

> **`babel-code-goat-cli/add-babel-code-goat`**: Defines CLI commands, language validation, missing tester behavior, and allowed values/equality - informs extending `SUPPORTED_LANGS`, tester-file validation, and value encoding because the native targets must behave like existing generated targets.

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines traceable discovered test execution - informs preserving `TestCase.id` and pass/fail aggregation in native runners because generated native testers must report the same case identifiers.

> **`babel-code-goat-cli/support-mutation-directory-discovery`**: Defines recursive discovery and mutation-style tests - informs retaining `discover_tests()` as the single source of cases because native targets should consume the same recursive and mutation-aware case model.

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the existing `generate` and `test` language flow in `babel_code_goat.py`.
- Generate `tester.cpp` and `tester.rs` with metadata compatible with `read_tester_metadata()`.
- Reuse discovered `TestCase` instances and `case_to_json()` semantics for native target generation.
- Support the current Python value model for native targets, including nested `None`/`null`, with Rust deque skips.
- Add regression tests in `tests/test_babel_code_goat.py` for language validation, missing tester errors, native null/value rendering, and toolchain-gated execution.

**Non-Goals:**

- Do not introduce a new discovery parser for C++ or Rust.
- Do not support arbitrary Python syntax beyond the existing discovered subset.
- Do not require Rust deque behavior unless a later change maps it to `VecDeque`.

## Decisions

1. Extend the existing language registry.

   Add `cpp: tester.cpp` and `rust: tester.rs` to `SUPPORTED_LANGS`, and keep language validation, generated-tester filtering, and metadata validation driven by that map _(see `babel-code-goat-cli/add-babel-code-goat`)_. This avoids a second validation path and automatically extends missing-tester checks.

   Alternative considered: separate native-language maps. That would reduce immediate coupling but increase the chance that generation, discovery ignore rules, and metadata support diverge by target class.

2. Emit native testers from the encoded case model.

   Add C++ and Rust rendering helpers that consume the same encoded values and expression operations already used by Python/Node execution. The renderer should translate `encode_value()` tags and `encode_expr()` operations into target-native helper functions for equality, numeric tolerance, string methods, sorting, membership, mutation postconditions, and exception-style checks _(see `babel-code-goat-cli/support-single-call-traceability`)_.

   Alternative considered: generate direct source snippets from Python AST nodes. That would duplicate discovery semantics and make nested values, mutation postconditions, and loop-expanded IDs harder to keep aligned.

3. Use target-native nullable and collection types.

   C++ generated code should use `std::optional<T>`/`std::nullopt` where nullability appears, plus `std::vector`, maps, sets, `long double`, and `std::string`. Rust generated code should use `Option<T>`, `Vec`, maps/sets, `f64`, and `String`. Type inference can be local to generated literals and helper calls; ambiguous mixed null/non-null containers should use an optional element wrapper.

   Alternative considered: serialize all values as JSON strings at runtime and compare JSON. That would simplify type generation but would not exercise native collection/string behavior required by the checkpoint.

4. Keep execution isolated through temporary compile/run steps.

   `test` should read tester metadata, discover current cases, compile or run native tester code in a temporary directory, and aggregate JSON results with the same status and exit-code behavior used by existing targets. C++ should use a C++17 compiler when available, and Rust should use a Rust 1.70-or-newer toolchain when available.

   Alternative considered: only generate native files without executing them. That would satisfy file generation but not the `generate -> test` workflow requirement.

5. Treat Rust deque as an explicit skip.

   Before emitting or executing Rust cases, detect encoded values or expressions containing `deque` and mark those cases skipped for Rust while leaving unrelated cases intact _(see `babel-code-goat-cli/support-mutation-directory-discovery`)_. The skip should be visible in tests without changing pass/fail IDs for non-deque cases.

   Alternative considered: map Python `deque` to `VecDeque` immediately. The checkpoint allows skipping, and deferring avoids partial semantics for operations the current expression model may not fully represent.

## Risks / Trade-offs

- Native type inference may become complex for heterogeneous containers or null-heavy values -> constrain generation to the existing supported value model and add targeted fixtures for nested optional containers.
- C++ and Rust toolchains may be unavailable in some environments -> guard smoke tests with `shutil.which()` and make missing toolchains produce the standard error JSON during `test`.
- Floating-point and `Decimal` parity cannot be exact in Rust with `f64` -> document limited precision in tests and use existing tolerance paths for approximate numeric comparisons.
- Generated native helper code may grow large in a single Python file -> keep helpers target-specific but driven by shared encoded case data to avoid duplicating discovery behavior.

## Migration Plan

1. Extend language metadata and missing-file validation.
2. Add native render helpers and wire them into `generate`.
3. Add native compile/run helpers and wire them into `test`.
4. Add regression tests for file names, metadata, missing tester errors, nested null values, value parity, and toolchain-gated execution.
5. Run the existing Python unit suite, plus C++ and Rust smoke tests where toolchains are installed.

## Open Questions

- Should skipped Rust deque cases appear in a separate `skipped` JSON field later, or remain outside pass/fail aggregation for this checkpoint?
- Which compiler command names should be preferred when multiple C++ or Rust toolchains are available?
