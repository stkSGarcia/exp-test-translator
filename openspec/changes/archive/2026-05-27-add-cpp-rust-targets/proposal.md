## Why

The test translator only supports Python, JavaScript, and TypeScript targets, leaving C++ and Rust users unable to generate or run translated testers. Adding `--lang cpp` and `--lang rust` expands the tool to two widely-used systems languages.

## What Changes

- `generate` accepts `--lang cpp` and produces `tester.cpp`
- `generate` accepts `--lang rust` and produces `tester.rs`
- `test` accepts `--lang cpp` and runs `tester.cpp`; errors if missing
- `test` accepts `--lang rust` and runs `tester.rs`; errors if missing
- All Python value types (including `None`, `bool`, `int`, `float`, `str`, `list`, `dict`, `set`, `frozenset`, `tuple`, `decimal.Decimal`, `Counter`, `deque`, `defaultdict`) are supported in C++ and Rust emitters
- C++ uses `std::optional<T>` / `std::nullopt` for `None`; Rust uses `Option<T>` / `Some` / `None`
- Rust: `collections.deque`-based tests are skipped (annotated `skipif` for Rust target)

## Capabilities

### New Capabilities
- `cpp-target`: C++ tester generation and execution — value encoding, type mapping, null handling via `std::optional`, and compilation/run harness
- `rust-target`: Rust tester generation and execution — value encoding, type mapping, null handling via `Option<T>`, and compilation/run harness

### Modified Capabilities
- `test-harness-generate`: Add `cpp` and `rust` as valid `--lang` values; produce `tester.cpp` / `tester.rs`
- `test-harness-run`: Add `cpp` and `rust` as valid `--lang` values; enforce missing-tester error for `.cpp` / `.rs`

## Impact

- `translator/emitters/`: new `cpp.py` and `rust.py` emitter modules
- `translator/runner/`: new C++ (compile + run) and Rust (cargo or rustc + run) runner logic
- `translator/cli.py` or equivalent: extend `--lang` choices to include `cpp`, `rust`
- Existing emitter and runner code is unchanged
- No new external runtime dependencies beyond a C++17 compiler (`g++`/`clang++`) and `rustc` being present on the host
