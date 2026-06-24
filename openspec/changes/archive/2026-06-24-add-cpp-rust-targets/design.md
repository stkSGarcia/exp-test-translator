## Context

`babel_code_goat.py` discovers tests from Python files, serializes discovered cases into generated tester files, and runs the selected target language through a language-specific tester. The current target set is Python, JavaScript, and TypeScript, with tester filenames and runners defined in one language metadata table.

C++ and Rust add compiled execution and stricter type requirements. The existing normalized value model already tags Python-only structures such as dictionaries with non-string keys, sets, counters, deques, and decimals; the new generators should consume that same normalized representation rather than adding a parallel discovery model.

## Goals / Non-Goals

**Goals:**
- Accept `--lang cpp` and `--lang rust` for both `generate` and `test`.
- Generate `tester.cpp` and `tester.rs` from the same discovered test cases used by existing targets.
- Preserve the JSON result contract and missing-tester error behavior for compiled targets.
- Render supported values, including nested `None`, into C++ and Rust code with deep comparison semantics matching existing targets.
- Compile and execute C++ and Rust testers against single-file solutions.

**Non-Goals:**
- Do not replace the Python test discovery language.
- Do not require Cargo, CMake, or multi-file project layouts.
- Do not guarantee Rust support for Python `collections.deque` operation tests beyond explicitly skipped coverage in the test suite.
- Do not introduce arbitrary Python construct translation beyond the currently supported discovery subset.

## Decisions

1. Extend the existing language metadata table.
   - Add `cpp` with `tester.cpp` and a compiled runner, and `rust` with `tester.rs` and a compiled runner.
   - Rationale: language-specific behavior is already keyed from this table, so extending it keeps argument validation, tester filename lookup, and missing tester checks aligned.
   - Alternative considered: add separate branches in CLI handlers. That would duplicate validation and make future target additions harder to keep consistent.

2. Generate self-contained tester source for each compiled target.
   - C++ testers will include the solution file, define test data and comparison helpers in one translation unit, compile with C++17 or later, and run the produced binary.
   - Rust testers will include the solution file as a module or inline include, define test data and comparison helpers in one generated file, compile with `rustc`, and run the produced binary.
   - Rationale: the repo currently writes one tester file per language and the checkpoint requires single-file solution support.
   - Alternative considered: emit build-system projects. That would add toolchain surface area that is unnecessary for this CLI.

3. Keep normalized test data as the source of truth.
   - The discovery layer should continue producing normalized JSON-compatible values. C++ and Rust generators should render those normalized values into target-native literals and helper constructors.
   - C++ should represent nullable values with `std::optional<T>` and `std::nullopt` where a concrete static type can be inferred.
   - Rust should represent nullable values with `Option<T>`, `Some(value)`, and `None` where a concrete static type can be inferred.
   - Rationale: this preserves parity with Python tests while limiting changes to generation and comparison code.
   - Alternative considered: serialize every value as runtime JSON. That would simplify null handling but would add a JSON parser dependency or a large handwritten parser.

4. Prefer target-native containers and comparison helpers.
   - C++ should render collections using `std::vector`, `std::map` or `std::unordered_map`, and `std::set` as appropriate, with `long double` for decimals/high-precision numeric values.
   - Rust should render collections using `Vec`, `HashMap`, `BTreeMap`, and `HashSet`, with `f64` for decimal-compatible numeric values.
   - Comparison helpers should preserve deep structural comparison, unordered set semantics, dictionary key identity, numeric tolerance, and exact nonnumeric comparisons.
   - Rationale: target-native values make generated tests readable and keep solution signatures close to normal C++ and Rust challenge code.
   - Alternative considered: compare only serialized strings. That would lose key identity and tolerance behavior.

5. Treat exception-style tests as target-language failures.
   - C++ raise expectations should use `try`, `throw std::runtime_error`, and `catch (const std::exception&)`.
   - Rust raise expectations should use `panic!` and `std::panic::catch_unwind`.
   - Rationale: there is no cross-language exception hierarchy equivalent, so generated testers should map Python-style expectation intent to idiomatic target mechanisms.
   - Alternative considered: mark all exception tests unsupported for compiled targets. That would violate value and behavior parity for existing discoverable tests.

## Risks / Trade-offs

- Type inference for nested `None` can be ambiguous when all examples at a position are null. Mitigation: infer from paired expected/argument values across discovered tests where possible and fail generation with the standard error path when no concrete target type can be determined.
- C++ and Rust compiler availability varies by environment. Mitigation: keep compiler invocation isolated to `test` for those languages and surface failures through the existing error JSON contract.
- Rust owned string lookup can be easy to render incorrectly. Mitigation: add explicit coverage for `HashMap<String, V>` lookups using owned `String` keys such as `get_mut(String::from("items"))`.
- Decimal parity is weaker in Rust because the target representation is `f64`. Mitigation: document this as target precision behavior and keep tolerance-aware numeric comparisons in generated helpers.
- Rust deque behavior is intentionally limited. Mitigation: skip Rust-specific deque operation tests in the project test suite while keeping other nested value parity tests active.
