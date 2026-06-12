## 1. Language Registry and CLI Preflight

- [x] 1.1 Add `cpp` and `rust` to the supported language registry with `tester.cpp` and `tester.rs`.
- [x] 1.2 Ensure `generate` writes C++ and Rust metadata tester files with the correct comment marker syntax.
- [x] 1.3 Ensure unsupported-language failures preserve all tester files, including `tester.cpp` and `tester.rs`.
- [x] 1.4 Ensure `test` returns the standard error JSON and exit code 2 when `tester.cpp` or `tester.rs` is missing.
- [x] 1.5 Extend tester metadata validation tests to cover C++ and Rust language metadata.

## 2. Shared Target Value Translation

- [x] 2.1 Add target type/literal rendering for encoded scalar, nullable, sequence, mapping, set, counter, default dictionary, decimal, and nested values.
- [x] 2.2 Preserve `None` anywhere in C++ value renderings using `std::optional<T>` and `std::nullopt`.
- [x] 2.3 Preserve `None` anywhere in Rust value renderings using `Option<T>`, `Some(value)`, and `None`.
- [x] 2.4 Map C++ strings, vectors, maps/unordered maps, sets, sorting, numeric, and decimal values to C++17+ standard-library constructs.
- [x] 2.5 Map Rust strings, vectors, hash maps, B-tree maps, hash sets, sorting, numeric, and decimal values to Rust 1.70+ standard-library constructs.
- [x] 2.6 Add Rust-specific handling so deque-dependent cases are excluded or skipped for Rust target execution only.

## 3. C++ Runner

- [x] 3.1 Implement a C++ harness generator that includes or otherwise wires a single-file C++ solution into a temporary executable.
- [x] 3.2 Implement C++ deep equality, inequality, membership, primitive expression, and numeric tolerance helpers.
- [x] 3.3 Implement C++ execution for normal return-value cases, loop tests, and mutation-style cases.
- [x] 3.4 Implement C++ stdout/stderr capture checks for raw output expectations.
- [x] 3.5 Implement C++ exception-style expectations using `try`, `throw`, and `std::exception` handling.
- [x] 3.6 Route `execute_case` through the C++ runner and treat compile/runtime infrastructure failures as failed cases after successful discovery.

## 4. Rust Runner

- [x] 4.1 Implement a Rust harness generator that includes or otherwise wires a single-file Rust solution into a temporary executable.
- [x] 4.2 Implement Rust deep equality, inequality, membership, primitive expression, and numeric tolerance helpers.
- [x] 4.3 Implement Rust execution for normal return-value cases, loop tests, and mutation-style cases.
- [x] 4.4 Implement Rust stdout/stderr capture checks for raw output expectations.
- [x] 4.5 Implement Rust exception-style expectations using `panic!` and `catch_unwind`.
- [x] 4.6 Ensure `HashMap<String, V>` mutation lookups accept owned `String` keys such as `String::from("items")`.
- [x] 4.7 Route `execute_case` through the Rust runner and treat compile/runtime infrastructure failures as failed cases after successful discovery.

## 5. Regression Coverage and Verification

- [x] 5.1 Update generate/test language validation tests to include `cpp` and `rust`.
- [x] 5.2 Add missing-tester tests for `tester.cpp` and `tester.rs`.
- [x] 5.3 Add C++ pass/fail execution tests for simple functions, nested values with `None`, numeric tolerance, output expectations, exceptions, loops, and mutation-style cases.
- [x] 5.4 Add Rust pass/fail execution tests for simple functions, nested non-deque values with `None`, numeric tolerance, output expectations, exceptions, loops, mutation-style cases, and owned `String` map lookup.
- [x] 5.5 Add or mark Rust deque-specific coverage so deque behavior is skipped for Rust while remaining covered for non-Rust targets.
- [x] 5.6 Run the full test suite and confirm OpenSpec status reports the change as ready to apply or archive.
