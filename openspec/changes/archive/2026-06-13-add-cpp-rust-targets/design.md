## Context

`babel_code_goat.py` currently keeps the supported-language matrix in one filename map, writes metadata-only tester files, discovers constrained Python tests once, and dispatches execution through Python or Node-specific runners. The existing spec already defines recursive discovery, value parsing, structural comparisons, output expectations, mutation-style tests, tolerance handling, and exception-style expectations; this change extends that contract to two compiled targets without changing the CLI shape or JSON result schema.

The checkpoint asks for C++ and Rust together. That means the implementation should separate shared test-case planning from target-specific code generation and execution, because both new targets need the same discovered-test model but very different type syntax, nullable values, compile commands, runtime invocation, and exception behavior.

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the supported `generate` and `test` language set with `tester.cpp` and `tester.rs` outputs.
- Preserve the existing `generate -> test` workflow, including missing-tester errors before any execution.
- Reuse the existing Python AST discovery and test-case metadata as the source of truth for all targets.
- Generate C++17-compatible and Rust 1.70+-compatible tester code that embeds the discovered cases, includes the user solution, invokes the configured entrypoint, and normalizes pass/fail/error output into the existing JSON schema.
- Preserve value-model parity for compiled targets, including nested `None`/null values, structural containers, strings, numeric tolerance, output capture, mutation-style tests, and exception-style tests where the target can express them.
- Keep Rust deque behavior explicitly limited rather than pretending Python `collections.deque` operations translate cleanly.

**Non-Goals:**

- Supporting arbitrary C++ or Rust project layouts, build systems, Cargo packages, headers, modules, or multi-file submissions.
- Translating arbitrary Python helper code into C++ or Rust beyond the already supported expression/value/test subset.
- Adding a `skip` status or changing the JSON result schema.
- Introducing a separate OpenSpec capability for compiled targets.

## Decisions

1. Extend the language registry instead of adding separate command branches.
   - Rationale: Filename selection, metadata validation, missing-tester checks, and unsupported-language errors already flow through `SUPPORTED_LANGS`.
   - Approach: Add `cpp: tester.cpp` and `rust: tester.rs`, and route execution by language through compiled-target runners.
   - Alternative considered: Add special-case parsing in `command_generate` and `command_test`. That would duplicate existing validation paths and make missing-tester behavior easier to drift.

2. Keep Python discovery target-agnostic and add target renderers after discovery.
   - Rationale: The Python test subset is already the canonical input model. C++ and Rust should not rediscover tests from generated files.
   - Approach: Continue using `discover_tests()` to produce `TestCase` records, then render target-specific literals, comparison helpers, and invocation code from those records.
   - Alternative considered: Generate a tester that shells back into Python for comparisons. That would make compiled targets less standalone and blur failure modes between target execution and host Python behavior.

3. Use single-file compiled harnesses with temporary build artifacts.
   - Rationale: The checkpoint specifies single-file C++ and Rust solutions, and the CLI should remain lightweight.
   - Approach: Generated testers include or reference the submitted solution file, compile a temporary executable with `g++`/`clang++` for C++ and `rustc` for Rust, run it, capture stdout/stderr, and map compile/runtime failures to failed tests or command errors according to when the failure occurs.
   - Alternative considered: Require CMake or Cargo. That would add project-layout assumptions outside the checkpoint.

4. Model nullable values explicitly in generated target code.
   - Rationale: `None` can appear anywhere in nested Python values, and string/sentinel encodings would break structural equality.
   - Approach: Represent nullable C++ values with `std::optional<T>`/`std::nullopt` where type context is available and Rust values with `Option<T>`/`None`/`Some(...)`. For mixed or deeply heterogeneous containers, introduce generated value wrappers only where the static type system cannot express the Python shape directly.
   - Alternative considered: Serialize every value as JSON. That would lose non-string dictionary keys, sets, counters, decimals, and Python container semantics unless a second custom runtime value model was added anyway.

5. Treat C++ and Rust type/runtime helpers as target libraries embedded in the tester.
   - Rationale: Structural equality, tolerance, sets, maps, counters, stdout/stderr capture, and exception checks need reusable code per target.
   - Approach: Generate helpers in `tester.cpp`/`tester.rs` alongside the cases, keeping the user solution single-file and avoiding external dependencies.
   - Alternative considered: Ship separate helper files. That would complicate the current tester-file contract and missing-tester checks.

6. Limit Rust deque coverage intentionally.
   - Rationale: Python `collections.deque` operations do not map cleanly to the standard translation subset, even though Rust has `VecDeque`.
   - Approach: Keep C++/Rust value parity work focused on supported static values and mark Rust-specific regression cases requiring deque behavior as skipped in the repository test suite until a first-class mapping is designed.
   - Alternative considered: Translate deque operations opportunistically to `VecDeque`. That would expand the expression language and risk inconsistent behavior.

## Risks / Trade-offs

- Static target types can be difficult for heterogeneous Python values -> Add generated runtime value wrappers only for shapes that cannot be represented as idiomatic `optional`, vector, map, set, or scalar types.
- Compilers may be absent in a local environment -> Treat missing `g++`/`clang++` or `rustc` as test command errors and guard repository regression tests with availability checks.
- Compile failures can obscure individual test results -> Compile once per invocation when possible; if compilation fails before any case can run, return the standard error JSON.
- Output capture differs across languages -> Encapsulate stdout/stderr capture in target helpers and test exact raw matching with new C++/Rust cases.
- Rust deque behavior is intentionally incomplete -> Keep the limitation narrow, documented, and covered by skipped Rust-specific regression tests so it does not silently masquerade as support.

## Migration Plan

No user migration is required. Existing Python, JavaScript, and TypeScript workflows continue to use the same commands, tester filenames, metadata, JSON schema, and exit codes. Projects can opt into C++ or Rust by running `generate` with `--lang cpp` or `--lang rust`, then running `test` with the same language after the corresponding tester file exists.

## Open Questions

None for the checkpoint scope.
