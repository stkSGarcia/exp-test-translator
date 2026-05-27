## 1. CLI and Dispatch Wiring

- [x] 1.1 Add `"cpp": "tester.cpp"` and `"rust": "tester.rs"` to `_TESTER_NAMES`
- [x] 1.2 Update `_lang_type` to accept `cpp` and `rust` (error message updated to list all valid langs)
- [x] 1.3 Add `"cpp"` and `"rust"` to `_EMITTERS` dict pointing to the new emitter functions (stubs OK initially)
- [x] 1.4 Update `_VALID_LANGS` (derived from `_TESTER_NAMES`, so no direct change needed if already derived)

## 2. Compile-then-Run Infrastructure in cmd_test

- [x] 2.1 Add `_COMPILE` dict mapping `"cpp"` and `"rust"` to compile-step functions `(tester_path, sol_path, bin_path) -> int`
- [x] 2.2 For Rust: add a helper that writes a temp `runner.rs` (solution.rs content + tester.rs content) and returns its path
- [x] 2.3 In `cmd_test`, before `_SUBPROC`, check `_COMPILE.get(args.lang)`; if present, run compile step in a temp dir; on `FileNotFoundError` or non-zero exit, call `_error_exit()`
- [x] 2.4 Add `_SUBPROC` entries for `"cpp"` and `"rust"` that run the compiled binary (no args needed; results via env)
- [x] 2.5 Wrap compiled-binary cleanup in `try/finally` to ensure temp binary is removed

## 3. C++ Emitter (emit_cpp)

- [x] 3.1 Implement `emit_cpp(cases, entrypoint) -> str` that generates a compilable C++17 source file
- [x] 3.2 Emit standard `#include` headers: `<iostream>`, `<fstream>`, `<vector>`, `<map>`, `<set>`, `<deque>`, `<optional>`, `<string>`, `<algorithm>`, `<stdexcept>`, `<cmath>`, `<cstdlib>`
- [x] 3.3 Implement value encoder for C++: `None → std::nullopt`, `bool`, `long long`, `long double`, `std::string`, `std::vector`, `std::map`, `std::set`, `std::deque`, `std::optional`
- [x] 3.4 Emit `extern` declaration for the entrypoint function with a signature inferred from test cases (or use a template/auto approach)
- [x] 3.5 Emit test runner loop: for each test case, call the entrypoint with encoded args, compare to expected value, record pass/fail
- [x] 3.6 Implement eq/ne comparison for each supported C++ type (recursive for containers)
- [x] 3.7 Implement raises testing using `try { } catch (...) { }`
- [x] 3.8 Implement tolerance-based comparison: read `_BCG_TOL` from env, apply `fabsl(a - b) <= tol`; per-test `tol_abs`/`tol_rel` override
- [x] 3.9 Emit `main()` that runs all test cases and writes JSON results to `_BCG_RESULTS_FILE`
- [x] 3.10 Handle `transform` (sorted, len, etc.) for C++ — implement the equivalent operations
- [x] 3.11 Handle `kind="in"` (membership) tests for C++ container types

## 4. Rust Emitter (emit_rust)

- [x] 4.1 Implement `emit_rust(cases, entrypoint) -> str` that generates a compilable Rust source file
- [x] 4.2 Emit `use` statements: `std::collections::{BTreeMap, BTreeSet}`, `std::env`, `std::fs`, `std::panic`
- [x] 4.3 Implement value encoder for Rust: `None → None`, `Some(v)` for non-None optionals, `bool`, `i64`, `f64`, `String`, `vec![]`, `BTreeMap`, `BTreeSet`
- [x] 4.4 Mark test cases with deque args/expected as auto-fail with skip message (appear in `failed`)
- [x] 4.5 Emit test runner: for each non-skipped test case, call the entrypoint with encoded args, compare to expected, record pass/fail
- [x] 4.6 Implement eq/ne comparison for each supported Rust type (derive `PartialEq` where possible, or implement recursively)
- [x] 4.7 Implement raises testing using `std::panic::catch_unwind`; mark test as passed if panic occurred
- [x] 4.8 Implement tolerance-based comparison: read `_BCG_TOL` from env, apply `(a - b).abs() <= tol`; per-test overrides
- [x] 4.9 Emit `fn main()` that runs all test cases and writes JSON results to `_BCG_RESULTS_FILE` (manual JSON serialization)
- [x] 4.10 Handle `transform` (sorted, len, etc.) for Rust — implement the equivalent operations
- [x] 4.11 Handle `kind="in"` (membership) tests for Rust container types
- [x] 4.12 Use `String::from("key")` for all HashMap/BTreeMap string key lookups

## 5. Value Type Edge Cases

- [x] 5.1 Verify `None` as a function argument emits correctly for both C++ (`std::nullopt`) and Rust (`None`)
- [x] 5.2 Verify `None` as expected value emits and compares correctly for both targets
- [x] 5.3 Verify nested containers (list of dicts, dict with set values, etc.) encode correctly in both emitters
- [x] 5.4 Verify `Counter` encodes as `std::map<K, long long>` (C++) and `BTreeMap<K, i64>` (Rust)
- [x] 5.5 Verify `defaultdict` encodes as plain map (ignoring factory) in both targets

## 6. Integration and Manual Testing

- [x] 6.1 Test `generate --lang cpp` end-to-end: produces `tester.cpp` that compiles with `g++`
- [ ] 6.2 Test `generate --lang rust` end-to-end: produces `tester.rs` that compiles via `rustc` when combined with solution (skipped: rustc not on this system)
- [x] 6.3 Test `test --lang cpp` with a passing solution: exits `0`, correct JSON
- [ ] 6.4 Test `test --lang rust` with a passing solution: exits `0`, correct JSON (skipped: rustc not available)
- [x] 6.5 Test `test --lang cpp` with `tester.cpp` missing: exits `2`, error JSON
- [x] 6.6 Test `test --lang rust` with `tester.rs` missing: exits `2`, error JSON
- [x] 6.7 Test `test --lang cpp` with a failing solution: exits `1`, correct fail JSON
- [x] 6.8 Test `generate --lang ruby` (invalid): exits non-zero, no file created
- [x] 6.9 Test `test --lang ruby` (invalid): exits `2`, error JSON
- [x] 6.10 Verify deque-containing test cases appear in `failed` for Rust target
