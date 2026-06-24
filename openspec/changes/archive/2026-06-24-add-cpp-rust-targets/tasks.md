## 1. Language Matrix and CLI Preconditions

- [x] 1.1 Add focused CLI tests proving `generate` accepts `--lang cpp` and `--lang rust` and writes `tester.cpp` / `tester.rs`.
- [x] 1.2 Extend unsupported-language and failed-generation preservation tests to cover the expanded tester filename set.
- [x] 1.3 Add missing tester tests proving `test --lang cpp` errors when `tester.cpp` is absent and `test --lang rust` errors when `tester.rs` is absent.
- [x] 1.4 Extend the language registry and tester filename mapping with C++ and Rust metadata without changing existing Python, JavaScript, or TypeScript behavior.

## 2. Shared Payload and Compiled Test Flow

- [x] 2.1 Generate C++ and Rust tester files that embed the same normalized payload used by existing testers.
- [x] 2.2 Extend tester payload extraction to read embedded payloads from `tester.cpp` and `tester.rs` during `test` revalidation.
- [x] 2.3 Add temporary compile-and-run support for C++ testers using the supplied single-file C++ solution and C++17-or-later compiler settings.
- [x] 2.4 Add temporary compile-and-run support for Rust testers using the supplied single-file Rust solution and Rust 1.70-or-later compatible code.
- [x] 2.5 Ensure compiled target build artifacts are temporary and `test` never creates or modifies tester files in `<tests_dir>`.

## 3. C++ Tester Semantics

- [x] 3.1 Implement C++ generated helpers for target-native values, including `std::optional<T>` / `std::nullopt`, `std::vector<T>`, map types, set types, strings, and `long double` decimal-like numbers.
- [x] 3.2 Implement C++ deep comparison, tolerance-aware numeric comparison, primitive expression evaluation, and sorting/string helper behavior.
- [x] 3.3 Implement C++ execution for direct-call tests, loop tests, mutation-style groups, stdout/stderr expectations, and result coverage accounting.
- [x] 3.4 Implement C++ exception-style test handling with `std::exception` matching and message checks.

## 4. Rust Tester Semantics

- [x] 4.1 Implement Rust generated helpers for target-native values, including `Option<T>`, `Vec<T>`, `HashMap<K, V>`, `BTreeMap<K, V>`, `HashSet<T>`, `String`, and `f64` numeric values.
- [x] 4.2 Implement Rust deep comparison, tolerance-aware numeric comparison, primitive expression evaluation, sorting, and string helper behavior.
- [x] 4.3 Implement Rust execution for direct-call tests, loop tests, mutation-style groups, stdout/stderr expectations, and result coverage accounting.
- [x] 4.4 Implement Rust panic-style test handling with `catch_unwind` and message checks.
- [x] 4.5 Ensure Rust `HashMap<String, V>` mutation helpers support owned `String` key lookups where generated tests require them.

## 5. Parity and Regression Coverage

- [x] 5.1 Add end-to-end C++ tests covering nested `None`/`null`, rich containers, decimal-like numeric comparisons, primitive expressions, mutation groups, loops, stream expectations, and exception-style tests.
- [x] 5.2 Add end-to-end Rust tests covering nested `None`/`null`, rich containers, f64 numeric comparisons, primitive expressions, mutation groups, loops, stream expectations, and panic-style tests.
- [x] 5.3 Mark or structure Rust deque-operation cases so behavior depending on Python `collections.deque` operations is skipped for Rust while value parity remains covered elsewhere.
- [x] 5.4 Run the full pytest suite and any compiler-gated focused scenarios for Python, JavaScript, TypeScript, C++, and Rust.
- [x] 5.5 Run `openspec status --change add-cpp-rust-targets` and confirm the change is apply-ready.
