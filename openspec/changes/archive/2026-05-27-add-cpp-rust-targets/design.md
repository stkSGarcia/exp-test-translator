## Context

`babel_code_goat.py` is a single-file tool. All language targets are handled by three dicts:
- `_TESTER_NAMES`: lang → output filename
- `_EMITTERS`: lang → `emit_*(cases, entrypoint) -> str`
- `_SUBPROC`: lang → `(tester_path, sol_path) -> [cmd]`

`_lang_type` validates the lang argument for `generate`; `cmd_test` validates for `test` (manual, to emit error JSON). The test runner passes the solution file path as the first argument to the tester subprocess, plus `_BCG_RESULTS_FILE` and `_BCG_TOL` via env.

Python/JS/TS are purely interpreted: the tester script dynamically imports the solution at runtime. C++ and Rust are compiled languages, which changes the execution model.

## Goals / Non-Goals

**Goals:**
- Add `--lang cpp` and `--lang rust` to both `generate` and `test`
- Full value-model parity with interpreted targets (including `None`, all collection types)
- `test` errors (status: error, exit 2) when `tester.cpp`/`tester.rs` is missing
- Skip deque-based tests for Rust (emit with comment, not silently drop)

**Non-Goals:**
- Cargo/CMake project support — single-file compilation only
- Cross-compilation or non-standard toolchain support
- Windows-native toolchain (`cl.exe`) — only `g++`/`clang++` and `rustc`

## Decisions

### Compilation strategy for C++

**Decision**: Compile `tester.cpp` and `solution.cpp` together as separate translation units.
```
g++ -std=c++17 {tester_path} {solution_path} -o {bin_path}
```
`tester.cpp` declares `extern` the entrypoint signature; the linker resolves it from the solution translation unit. The binary is written to a temp file (`tempfile.mkstemp`) and cleaned up after the run.

**Alternatives considered**:
- `#include "solution.cpp"` inside tester.cpp — creates a dependency on the relative filename "solution.cpp" and embeds solution path at generate time, not test time.
- `-include /abs/path` compiler flag — less portable and less standard than separate TU linking.

### Compilation strategy for Rust

**Decision**: At test time, write a temporary `runner.rs` that textually concatenates solution content and tester content, then compile with `rustc`.
```
rustc --edition 2021 {runner_path} -o {bin_path}
```
`tester.rs` defines `main()` and all test helpers; solution functions appear first in the combined file.

**Alternatives considered**:
- `include!()` macro inside tester.rs — requires the solution path to be known at `generate` time or forces a temp-copy step; textual concatenation is simpler.
- Multi-crate Cargo workspace — too heavy; contradicts single-file tool philosophy.
- Compile-time linking (`rustc tester.rs --extern`) — Rust's `extern` model requires compiled `.rlib` artifacts, not source.

### Compile-then-run in `cmd_test`

**Decision**: Introduce a `_COMPILE` dict mapping lang → optional compile function, called before `_SUBPROC`.

```python
_COMPILE = {
    "cpp":  lambda tester, sol, out: ["g++", "-std=c++17", str(tester), str(sol), "-o", str(out)],
    "rust": lambda tester, sol, out: None,   # handled specially (concat step)
}
```

`cmd_test` checks `_COMPILE.get(lang)` and runs that step first using a `tempfile.mkstemp`-derived binary path. Compile failure → `_error_exit()`. The binary is cleaned up in a `finally` block.

This is additive: interpreted langs have no `_COMPILE` entry and follow the existing path.

### Null/None encoding

C++ uses `std::optional<T>` with `std::nullopt` for `None`. Rust uses `Option<T>` with `None`/`Some(v)`.

JSON null → C++ `std::nullopt` / Rust `None`. Containers containing null are typed as `optional<T>`.

### Deque skip for Rust

Python's `collections.deque` maps cleanly to C++'s `std::deque<T>` but Rust's `VecDeque<T>` has a different API surface. Rather than emit broken Rust code, test cases whose args or expected values contain `__deque__` are emitted as `SKIP` entries in the Rust tester (with a `// skipped: deque not supported` comment). The test ID appears in neither `passed` nor `failed` — similar to how Python's `@pytest.mark.skipif` is handled in the existing testers.

Wait — the spec requires all test IDs to appear in `passed` or `failed`. Deque-skipped tests should appear in `failed` with a clear message, or alternatively a new `skipped` status key.

**Revised decision**: Rust deque-skipped tests emit a test case that unconditionally marks itself as failed with a skip message. This keeps the coverage invariant (all IDs accounted for) while signaling clearly that deque support is absent.

### Value type mapping

| Python type | C++ type | Rust type |
|---|---|---|
| `None` | `std::nullopt` / `std::optional<T>` | `None` / `Option<T>` |
| `bool` | `bool` | `bool` |
| `int` | `long long` | `i64` |
| `float` | `double` | `f64` |
| `Decimal` | `long double` | `f64` (precision loss noted) |
| `str` | `std::string` | `String` |
| `list` | `std::vector<T>` | `Vec<T>` |
| `tuple` | `std::tuple<Ts...>` or `std::vector<T>` | tuple or `Vec` |
| `dict` | `std::map<K,V>` | `BTreeMap<K,V>` |
| `set`/`frozenset` | `std::set<T>` | `BTreeSet<T>` |
| `Counter` | `std::map<K,long long>` | `BTreeMap<K,i64>` |
| `deque` | `std::deque<T>` | skipped |
| `defaultdict` | `std::map<K,V>` | `BTreeMap<K,V>` |

### Results protocol for compiled binaries

Compiled binaries read `_BCG_RESULTS_FILE` from env (same as interpreted testers) and write the JSON results file. `_BCG_TOL` is also read from env for global tolerance. No protocol changes needed.

## Risks / Trade-offs

- **Compiler not on PATH** → `subprocess.run` raises `FileNotFoundError`; caught and mapped to `_error_exit()`. User gets `status: error` with a stderr message.
- **C++ temp binary cleanup** → use `try/finally`; if cleanup fails (e.g., permission issue), leftover temp files in `/tmp` are harmless.
- **Rust concatenation correctness** → if solution.rs and tester.rs both define items with the same name, the compile will fail. Documented as a user responsibility (entrypoint name is the integration point).
- **Long double precision (C++)** → matches checkpoint spec; not a concern beyond that.
- **`f64` Decimal precision (Rust)** → lossy but matches checkpoint spec.

## Migration Plan

Additive change — no existing behavior modified. Deploy by replacing `babel_code_goat.py`.
