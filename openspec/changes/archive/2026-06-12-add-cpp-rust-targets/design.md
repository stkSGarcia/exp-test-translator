## Context

`babel_code_goat.py` currently centralizes supported language names and tester filenames in `SUPPORTED_LANGS`, writes metadata-bearing tester files from `render_tester`, and executes discovered cases through language-specific runner branches in `execute_case`. Python runs in-process through an embedded runner, while JavaScript and TypeScript use a Node subprocess runner. The discovery and case metadata layers already encode rich Python values, expression plans, mutation-style cases, output expectations, loop tests, and exception expectations.

Checkpoint 6 expands the same CLI workflow to C++ and Rust. The new targets need the same visible behavior as interpreted targets, but execution must compile or otherwise run single-file C++/Rust solutions with temporary harness code.

## Goals / Non-Goals

**Goals:**

- Add `cpp` and `rust` to the supported `generate` and `test` language set.
- Generate `tester.cpp` and `tester.rs` metadata files and require their presence before `test`.
- Preserve current JSON output and exit-code contracts for pass, fail, and error outcomes.
- Execute C++ and Rust single-file solutions against discovered test metadata with parity for supported values, nullable values, comparisons, loops, mutation tests, stdout/stderr expectations, and exception-style tests.
- Keep discovery in Python as the source of truth and reuse the existing encoded case representation where practical.

**Non-Goals:**

- Translating arbitrary Python test code into general-purpose C++ or Rust source.
- Supporting multi-file C++/Rust projects, Cargo packages, CMake projects, or user-provided build systems.
- Providing exact arbitrary-precision decimal behavior for Rust beyond the checkpoint's `f64` mapping.
- Mapping Python `collections.deque` behavior for Rust; Rust deque-specific cases are skipped for the Rust target.

## Decisions

1. Extend the language registry first.

   Add `cpp: tester.cpp` and `rust: tester.rs` to the existing language filename registry, and derive all validation, tester filename lookup, metadata validation, and preflight behavior from that registry. This keeps unsupported-language and missing-tester behavior consistent with current targets.

   Alternative considered: hard-code C++/Rust in command handlers. That would duplicate logic already handled by `SUPPORTED_LANGS` and make future target additions more fragile.

2. Keep generated tester files metadata-bearing and move execution into temporary target harnesses.

   Continue using generated tester files as the generate-to-test contract and source of entrypoint/language metadata. During `test`, rediscover Python tests and synthesize a temporary C++ or Rust harness that imports/includes the solution file, embeds encoded cases, executes one case at a time, and reports pass/fail to the Python parent process.

   Alternative considered: generate a full permanent `tester.cpp` or `tester.rs` during `generate`. That would make generated files stale whenever tests change and diverge from the current workflow where `test` discovers the latest tests while requiring the tester metadata file to exist.

3. Add compiled execution branches beside the Node branch.

   Introduce C++ and Rust runner helpers called from `execute_case`, mirroring `run_node_case`: create an isolated temporary directory, write harness source, compile it with the available toolchain, execute it with case payload/environment data, and parse a minimal success/failure result. Compilation or runtime infrastructure failure marks the affected case failed after successful discovery, while preflight/discovery errors retain the standard error result.

   Alternative considered: interpret C++/Rust-like output from Python without compiling. That would not validate real target-language solutions and would miss value-model issues at the boundary.

4. Use target-native nullable and container representations in harness code.

   Generate target helpers that map encoded Python values into C++17+ and Rust 1.70+ structures. C++ nullable values use `std::optional<T>` and `std::nullopt`; Rust nullable values use `Option<T>` with `Some(...)` and `None`. C++ collections use `std::vector`, ordered/unordered maps where applicable, and `std::set`; Rust collections use `Vec`, `HashMap`, `BTreeMap`, and `HashSet`.

   Alternative considered: stringify all values and compare JSON text. That would lose non-string dictionary key identity, set semantics, nullable nesting, decimal/numeric tolerance behavior, and mutation side effects.

5. Preserve comparison semantics in generated target helpers.

   C++ and Rust harnesses should decode or construct values with enough type information to perform deep equality, inequality, membership, primitive expression evaluation, default/per-assert tolerance checks, stdout/stderr matching, and exception expectation matching inside the target execution path. C++ decimals map to `long double`; Rust decimals map to `f64` as specified.

   Alternative considered: return actual values to Python for comparison. That would require serializing arbitrary C++/Rust values back into the Python tagged model and would make mutation checks and exception/output capture less direct.

6. Treat Rust deque cases as unsupported for that target only.

   Python `collections.deque` cases remain supported for existing targets and C++. For Rust, cases requiring deque behavior should be skipped or excluded from Rust-target execution according to the checkpoint because the standard translation may not map to `VecDeque`.

   Alternative considered: force a `VecDeque` translation. That would exceed the stated checkpoint scope and create a special case not guaranteed by the normal value translator.

## Risks / Trade-offs

- Compiled target tests depend on local `g++`/`clang++` and `rustc` availability -> Gate execution tests when toolchains are absent and treat missing toolchains during CLI execution as target execution failures rather than discovery failures.
- Generic typed values are harder in C++ and Rust than in Python/JavaScript -> Keep the harness value model explicit and generated from the existing encoded case tags.
- `std::optional<T>` and `Option<T>` require concrete inner types -> Infer target value types from encoded arguments and expected values, and reject ambiguous unsupported shapes during discovery or target translation.
- Rust decimal precision is limited by `f64` -> Document the limitation in the target mapping requirement and keep tolerance-based decimal tests within representable bounds for Rust.
- Exception semantics differ across languages -> Match C++ exceptions through `std::exception`-style catches and Rust exception-style tests through `panic!` with `catch_unwind`, as required by the checkpoint.

## Migration Plan

No migration is required for existing users. Existing Python, JavaScript, and TypeScript tester files and test behavior continue to work. New C++ and Rust workflows require running `generate` for the target first so `tester.cpp` or `tester.rs` exists before `test`.

## Open Questions

None for the checkpoint scope.
