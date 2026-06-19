## Context

`babel_code_goat.py` currently centralizes language support in one module. `SUPPORTED_LANGS` maps accepted `--lang` values to tester filenames, `render_tester()` writes a small metadata-only tester file, `read_tester_metadata()` validates that metadata, and `cmd_test()` reruns discovery before dispatching each discovered `TestCase` through `execute_case()`. Runtime support currently branches to the Python runner for `python` and a Node-based runner for `javascript` and `typescript`.

Checkpoint 6 adds two compiled targets, C++ and Rust, while preserving the existing Python-authored test source and JSON result contract. The main implementation challenge is not discovery; it is producing target-specific runners that can decode the existing case model, invoke compiled solutions, evaluate expression plans, compare rich values, and report each discovered test exactly once.

## Goals / Non-Goals

**Goals:**
- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate and require `tester.cpp` and `tester.rs` as the workflow marker files for C++ and Rust.
- Execute C++ and Rust solutions through generated harnesses that preserve the current test result JSON shape and exit-code behavior.
- Support the same Python test value model for C++ and Rust, including nested `None`/`null` values.
- Translate supported primitive expression plans, string helpers, sorting, numeric tolerance, mutation-style cases, output expectations, and exception expectations for the new targets.
- Skip Rust cases that require Python `collections.deque` semantics rather than failing the whole suite for unsupported standard-library mapping.

**Non-Goals:**
- Supporting arbitrary C++ or Rust project layouts, build systems, packages, or multi-file solutions.
- Supporting C++ versions older than C++17 or Rust versions older than 1.70.
- Adding new Python test syntax beyond the already supported discovery subset.
- Replacing the existing Python and Node execution paths.

## Decisions

1. Keep language registration centralized.
   - Rationale: CLI validation, tester filenames, metadata validation, and test dispatch all already depend on the `SUPPORTED_LANGS` mapping.
   - Approach: Add `cpp: tester.cpp` and `rust: tester.rs`, keep metadata format versioned as-is, and extend `execute_case()` dispatch for compiled targets.
   - Alternative considered: Add separate validation tables per command. That increases drift risk because `generate` and `test` must agree on filenames and metadata.

2. Generate self-contained compiled tester source files.
   - Rationale: Existing generated testers are the generate-to-test workflow marker, and compiled languages need an executable harness rather than a Node/Python interpreter runner.
   - Approach: Have `render_tester("cpp", ...)` and `render_tester("rust", ...)` include metadata plus a full harness source that embeds runtime helpers and includes or links the single-file solution in a deterministic way. `test` compiles the tester and solution in a temporary directory, runs the binary, and parses one JSON result line.
   - Alternative considered: Keep generated testers metadata-only and synthesize compiler input entirely in `test`. That would satisfy execution but make `tester.cpp` and `tester.rs` less meaningful and harder to inspect after `generate`.

3. Preserve the current case JSON model as the cross-language contract.
   - Rationale: Discovery already normalizes tests into JSON-serializable cases with encoded values, expression plans, tolerances, mutation metadata, and expectations.
   - Approach: Reuse `case_to_json()` for C++ and Rust, add any missing type tags needed to distinguish null/None from absent optional fields, and implement equivalent decoders/comparators in the generated harnesses.
   - Alternative considered: Emit target-language literals directly during discovery. That would duplicate discovery and value formatting logic per language and make nested null handling more fragile.

4. Represent optional values explicitly in compiled harness runtimes.
   - Rationale: Python `None` may appear as a complete value, a container member, a dictionary key, or an optional metadata field. C++ and Rust need to distinguish "expected value is None" from "no expected value".
   - Approach: Use tagged runtime values for test data. In C++, map nullable typed solution-facing values to `std::optional<T>`/`std::nullopt` where the translated signature requires it; in Rust, map them to `Option<T>` with `Some(...)` and `None`. Harness-side dynamic values keep a null variant for structural comparison.
   - Alternative considered: Use plain JSON `null` everywhere. That loses the distinction between absent optional fields and an actual expected null unless every field is wrapped.

5. Compile and run each target through temporary build artifacts.
   - Rationale: `test` must not modify the generated tester file or leave build outputs in the tests directory.
   - Approach: Copy or reference `tester.cpp`/`tester.rs` and the solution into a temporary directory, compile with the available system compiler (`g++`/`clang++` for C++17+ and `rustc` for Rust 1.70+), execute the binary with per-case payloads, and treat compiler/runtime setup failures as test command errors before successful execution or failed cases after discovery depending on where they occur.
   - Alternative considered: Require users to precompile their solution. That would change the current `test <solution_path> <tests_dir>` contract and push harness details onto users.

6. Treat Rust deque cases as skipped failed/neutral according to discovery context.
   - Rationale: The checkpoint explicitly says Python `collections.deque` operations are skipped for Rust targets because the standard translation may not map to `VecDeque`.
   - Approach: Detect cases whose encoded values or expression plans require deque semantics when running `--lang rust` and omit them from Rust execution/reporting only when the test author marks them with the expected skip mechanism; otherwise discovery remains target-independent and unsupported execution should fail the affected case rather than silently passing it.
   - Alternative considered: Convert every deque to `VecDeque`. That could be added later, but checkpoint 6 intentionally scopes Rust deque behavior out.

## Risks / Trade-offs

- Compiler availability can vary by environment -> Add tests that skip compiled-target execution when the required compiler is absent while still testing generation, validation, and missing-tester behavior.
- Inferring C++ and Rust callable signatures from dynamic Python test values is limited -> Start with the single-file solution shapes and value types covered by the checkpoint, and fail clearly when a discovered case cannot be mapped to the target type model.
- Nulls nested inside heterogeneous containers are hard to map to statically typed solution signatures -> Keep harness comparison values tagged and use optional target values only at solution-call boundaries where a concrete type can be inferred.
- Exception type names differ across languages -> Match supported exception-style tests by target semantics: `std::exception`-derived failures for C++ and `panic!` captured by `catch_unwind` for Rust, with message matching where the target exposes one.
- Generated harnesses can become large -> Keep shared algorithms structured in Python templates and add focused golden/behavior tests instead of asserting entire generated file contents.

## Migration Plan

No migration is required for existing Python, JavaScript, or TypeScript users. Existing generated testers remain valid for their languages. New C++ and Rust users must run `generate` before `test` so `tester.cpp` or `tester.rs` exists, matching the established workflow.

Rollback is limited to removing the new language entries, compiled-target dispatch, generated harness templates, and compiled-target tests. Existing interpreted-target discovery and execution should remain unaffected.

## Open Questions

None.
