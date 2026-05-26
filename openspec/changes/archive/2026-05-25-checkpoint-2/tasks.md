## 1. IR & Value Helpers

- [x] 1.1 Extend `TestCase` dataclass with `tol_abs: float | None`, `tol_rel: float | None`, `tol_strict: bool` (for `<` vs `<=`), `exc_type: str | None`, `msg_contains: str | None`, `msg_regex: str | None`
- [x] 1.2 Extend `_ast_to_value` to handle `set` and `frozenset` literals (`ast.Set`)
- [x] 1.3 Extend `_ast_to_value` to handle `collections.Counter(...)`, `collections.deque(...)`, `collections.defaultdict(...)` call nodes
- [x] 1.4 Extend `_ast_to_value` to handle `decimal.Decimal(...)` / `Decimal(...)` call nodes
- [x] 1.5 Allow non-string dict keys in `_ast_to_value` dict handling (pass through `_ast_to_value` on keys)
- [x] 1.6 Extend `_to_json_value` to encode non-JSON-native types using tagged-value objects (`{"__type__": "set", "value": [...]}`, `"dict"` with parallel keys/values for non-string-key dicts, etc.)

## 2. Parser Extensions

- [x] 2.1 Extend `_match_assert` to detect `assert math.isclose(EP(args), expected, abs_tol=..., rel_tol=...)` and return a `kind="eq"` case with `tol_abs`/`tol_rel` set
- [x] 2.2 Extend `_match_assert` to detect `assert abs(EP(args) - expected) < tol` and `<= tol` and return a `kind="eq"` case with `tol_abs` set
- [x] 2.3 Extend `_match_raises` (or add a new matcher) to detect typed raises blocks: `except SomeError as e: assert "substr" in str(e)` and `assert re.search(r"...", str(e))`
- [x] 2.4 Extend `_match_raises` to detect typed raises blocks with only `pass` (no message assertion) for named exception types (not just `Exception`)

## 3. CLI — --tol flag

- [x] 3.1 Add `--tol` optional float argument to the `test` sub-parser
- [x] 3.2 Pass the `--tol` value to the tester subprocess via environment variable `_BCG_TOL`

## 4. Python Tester Emitter

- [x] 4.1 Add tagged-value decoder to `emit_python`: a `_decode(v)` function that reconstructs `set`, `frozenset`, `Decimal`, `Counter`, `deque`, `defaultdict`, and non-string-key dicts from tagged objects
- [x] 4.2 Update `_deep_eq` in the emitted Python tester to use `_decode` and apply tolerance (`tol_abs`, `tol_rel` per case; fall back to `_BCG_TOL` env var for global default)
- [x] 4.3 Update `_run` in the emitted Python tester to handle `kind="raises"` with `exc_type`, `msg_contains`, and `msg_regex`

## 5. JavaScript Tester Emitter

- [x] 5.1 Add tagged-value decoder to `emit_javascript`: a `decode(v)` function (JS sets represented as arrays with a `__isSet` marker or compared with a `setEq` helper)
- [x] 5.2 Update `deepEq` in the emitted JS tester to handle decoded tagged values and apply tolerance per case (read `_BCG_TOL` env var as global default)
- [x] 5.3 Update `run` in the emitted JS tester to handle typed raises (`kind="raises"` with `excType`, `msgContains`, `msgRegex`)

## 6. TypeScript Tester Emitter

- [x] 6.1 Add tagged-value decoder to `emit_typescript` (same logic as JS, with types annotated)
- [x] 6.2 Update `deepEq` in the emitted TS tester for tolerance and set equality
- [x] 6.3 Update `run` in the emitted TS tester for typed raises with message matching
