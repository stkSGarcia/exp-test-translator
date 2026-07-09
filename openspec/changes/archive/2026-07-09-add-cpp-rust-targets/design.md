## Context

`babel_code_goat.py` currently owns discovery, value normalization, tester generation, payload extraction, and command execution for Python, JavaScript, and TypeScript. Generated testers embed the same JSON payload produced from discovered Python tests, then each target runtime decodes that payload, calls the target entrypoint, compares results, and prints the standard result object.

The compiled target work should keep that architecture: discovery remains Python-based, and C++/Rust support adds target-specific source renderers plus target-specific compile/run steps. This keeps the new behavior aligned with the existing generate-then-test workflow and avoids introducing a separate metadata format.

## Related Work

**`babel-code-goat-cli/add-babel-code-goat`**: Defines the root CLI, language selection, tester generation, missing tester behavior, supported values, and solution callable forms. It informs the decision to extend `SUPPORTED_LANGS`, `generate_tester`, `extract_tester_payload`, and `command_test` rather than adding separate compiled-language commands because the prior intent was a predictable generate-then-test workflow.

**`babel-code-goat-cli/support-single-call-test-traceability`**: Defines traceable assertion discovery for tests with one invocation of the callable under test. It informs the decision to consume the existing `TestCase` payload unchanged because compiled targets should execute the same discovered assertions, not rediscover or reinterpret tests.

**`babel-code-goat-cli/support-loop-construct-tests`**: Defines allowed loop and assignment constructs. It informs the decision to preserve loop sentinel tests and generated pass/fail semantics in compiled runners because compiled targets should match the existing loop behavior.

**`babel-code-goat-cli/support-mutation-style-tests`**: Defines mutation-style discovery and post-call argument comparison. It informs the decision to decode mutable arguments into target-native collections and compare the mutated argument when `mutation_arg_index` is present.

## Goals / Non-Goals

**Goals:**
- Add `cpp` and `rust` to the existing language registry and CLI validation.
- Generate `tester.cpp` and `tester.rs` from the existing discovered test payload.
- Support the value model already accepted by Python tests, including `None`/`null` in nested values.
- Compile and execute C++17+ and Rust 1.70+ solution/tester pairs through `test`.
- Return the existing JSON result format for pass, fail, and error outcomes.
- Keep Rust deque behavior explicit by skipping unsupported deque cases instead of emitting invalid Rust.

**Non-Goals:**
- Do not parse C++ or Rust source to rediscover tests.
- Do not introduce Cargo, CMake, or multi-file project generation.
- Do not guarantee arbitrary user-defined class serialization beyond the existing normalized value model.
- Do not make Rust deque translation equivalent to Python `collections.deque` in this change.

## Decisions

1. Extend the existing language registry.

   Add `cpp` and `rust` entries to `SUPPORTED_LANGS` with `tester.cpp` and `tester.rs`. `GENERATED_TESTER_FILES` then naturally excludes those generated files during test discovery. This follows the existing command interface and missing-tester lookup model _(see `babel-code-goat-cli/add-babel-code-goat`)_.

   Alternative considered: separate compiled-language flags. That would duplicate CLI behavior and make generated tester validation inconsistent with the existing targets.

2. Keep the JSON payload as the cross-language contract.

   C++ and Rust tester source should embed the same payload shape used by Python and JavaScript/TypeScript. The renderers should generate target helpers for decoding normalized tagged values, evaluating expression payloads, applying tolerance policies, and comparing normalized output. This preserves single-call traceability and mutation metadata without inventing a compiled-only discovery format _(see `babel-code-goat-cli/support-single-call-test-traceability`)_.

   Alternative considered: generate one assertion as handwritten target code per source assertion. That would make nested values and mutation metadata harder to keep consistent across languages.

3. Generate single-file testers and compile beside the solution.

   `cpp_tester_source()` should emit a C++17+ tester that includes or links with the user solution file during `test`; `rust_tester_source()` should emit a Rust 1.70+ tester that compiles with the supplied solution file. `command_test` should dispatch to `g++` for C++ and `rustc` for Rust, run the resulting temporary binary, and validate the stdout contract just like existing runner subprocesses.

   Alternative considered: requiring users to provide project files. That would be heavier than the current single-file target model and would make generated tests less portable.

4. Represent nullability with target-native optional types where target type information is available.

   Generated C++ helper code should represent nullable values with `std::optional<T>` and `std::nullopt` when typed target literals or expected values require it. Generated Rust helper code should use `Option<T>`, `Some(value)`, and `None`. For generic comparison helpers, both targets can also use an internal variant/value representation that preserves nulls before conversion to function arguments.

   Alternative considered: encode all values as strings. That would lose type intent and break equality semantics for numeric, collection, and mutation cases.

5. Prefer target-native standard library containers and operations.

   C++ generation should map collections to `std::vector<T>`, `std::map<K,V>`, `std::unordered_map<K,V>`, and `std::set<T>`, use `long double` for decimal-like numeric comparisons, and use standard string/sort/exception support. Rust generation should map collections to `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, and `HashSet<T>`, use `f64` for decimal-like comparisons, support owned `String` map lookups, and use `catch_unwind` for exception-style tests.

   Alternative considered: implement custom collection shims for every Python behavior. That would increase complexity and conflict with the checkpoint's target-standard-library expectations.

6. Treat Rust deque as a target-specific skip.

   When discovered tests include tagged deque values or deque operations and the selected target is Rust, generation should mark those tests skipped for Rust instead of producing invalid code. The result format should report skipped deque tests consistently with the local convention chosen during implementation, while preserving non-deque test execution _(see `babel-code-goat-cli/support-loop-construct-tests`)_.

   Alternative considered: mapping to `VecDeque`. The checkpoint explicitly says standard translation may not map Python deque operations to `VecDeque`, so this change keeps the skip behavior clear.

## Risks / Trade-offs

- [Compiler availability] C++/Rust tests will fail on machines without `g++` or `rustc` -> Mitigate by returning the existing error result and adding tests that skip only when the toolchain is unavailable.
- [Type inference for nested nulls] Optional types require enough context to infer contained types -> Mitigate with internal normalized value helpers and targeted typed conversion at function-call boundaries.
- [High-precision mismatch] C++ `long double` and Rust `f64` differ from Python `Decimal` -> Mitigate by applying the existing tolerance policy and documenting Rust precision limits in tests.
- [Generated source size] Embedding comparison helpers in two compiled testers can grow large -> Mitigate by keeping helpers generated from focused renderer functions in `babel_code_goat.py`.
- [Deque skip accounting] The existing result schema has no explicit skipped list -> Mitigate by choosing a deterministic local convention in implementation tests before broadening behavior.

## Migration Plan

1. Add language registry entries and missing-tester validation for `tester.cpp` and `tester.rs`.
2. Add C++ and Rust tester source renderers and payload extraction support.
3. Add compiled target subprocess execution in `command_test`.
4. Extend tests for generate, missing tester, passing execution, nested `None`/`null`, mutation, expression, string, sort, exception, and Rust deque skip cases.
5. Keep existing Python, JavaScript, and TypeScript tests passing throughout.
