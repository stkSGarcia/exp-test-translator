## Context

`babel_code_goat.py` is a single-file CLI that discovers constrained Python test sources into `TestCase` objects, encodes supported Python values as tagged JSON, and executes each case through target-specific subprocess runners. The current target dispatch supports Python directly and JavaScript/TypeScript through a Node runner. Generated tester files currently provide entrypoint and language metadata, while `test` rediscoveres the Python tests and preserves the existing one-line JSON output contract.

The checkpoint adds compiled C++ and Rust targets to the same workflow. These targets need generated tester artifacts, compiler-backed execution, idiomatic target value literals, nullability support, and parity with the current rich comparison, mutation, output expectation, tolerance, and exception-style behavior.

## Goals / Non-Goals

**Goals:**

- Accept `cpp` and `rust` everywhere language validation currently accepts Python, JavaScript, and TypeScript.
- Generate and require `tester.cpp` and `tester.rs` in the same failure-safe way as existing tester files.
- Add C++17+ and Rust 1.70+ execution backends that compile single-file solution functions with generated per-case harness code.
- Reuse the existing Python AST discovery, tagged value encoding, test IDs, comparison metadata, tolerance metadata, exception metadata, and result aggregation.
- Represent `None`/`null` anywhere in arguments and expected values using `std::optional<T>` / `std::nullopt` for C++ and `Option<T>` / `None` for Rust.
- Cover the documented target collections, strings, sorting, numeric behavior, mutation-style cases, and exception-style expectations.

**Non-Goals:**

- Supporting Cargo projects, CMake projects, multi-file user solutions, package manifests, or external library dependency resolution.
- Supporting arbitrary Python syntax beyond the existing constrained discovery model.
- Guaranteeing exact high-precision decimal parity in Rust beyond the checkpoint's `f64` mapping.
- Translating Python `collections.deque` tests into Rust execution; those cases are skipped for Rust as specified.
- Introducing a new output schema or changing existing exit-code semantics.

## Decisions

1. Keep one discovery and aggregation pipeline, add compiled execution backends.
   - Rationale: Python, JavaScript, and TypeScript already share discovered `TestCase` metadata. C++ and Rust should consume the same case data so IDs, tolerance, output expectations, mutation behavior, and error aggregation stay consistent.
   - Approach: Extend `SUPPORTED_LANGS`, generated tester recognition, and `execute_case` dispatch with `run_cpp_case` and `run_rust_case`. Loop-only cases continue to be evaluated in the parent aggregator without invoking a compiler.
   - Alternative considered: Generate and run a complete target-language test suite once. That would be faster but would complicate per-case isolation, output capture, and deterministic reporting of every discovered ID.

2. Generate temporary per-case compiled harnesses during `test`.
   - Rationale: The parent process already controls case isolation and JSON result parsing. Compiling a small harness per case keeps failures localized and avoids inventing a target-side test runner protocol.
   - Approach: `tester.cpp` / `tester.rs` carry metadata and target helper scaffolding. During `test`, the runner writes a temporary source file that includes or references the solution file, embeds the serialized case as target literals/helper values, compiles it with `g++` or `clang++` for C++ and `rustc` for Rust, runs the binary with stdout/stderr capture, and parses `{"passed":true|false}` from the final stdout line.
   - Alternative considered: Compile the generated tester artifact directly and pass case JSON at runtime. That would require a JSON parser in C++/Rust or hand-written target decoders, increasing dependencies or parser complexity.

3. Use target helper value builders to preserve Python value semantics.
   - Rationale: C++ and Rust are statically typed, while the discovered Python values can contain nested containers, non-string dictionary keys, and nulls. The generated harness must produce idiomatic target values without losing nullability or container meaning.
   - Approach: Translate tagged values into target literals/builders: C++ helpers convert into `std::optional<T>`, `std::vector<T>`, `std::map<K,V>` / `std::unordered_map<K,V>`, `std::set<T>`, `long double`, and `std::string`; Rust helpers generate `Option<T>`, `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, `HashSet<T>`, `f64`, and `String`. Nulls become `std::nullopt` or `None`, with surrounding container and function-call context providing the concrete type where possible.
   - Alternative considered: Require C++/Rust solutions to accept one dynamic `Value` type. That would avoid type inference but would not match the checkpoint's idiomatic target type expectations.

4. Implement recursive comparison and expression evaluation in target helpers.
   - Rationale: Actual return values and mutated arguments live in the compiled binary, so structural equality, tolerance, truthiness, primitive operations, and output checks need target-side helpers.
   - Approach: Port the current Python/Node runner semantics into compact C++ and Rust helpers for deep equality, unordered collection comparison, mapping comparison, numeric tolerance, string methods, supported primitive functions, indexing/slicing where applicable, exception-style matching, and stdout/stderr capture. Mutation assertions evaluate against post-call argument references just like the current runners.
   - Alternative considered: Serialize actual compiled values back to Python for comparison. Generic serialization for arbitrary C++/Rust return types is not available without imposing a new solution API.

5. Keep typed exception support target-idiomatic.
   - Rationale: Python exception classes do not map cleanly to C++ or Rust, but the existing cross-language behavior already treats exception type names as strings for JavaScript/TypeScript.
   - Approach: C++ exception-style tests pass when the entrypoint throws `std::exception` or a compatible exception whose discovered type/message matcher is satisfied; generated tests can use `std::runtime_error` for expected examples. Rust exception-style tests use `panic!` and `std::panic::catch_unwind`, checking panic text for message assertions.
   - Alternative considered: Build a broad Python-to-target exception taxonomy. That would be speculative and brittle.

6. Treat Rust deque tests as unsupported at execution time.
   - Rationale: The checkpoint explicitly says Python `collections.deque` operations are skipped for Rust targets even though Rust has `VecDeque`.
   - Approach: Discovery continues to allow deque values. Rust execution detects cases whose arguments, expected values, or expression metadata require deque semantics and reports them as skipped/passing only when the test suite marks them with the documented skip condition. Non-skipped deque-dependent Rust cases fail rather than silently changing semantics.
   - Alternative considered: Map deque to `VecDeque`. That could pass simple examples but would exceed the checkpoint's stated Rust behavior.

## Risks / Trade-offs

- Compiler availability can make target tests fail in environments without `g++`/`clang++` or `rustc` -> Gate smoke tests with `shutil.which` and make runner failures produce ordinary failed test IDs while preserving CLI output.
- Static target type inference is more fragile than Python or JavaScript dynamic calls -> Keep generated values idiomatic, add focused null/container cases, and document that C++/Rust solutions are single-file functions whose signatures must match the generated value shapes.
- Per-case compilation may be slower for large suites -> Prefer correctness and isolation first; batching can be added later without changing the spec.
- C++ decimal precision and Rust decimal precision differ -> Use `long double` for C++ and `f64` for Rust as requested, and keep tolerance tests realistic for each target.
- Rust deque skip behavior can be surprising -> Add explicit tests around skip handling so unsupported deque execution is visible and intentional.

## Migration Plan

No migration is required. Existing Python, JavaScript, and TypeScript tests and generated tester files remain valid. C++ and Rust projects opt in by running `generate --lang cpp` or `generate --lang rust`, then `test` with the matching language and single-file solution path.

## Open Questions

None for the checkpoint scope.
