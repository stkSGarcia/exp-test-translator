## 1. IR changes

- [x] 1.1 Add `transform: str | None = None` field to `TestCase` dataclass
- [x] 1.2 Add `"in"` as a valid `kind` literal to `TestCase` (update type annotation)

## 2. Parser — new assertion shapes

- [x] 2.1 In `_match_assert`, add detection of RHS call for `ast.Eq`: when `test.left` is a constant value and `test.comparators[0]` is an EP call, swap to produce `kind="eq"` with `args` from the RHS call
- [x] 2.2 In `_match_assert`, add same RHS detection for `ast.NotEq`
- [x] 2.3 In `_match_assert`, add detection of `ast.In` operator: when `test.left` is an EP call and op is `ast.In`, produce `kind="in"` with `expected=container`
- [x] 2.4 In `_match_assert`, add detection of primitive-wrapped call: before the plain `ast.Compare` branch, check if `test.left` is a `Call` to a supported primitive whose sole argument is an EP call; if so, extract `transform`, `args`, and `expected`
- [x] 2.5 Define the set of supported primitive names (`SUPPORTED_PRIMITIVES`) as a module-level constant: `{"sorted","len","list","set","tuple","str","int","float","abs","sum","min","max"}`
- [x] 2.6 Ensure `_match_isclose` and `_match_abs_tol` pre-passes remain before the new primitive-wrapped branch (order: isclose → abs_tol → primitive-wrapped → plain compare)

## 3. Python emitter

- [x] 3.1 Add `"transform": tc.transform` to the case dict inside `emit_python`
- [x] 3.2 In the generated `_run()` function, after calling `fn(*args)` and before comparison, apply `transform` when it is not `None`: `result = globals()[transform](result)` (all supported primitives are builtins accessible via `globals()` in Python, or use `__builtins__` dict; note `sorted` is a builtin)
- [x] 3.3 In the generated `_run()` function, handle `kind="in"`: check `result in expected` using deep equality (iterate expected and compare with `_deep_eq`) and append to `passed`/`failed` accordingly

## 4. JavaScript emitter

- [x] 4.1 Add `"transform": tc.transform` to the case dict inside `emit_javascript`
- [x] 4.2 Add a `_TRANSFORMS` object to the generated JS tester mapping each supported primitive name to its JS equivalent function (see design D4 table)
- [x] 4.3 In the generated `run()` function, after calling `fn(...args)` and before comparison, apply `_TRANSFORMS[c.transform](result)` when `c.transform` is not null
- [x] 4.4 In the generated `run()` function, handle `kind="in"`: check membership using `expected.some(x => deepEq(x, result))` (treating `expected` as the decoded container from the case)

## 5. TypeScript emitter

- [x] 5.1 Add `transform: string | null` to the `Case` interface in the generated TS tester
- [x] 5.2 Add `"transform": tc.transform` to the case dict inside `emit_typescript`
- [x] 5.3 Add a `_TRANSFORMS` object to the generated TS tester (same mappings as JS, with appropriate type annotations)
- [x] 5.4 In the generated `run()` function, apply transform when not null
- [x] 5.5 In the generated `run()` function, handle `kind="in"` using `deepEq`-based membership check

## 6. Verification

- [x] 6.1 Manually test `assert 3 == add(1, 2)` (RHS call) produces correct tester for `--lang python`
- [x] 6.2 Manually test `assert add(1, 2) in [1, 2, 3]` produces correct tester for `--lang python`
- [x] 6.3 Manually test `assert sorted(f([3, 1, 2])) == [1, 2, 3]` produces correct tester for `--lang python`
- [x] 6.4 Run the same three patterns with `--lang javascript` and verify the generated `tester.js` executes correctly with `node`
- [x] 6.5 Confirm that `assert custom_fn(f(1)) == 2` (unsupported primitive) produces no test case and no error
- [x] 6.6 Confirm that `assert f(1) == f(2)` (two EP calls) produces no test case
