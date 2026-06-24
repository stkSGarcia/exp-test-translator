## 1. Language Metadata and CLI Contracts

- [x] 1.1 Add `cpp` and `rust` entries to the supported language metadata with tester filenames `tester.cpp` and `tester.rs`.
- [x] 1.2 Ensure `generate` accepts `--lang cpp` and `--lang rust` and writes only the selected compiled target tester file.
- [x] 1.3 Ensure `test` accepts `--lang cpp` and `--lang rust` and resolves the expected compiled target tester file before execution.
- [x] 1.4 Extend missing tester handling so absent `tester.cpp` or `tester.rs` returns `{"status":"error","passed":[],"failed":[]}` and exit code `2` without creating files.
- [x] 1.5 Update failed generation preservation so existing `tester.cpp` and `tester.rs` are not created or modified when discovery or generation fails.

## 2. Shared Value Model Support

- [x] 2.1 Audit the normalized test value representation used by existing generators and identify reusable rendering and comparison boundaries for compiled targets.
- [x] 2.2 Add type inference for compiled target values, including nested containers and nullable positions.
- [x] 2.3 Support `None` at any argument or expected-value nesting depth when rendering compiled target test data.
- [x] 2.4 Preserve deep structural comparison semantics for lists, tuples, dictionaries, sets, frozensets, counters, defaultdicts, decimals, booleans, strings, integers, and floats.
- [x] 2.5 Preserve default and per-assert numeric tolerance behavior in compiled target comparison helpers.

## 3. C++ Tester Generation

- [x] 3.1 Implement `tester.cpp` generation as a self-contained C++17-or-newer harness for discovered tests.
- [x] 3.2 Render C++ literals and helper constructors using `std::optional`, `std::nullopt`, `std::vector`, `std::map`, `std::unordered_map`, `std::set`, `std::string`, and `long double` where appropriate.
- [x] 3.3 Generate C++ deep comparison helpers for nested values, unordered containers, dictionary key semantics, and tolerance-aware numeric values.
- [x] 3.4 Generate C++ expression evaluation support for discovered primitive operations, indexing, sorting, string operations, and membership checks supported by existing targets.
- [x] 3.5 Generate C++ exception expectation checks with `try`, `catch (const std::exception&)`, type/message matching, and failure reporting.

## 4. Rust Tester Generation

- [x] 4.1 Implement `tester.rs` generation as a self-contained Rust 1.70-compatible harness for discovered tests.
- [x] 4.2 Render Rust literals and helper constructors using `Option`, `Some`, `None`, `Vec`, `HashMap`, `BTreeMap`, `HashSet`, `String`, and `f64` where appropriate.
- [x] 4.3 Generate Rust deep comparison helpers for nested values, unordered containers, dictionary key semantics, and tolerance-aware numeric values.
- [x] 4.4 Generate Rust expression evaluation support for discovered primitive operations, indexing, sorting, string methods, and membership checks supported by existing targets.
- [x] 4.5 Ensure generated `HashMap<String, V>` accesses use owned `String` keys accepted by Rust, including `get_mut(String::from("items"))` style forms where mutation is needed.
- [x] 4.6 Generate Rust exception-style checks with `std::panic::catch_unwind`, panic message matching, and failure reporting.
- [x] 4.7 Mark Rust-specific project tests that require Python `collections.deque` operation behavior with `pytest.mark.skipif`.

## 5. Compiled Target Execution

- [x] 5.1 Add C++ compile-and-run execution for `test --lang cpp`, using the generated tester and supplied single-file solution.
- [x] 5.2 Add Rust compile-and-run execution for `test --lang rust`, using the generated tester and supplied single-file solution.
- [x] 5.3 Route compile, link, and runtime harness failures through the standard error JSON and exit code `2`.
- [x] 5.4 Keep passing and failing compiled test runs on the existing one-line JSON contract with only `status`, `passed`, and `failed` keys.
- [x] 5.5 Ensure temporary compiled artifacts are written outside the tests directory or cleaned up without modifying tester files during `test`.

## 6. Verification

- [x] 6.1 Add unit tests that `generate` creates `tester.cpp` and `tester.rs` for supported compiled targets.
- [x] 6.2 Add unit tests that unsupported language rejection still applies outside `python`, `javascript`, `typescript`, `cpp`, and `rust`.
- [x] 6.3 Add unit tests that missing `tester.cpp` and `tester.rs` produce the standard error JSON and exit code `2`.
- [x] 6.4 Add C++ and Rust end-to-end tests for passing, failing, and build-error runs.
- [x] 6.5 Add C++ and Rust tests for nested `None`/`null` values in arguments and expected values.
- [x] 6.6 Add C++ and Rust tests for nested containers, dictionary key semantics, sets, counters, defaultdicts, decimals, tolerance comparisons, and primitive expression assertions.
- [x] 6.7 Add C++ and Rust tests for exception-style expectations and message matching.
- [x] 6.8 Run the full Python test suite and targeted compiled-target tests.
