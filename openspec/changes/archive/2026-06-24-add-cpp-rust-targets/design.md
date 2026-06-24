## Context

`babel_code_goat.py` discovers tests from Python source files, normalizes supported Python values into a tagged JSON-compatible model, and emits language-specific tester files. The existing generated testers cover Python, JavaScript, and TypeScript. This change adds compiled targets without changing the Python test authoring surface or the JSON result contract.

The compiled targets need two layers of support: source generation for `tester.cpp` and `tester.rs`, and execution orchestration that can compile the user's solution together with the generated tester before running it. The generated tester runtime must understand the existing normalized value model, including tagged dictionaries, sets, counters, deques, decimals, mutation metadata, primitive expressions, tolerances, expected exceptions, and stream expectations.

## Goals / Non-Goals

**Goals:**
- Add `cpp` and `rust` to the supported language registry for `generate` and `test`.
- Generate one self-contained tester file per compiled target using C++17+ and Rust 1.70+ language features.
- Preserve the current discovery, result JSON, test ID, tolerance, mutation, loop, primitive expression, and expected-output semantics.
- Support `None`/null values anywhere in nested arguments and expected values for all targets, including C++ and Rust.
- Compile and run C++/Rust tests from the `test` command while reporting standard pass/fail/error JSON.

**Non-Goals:**
- Translating arbitrary Python test code into C++ or Rust source.
- Supporting Rust `VecDeque` as a translation target for Python `collections.deque` behavior in this change.
- Adding package managers, multi-file project scaffolds, or build-system integration beyond compiling the generated tester with a single solution source file.
- Changing the existing Python, JavaScript, or TypeScript public CLI behavior except where null/value parity requires shared helper updates.

## Decisions

1. **Represent test data with the existing normalized model.**

   Reuse the current discovery output as the source of truth and teach the C++/Rust tester runtimes to decode and compare it. This avoids a second discovery path and keeps test IDs, value ordering, dictionary key semantics, and mutation metadata consistent. The alternative was to emit bespoke language literals directly from the AST, but that would duplicate Python value semantics and make nested `None`/tagged containers harder to keep aligned.

2. **Generate self-contained compiled testers.**

   `tester.cpp` and `tester.rs` should contain the discovered cases, comparison helpers, expression evaluators, output capture, and entrypoint invocation glue in one file. Single-file testers match the existing generated artifact pattern and keep the `generate -> test` workflow simple. The alternative was runtime sidecar files, but that would complicate missing-tester checks and artifact cleanup.

3. **Compile during `test`, not `generate`.**

   `generate` should only discover tests and write the tester file. `test` should verify the expected tester exists, compile the tester with the solution, execute it, parse the result, and map compile/runtime harness failures to the standard error JSON. This preserves the current separation where `generate` validates tests but does not require a user solution.

4. **Use target-native optional/null types at the entrypoint boundary.**

   C++ generated calls should represent nullable values with `std::optional<T>`/`std::nullopt` where the inferred argument or expected type can be absent. Rust generated calls should use `Option<T>` with `Some(...)`/`None`. Internally, both runtimes may keep an enum/value wrapper for structural comparison, but solution-facing calls should use idiomatic nullable types.

5. **Keep the Rust deque limitation explicit and test-scoped.**

   Python deque values and deque-specific operations should continue to be supported for other targets. Rust tests that specifically require Python `collections.deque` behavior should be skipped with `pytest.mark.skipif` in the Python test suite rather than silently changing generated semantics. The alternative was mapping to `VecDeque`, but the checkpoint explicitly calls out that standard translation may not map to it.

## Risks / Trade-offs

- [Risk] C++ and Rust entrypoint type inference can be ambiguous for heterogeneous or null-heavy data. -> Mitigation: infer from all non-null observed values, use optional wrappers when any observed value is null, and report harness errors when a solution signature cannot match the generated call shape.
- [Risk] Compilers or Rust toolchains may not be installed in every test environment. -> Mitigation: add capability probes and skip end-to-end pytest cases when the relevant compiler is unavailable while still unit-testing generation and missing-tester behavior.
- [Risk] Reimplementing deep structural comparison in two compiled runtimes can drift from Python semantics. -> Mitigation: keep helper behavior table-driven around the normalized tags and add cross-target parity tests for nested nulls, maps, sets, counters, decimals, tolerance, mutation, and exceptions.
- [Risk] Compile failures could leak compiler output and break the one-line JSON contract. -> Mitigation: capture compiler stdout/stderr and return exactly the standard error JSON with exit code `2`.
- [Risk] High-precision decimal behavior differs by target. -> Mitigation: use `long double` for C++ and `f64` for Rust as target-specific approximations while preserving tolerance-aware numeric comparison semantics.

## Migration Plan

1. Extend language metadata with `cpp -> tester.cpp` and `rust -> tester.rs`.
2. Add generator/runtime helpers for C++17 and Rust 1.70+.
3. Add compile-and-run execution paths for compiled targets.
4. Expand parity tests, including missing tester checks and compiler-availability skips.
5. Run the existing Python/JavaScript/TypeScript test suite to guard against regressions.

Rollback is local: remove the `cpp` and `rust` language metadata entries and compiled tester generation/execution helpers, leaving existing targets unchanged.

## Open Questions

- Which compiler commands should be preferred when multiple C++ compilers are available (`g++` vs `clang++`)?
- Should compile diagnostics remain fully suppressed to preserve the strict JSON contract, or be exposed through stderr while stdout remains strict JSON?
