## Context

`babel_code_goat.py` currently owns discovery, tester generation, payload extraction, and execution for Python, JavaScript, and TypeScript targets. `generate_tester()` discovers tests once and writes a target-specific tester file with an embedded JSON payload; `command_test()` then verifies that the embedded payload still matches rediscovered tests before invoking the language runner. The new compiled targets should fit that model so `generate -> test` behavior remains predictable.

## Related Work

> **`python-test-discovery/add-mutation-style-test-discovery`**: Defines mutation-style grouping, arbitrary Python test-file discovery, and path-qualified discovered case ids — informs the compiled tester payload contract because C++ and Rust should consume the existing discovered cases without changing discovery semantics.

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the language registry with `tester.cpp` and `tester.rs`.
- Generate self-contained compiled-target tester sources from the same `TestCase.to_jsonable()` payload used by interpreted targets.
- Compile and execute single-file C++17+ and Rust 1.70+ solutions during `test`.
- Preserve the standard JSON result envelope and exit-code semantics for pass, fail, and error results.
- Support nullable and nested values consistently in generated tester logic.
- Keep Python discovery behavior unchanged, including mutation-style tests and path-qualified ids. _(see `python-test-discovery/add-mutation-style-test-discovery`)_

**Non-Goals:**

- Creating a package manager or multi-file build system for C++ or Rust.
- Translating arbitrary Python syntax into C++ or Rust solution code.
- Adding a direct Rust mapping for Python `collections.deque`; Rust deque-dependent cases may be skipped for this checkpoint.
- Changing the public JSON result shape or existing language behavior.

## Decisions

### Extend the Existing Target Registry

Add `cpp` and `rust` entries to `SUPPORTED_LANGS` with tester filenames and runner metadata. `GENERATED_TESTERS` should derive from the registry as it does today so generated compiled tester files are excluded from discovery automatically.

Alternative considered: keep compiled targets in a separate registry. That would split validation and generated-file filtering across two paths even though the CLI semantics are identical.

### Use Target-Specific Tester Source Functions

Add `cpp_tester_source()` and `rust_tester_source()` beside `python_tester_source()` and `javascript_tester_source()`. Each function should embed the same compact JSON payload and generate comparison, normalization, expression-evaluation, mutation-variable, and exception-checking helpers in the target language.

This keeps discovery as the source of truth and preserves mutation-style case ids from related discovery work. _(see `python-test-discovery/add-mutation-style-test-discovery`)_

Alternative considered: invoke the Python runner from compiled targets. That would satisfy some result-shape behavior but would not prove C++/Rust value construction, nullable handling, or exception-style execution in the target language.

### Represent Test Values with a Small Target Value Runtime

Generated compiled testers should parse the embedded payload into a small internal value representation that can model primitives, arrays, maps, sets, counters, decimals, and explicit null. C++ should represent nullable typed arguments with `std::optional<T>` / `std::nullopt` when constructing solution inputs; Rust should use `Option<T>` / `None`.

For comparison, preserve the existing normalized tagged-value model: dictionaries and counters compare as key/value item lists, sets compare unordered, decimals compare numerically, and tolerances are applied only to numeric positions.

Alternative considered: serialize all inputs as strings and require solutions to parse them. That would weaken parity with existing targets and push harness responsibility onto user solutions.

### Compile in an Isolated Temporary Directory

For `test --lang cpp`, compile a generated harness plus the provided solution with a C++17-or-newer compiler such as `g++` into a temporary executable. For `test --lang rust`, compile the generated harness plus the provided solution with `rustc` using an edition compatible with Rust 1.70+. The command should run the produced executable with the same environment tolerance value used by current targets.

Compilation or compiler lookup failures should return the standard error JSON, not traceback output. Passing and failing tests should still produce the tester's JSON pass/fail result.

Alternative considered: compile into the tests directory. A temporary build directory avoids leaving binaries next to source tests and keeps failed builds from dirtying fixtures.

### Preserve Missing Tester Behavior

`command_test()` already checks for the target tester file before extraction. Adding `tester.cpp` and `tester.rs` through `SUPPORTED_LANGS` should make missing compiled testers return the same error result and exit code `2`, and `test` should not call `generate_tester()`.

Alternative considered: regenerate missing compiled testers in `test`. That would break the existing generate-then-test contract and could hide stale or missing generated artifacts.

### Skip Rust Deque-Dependent Cases Before Rust Source Emission

Detect deque-tagged values recursively in Rust test payload entries. Rust tester generation should omit or mark those cases as skipped while preserving all non-deque cases. C++ should continue to support deque-like ordered collection comparison because the checkpoint only calls out Rust skipping.

Alternative considered: map every deque to `VecDeque`. The checkpoint allows skipping because standard translation may not map to it, so spending complexity here is not required for parity outside deque-specific cases.

## Risks / Trade-offs

- [Risk] C++ and Rust have static type constraints while discovered Python values are heterogeneous → Mitigation: generate per-test call expressions and comparison helpers from the concrete payload rather than requiring one universal argument type in user code.
- [Risk] Complex nested null values can produce ambiguous target types → Mitigation: infer types from the nearest non-null siblings or expected values, and fail generation clearly when a value is untypeable rather than emitting uncompilable source.
- [Risk] Local machines may not have `g++` or `rustc` installed → Mitigation: catch compiler lookup/build failures and return the standard error JSON result.
- [Risk] Duplicating comparison logic across target tester generators can drift → Mitigation: keep helper structure and test fixtures parallel to Python/JavaScript coverage, especially for tolerance, unordered collections, and exception cases.
- [Risk] Rust deque skipping could hide too much if detection is broad → Mitigation: only skip cases with a recursive `deque` tag in args, expected values, expressions, or variables, and assert that non-deque Rust cases still run.

## Migration Plan

1. Extend the registry and generated-file exclusion list through existing constants.
2. Add compiled tester source generation and payload extraction for `tester.cpp` / `tester.rs`.
3. Add compile-and-run execution paths in `command_test()`.
4. Add tests for generation, missing tester errors, pass/fail execution, value parity, nested `None`/`null`, mutation tests, exceptions, and Rust deque skipping.
5. Roll back by removing `cpp` and `rust` registry entries if compiled-target execution proves unstable before release.

## Open Questions

- Which exact C++ compiler command should be preferred when multiple compatible compilers are present?
- Should skipped Rust deque cases appear in `passed`, be omitted from both `passed` and `failed`, or be represented in a future expanded result schema?
