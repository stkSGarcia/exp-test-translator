## Context

`babel_code_goat.py` currently supports `python`, `javascript`, and `typescript` through one shared discovery pipeline and language-specific generated testers. The generated testers embed the normalized test payload, revalidated by `test`, then execute a same-language solution while preserving the one-line JSON result contract.

Checkpoint 6 expands the target matrix to C++ and Rust. These targets need the same discovered test model and comparison behavior as the interpreted targets, but they also need compile-time integration with single-file solutions and explicit mappings for nullable values, containers, numeric precision, strings, sorting, and exception-style tests.

## Goals / Non-Goals

**Goals:**

- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` with embedded payloads that can be extracted during `test` revalidation.
- Keep Python discovery, payload shape, test IDs, result JSON, exit codes, and tester non-modification guarantees unchanged.
- Execute C++ and Rust targets against the same normalized tests used by Python, JavaScript, and TypeScript.
- Preserve supported value parity, including nested `None`/`null` values, rich containers, numeric tolerance, mutation-style tests, loop tests, stdout/stderr expectations, and raise expectation checks where the target can express them.
- Map Python `None` to C++ `std::optional<T>`/`std::nullopt` and Rust `Option<T>`/`None` in generated invocation and comparison helpers.

**Non-Goals:**

- Translating arbitrary Python implementation code to C++ or Rust.
- Supporting multi-file C++ or Rust projects, package managers, custom build systems, or external crates.
- Expanding Python test discovery beyond the currently supported constructs.
- Requiring Rust deque-operation tests when the source behavior depends on Python `collections.deque` operations rather than value comparison.

## Decisions

1. Extend the language registry with explicit compiled target metadata.

   Add `cpp` and `rust` entries with tester filenames, runner kind, compiler command defaults, and source suffix expectations. Keep all language validation and missing-tester logic driven by this registry so existing unsupported-language behavior remains centralized.

   Alternative considered: special-case C++ and Rust at each CLI branch. That would make the missing-tester and generation paths easy to drift from the existing language contract.

2. Reuse the normalized payload as the cross-language contract.

   `tester.cpp` and `tester.rs` will embed the same JSON-compatible payload used by other generated testers, with payload extraction updated to recognize a clearly delimited raw string or comment block in each compiled tester. `test` will continue rediscovering Python tests and comparing them to the embedded payload before compiling or running target code.

   Alternative considered: generate C++/Rust testers directly from AST structures without embedded JSON. That would bypass existing revalidation and make generated tester drift harder to detect.

3. Generate self-contained compiled tester harnesses.

   The C++ tester should target C++17 or later and include helper types/functions for value decoding, deep comparison, expression evaluation, stdout/stderr capture, mutation grouping, loop result handling, and exception-style checks. The Rust tester should target Rust 1.70+ and include equivalent helpers using the standard library only.

   Alternative considered: call into Python helper code from compiled testers. That would make C++/Rust tests depend on the Python runtime during execution and weaken the same-language target guarantee.

4. Compile generated testers with the solution file at `test` time.

   For C++, `test` should compile `tester.cpp` together with the supplied single-file solution by including or otherwise linking the solution function source into a temporary executable, then run that executable. For Rust, `test` should compile `tester.rs` with the supplied solution file included as a module or `include!` source, then run the produced executable. Temporary build artifacts should live outside `<tests_dir>` so `test` does not create or modify tester files.

   Alternative considered: compile during `generate`. That cannot work because the solution path is supplied only to `test`, and it would break the current generate/test separation.

5. Model target values with target-native nullable and collection types.

   C++ generated code should represent nullable values with `std::optional<T>` and `std::nullopt`, sequence values with `std::vector<T>`, maps with `std::map` or `std::unordered_map` as appropriate, and sets with `std::set<T>`. Rust generated code should represent nullable values with `Option<T>`, sequences with `Vec<T>`, maps with `HashMap<K, V>` or `BTreeMap<K, V>`, and sets with `HashSet<T>`. Generated Rust map access helpers should support owned `String` keys such as `get_mut(String::from("items"))` where mutation-style tests need them.

   Alternative considered: force all solution signatures through one dynamic tagged value type. That is simpler for the harness but awkward for users writing idiomatic C++ and Rust solutions.

6. Keep numeric and exception semantics explicit per target.

   C++ decimal-like expected values should use `long double`; Rust should use `f64` and document the lower precision. C++ exception-style tests should catch `std::exception` after calls that throw, while Rust exception-style tests should use `catch_unwind` around calls that `panic!`.

   Alternative considered: require exact Decimal parity in Rust. Without external crates, Rust standard-library `f64` cannot provide Python `Decimal` precision.

## Risks / Trade-offs

- [Risk] C++ and Rust signatures can be ambiguous for nested nullable/container values. -> Mitigation: start with deterministic type inference from the discovered payload and add tests for `None`/`null` at top level and nested positions.
- [Risk] Temporary compilation can be slow or unavailable on machines without `g++`/`clang++` or `rustc`. -> Mitigation: treat compile failures as harness errors and keep tests skippable when compilers are missing.
- [Risk] Rust `f64` cannot fully match Python `Decimal` precision. -> Mitigation: preserve documented precision limits and cover tolerance behavior explicitly.
- [Risk] Mutation-style tests require target-specific mutable argument handling. -> Mitigation: generate helpers that pass mutable references/pointers only when the discovered mutation group requires observing post-call state.
- [Risk] C++/Rust exception mechanisms differ from Python exceptions. -> Mitigation: map raise expectation tests to `std::exception` and `panic!`/`catch_unwind` checks while preserving message matching where available.
