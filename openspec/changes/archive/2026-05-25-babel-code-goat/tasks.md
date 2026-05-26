## 1. CLI Skeleton and Entry Point

- [x] 1.1 Create `babel_code_goat.py` with `argparse` sub-commands `generate` and `test`
- [x] 1.2 Add `--entrypoint` and `--lang` flags to `generate`; add `--lang` flag to `test`
- [x] 1.3 Validate `--lang` is one of `python`, `javascript`, `typescript` in both sub-commands; exit non-zero (error JSON for `test`) on invalid value

## 2. Test IR (Intermediate Representation)

- [x] 2.1 Define `TestCase` dataclass with fields: `id`, `kind`, `args`, `expected`, `expect_stdout`, `expect_stderr`
- [x] 2.2 Implement value serializer that converts `None/bool/int/float/str/list/tuple/dict` to JSON-safe form

## 3. tests.py Parser

- [x] 3.1 Implement AST-based parser that walks `tests.py` and emits `TestCase` objects
- [x] 3.2 Handle `assert ENTRYPOINT(args) == expected` → kind `eq`
- [x] 3.3 Handle `assert ENTRYPOINT(args) != expected` → kind `ne`
- [x] 3.4 Handle `assert ENTRYPOINT(args)` → kind `truthy`
- [x] 3.5 Handle `assert not ENTRYPOINT(args)` → kind `falsy`
- [x] 3.6 Handle raise-any `try/except` block → kind `raises`
- [x] 3.7 Scan preceding comment lines for `# expect_stdout:` and `# expect_stderr:` annotations and attach to next test
- [x] 3.8 Discover assertions inside function bodies (not just top-level)
- [x] 3.9 Assign line-based IDs (`tests.py:<line>`); append `#0`, `#1` suffix when multiple tests share a line

## 4. Code Generators

- [x] 4.1 Implement `emit_python(cases, entrypoint) -> str` that produces a self-contained `tester.py`
- [x] 4.2 Implement `emit_javascript(cases, entrypoint) -> str` that produces a self-contained `tester.js`
- [x] 4.3 Implement `emit_typescript(cases, entrypoint) -> str` that produces a self-contained `tester.ts`
- [x] 4.4 Each emitted tester accepts solution path as CLI arg, loads the solution, resolves entrypoint (function or class-method form), runs all cases, and writes results to a temp JSON file path provided via env var
- [x] 4.5 Each emitter handles `expect_stdout`/`expect_stderr` by capturing output during the call and comparing exactly

## 5. `generate` Command Implementation

- [x] 5.1 Locate `tests.py` in `<tests_dir>`; exit non-zero if missing (no tester file created)
- [x] 5.2 Parse `tests.py` and build `TestCase` list; exit non-zero on parse error (no tester file created)
- [x] 5.3 Write tester file atomically (write to temp file, then rename) to ensure no partial file on error
- [x] 5.4 Exit `0` on success

## 6. `test` Command Implementation

- [x] 6.1 Check that the expected tester file (`tester.py`/`tester.js`/`tester.ts`) exists; if not, print error JSON and exit `2`
- [x] 6.2 Create a temp file for results JSON and pass its path to the tester subprocess via env var
- [x] 6.3 Run tester subprocess (`python tester.py <solution>` / `node tester.js <solution>` / `npx tsx tester.ts <solution>`)
- [x] 6.4 Read results from temp file; if missing or unparseable, output `{"status":"error","passed":[],"failed":[]}` and exit `2`
- [x] 6.5 Determine final `status`: `"pass"` if `failed` is empty, `"fail"` if `failed` is non-empty, `"error"` on discovery failure
- [x] 6.6 Print exactly one JSON line to stdout with keys `status`, `passed`, `failed`
- [x] 6.7 Exit `0`/`1`/`2` based on status

## 7. Tester Runtime Helpers (shared across generators)

- [x] 7.1 Python tester: deep equality helper that treats `tuple` and `list` as equivalent for comparison purposes
- [x] 7.2 JS/TS tester: deep equality helper matching the same semantics (arrays equal tuples)
- [x] 7.3 Python tester: stdout/stderr capture using `io.StringIO` context manager
- [x] 7.4 JS/TS tester: stdout/stderr capture by monkey-patching `process.stdout.write` / `process.stderr.write`

## 8. End-to-End Verification

- [x] 8.1 Manually test `generate` + `test` round-trip with a Python solution for all assertion kinds
- [x] 8.2 Manually test round-trip with a JavaScript solution
- [x] 8.3 Manually test round-trip with a TypeScript solution
- [x] 8.4 Verify `test` errors correctly when tester file is absent
- [x] 8.5 Verify `generate` leaves no tester file when `tests.py` is missing
- [x] 8.6 Verify coverage rule: unexecuted tests appear in `failed`
