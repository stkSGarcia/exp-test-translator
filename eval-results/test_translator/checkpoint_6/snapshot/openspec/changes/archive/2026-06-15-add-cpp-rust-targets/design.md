## Context

`babel_code_goat.py` currently owns language validation, tester filename selection, tester metadata, test discovery, and execution. The active CLI spec already defines the common `generate` and `test` contract, so C++ and Rust should be added as first-class targets in the same pipeline rather than as separate commands.

## Related Work

> **`babel-code-goat-cli/add-babel-code-goat`**: Defines CLI commands, language validation, tester file generation, missing-tester errors, allowed values, and execution output — informs extending `SUPPORTED_LANGS`, metadata handling, and shared error behavior because the native targets must preserve the existing CLI contract. _(see `babel-code-goat-cli`)_

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines loop-driven discovery and per-iteration IDs — informs reusing discovered `TestCase` records for native tester rendering because C++ and Rust must not rediscover or renumber loop tests. _(see `babel-code-goat-cli`)_

> **`babel-code-goat-cli/support-mutation-directory-discovery`**: Defines mutation-style and broader discovery behavior on the same test runner surface — informs rendering actual-expression plans and mutable argument assertions for native targets because generated testers need to evaluate the same discovered assertions. _(see `babel-code-goat-cli`)_

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the existing language registry and tester filename mapping.
- Generate compilable `tester.cpp` and `tester.rs` files from the existing discovered `TestCase` model.
- Run native testers through the existing `test` command and preserve the exact JSON status contract.
- Preserve supported value semantics, including nested `None`/null values, collection equality, numeric tolerance, string operations, sorting, and exception-style tests.
- Add focused regression tests covering generation, missing testers, native value rendering, and at least one successful native execution path per language when toolchains are present.

**Non-Goals:**

- Introducing package/project scaffolds such as CMake projects or Cargo packages.
- Translating arbitrary Python code beyond the supported `tests.py` subset.
- Guaranteeing exact arbitrary-precision decimal behavior for Rust beyond the specified `f64` representation.
- Implementing Rust `deque` parity when a test cannot be represented as `VecDeque`; those cases are generated as skipped Rust tests.

## Decisions

1. Extend the existing language map.

`SUPPORTED_LANGS` remains the source of truth for accepted `--lang` values and expected tester filenames. Adding `cpp: tester.cpp` and `rust: tester.rs` keeps validation, missing-tester handling, and metadata checks aligned with the current CLI flow. Alternative considered: separate native language validation. That would duplicate the behavior already covered by the CLI spec.

2. Render native testers from discovered test metadata.

Generation should call `discover_tests` once and pass the resulting `TestCase` list into language-specific renderers. C++ and Rust renderers should share a normalized value/expression rendering layer where practical, then emit target-specific syntax for optionals, containers, comparisons, stdout/stderr capture, and exception checks. Alternative considered: generate native code that parses `tests.py` at runtime. That would require Python in native test execution and weaken the single discovery source.

3. Use single-file compile-and-run execution.

For `test`, the runner should combine the solution file with the generated tester in a temporary directory, compile with a standard toolchain (`g++`/`clang++` for C++17, `rustc` for Rust 1.70+), run the produced binary, and map compile/runtime errors to the existing JSON error/fail behavior. Alternative considered: requiring user-managed build files. That adds setup friction and is outside the single-file solution contract.

4. Represent nullability at generated type boundaries.

C++ should represent nullable generated values with `std::optional<T>` and `std::nullopt`; Rust should use `Option<T>` and `None`. Nested values require type inference before rendering so container element types can wrap only nullable positions. Alternative considered: JSON serialization at runtime. That simplifies rendering but hides native value behavior and does not exercise target collection/string APIs.

5. Treat Rust deque gaps explicitly.

When a discovered test depends on `collections.deque` behavior that the Rust renderer cannot map to `VecDeque`, the Rust tester should mark that test as skipped in generated code. This keeps generation useful for the rest of the suite while making the unsupported deque case visible. Alternative considered: rejecting the whole Rust generation. That conflicts with the checkpoint instruction to skip Rust deque cases.

## Risks / Trade-offs

- Native type inference for heterogeneous or deeply nested values may be incomplete -> Keep unsupported-shape failures in generation with no partial file writes, and add tests for nested `None` plus mixed containers.
- Local environments may not have C++ or Rust compilers -> Gate execution tests with `shutil.which` skips, while still testing generated source contents.
- Rust `f64` decimal handling is less precise than Python `Decimal` or C++ `long double` -> Apply the existing tolerance model and document the precision limitation in generated-code tests.
- Native compile errors can produce noisy toolchain output -> Normalize CLI output to the existing single JSON line and keep compiler diagnostics out of stdout.

## Migration Plan

1. Add language registry entries and filename preservation behavior.
2. Add native renderer helpers for values, expressions, comparisons, and metadata.
3. Add native `test` execution branches for compile-and-run workflows.
4. Expand unit tests and integration-style CLI tests, with compiler-dependent cases skipped when toolchains are unavailable.
5. Roll back by removing `cpp` and `rust` from `SUPPORTED_LANGS`; existing Python/JavaScript/TypeScript paths remain unchanged.

## Open Questions

- Which C++ compiler should be preferred when both `g++` and `clang++` are installed?
- Should generated Rust skipped deque tests appear in `passed`, `failed`, or be omitted from result arrays? The spec currently requires generated skipped Rust tests rather than a final reporting convention.
