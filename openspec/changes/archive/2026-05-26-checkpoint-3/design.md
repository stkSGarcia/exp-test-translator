## Context

`babel_code_goat.py` translates Python `tests.py` assertions into language-specific tester files. The parser (`parse_tests` / `_collect_stmts` / `_match_assert`) currently only recognises four assertion shapes: `EP(args) == expected`, `EP(args) != expected`, `EP(args)` (truthy), and `not EP(args)` (falsy). Tolerance helpers (`math.isclose`, `abs(a-b) < tol`) are already handled as special pre-passes inside `_match_assert`.

Checkpoint 3 requires the parser to also accept three new shapes while keeping each test traceable to exactly one entrypoint call:

1. **RHS call** — `assert X == EP(args)` (or `!=`)
2. **Membership** — `assert EP(args) in container`
3. **Primitive-wrapped call** — `assert prim(EP(args)) == X` (or `!=`)

## Goals / Non-Goals

**Goals:**
- Recognise all three new assertion shapes in the parser
- Represent them faithfully in the `TestCase` IR with minimal new fields
- Emit correct tester code for all three shapes in Python, JavaScript, and TypeScript
- Keep the single-call invariant: every test traces to exactly one `ENTRYPOINT` invocation

**Non-Goals:**
- Primitive operations on the RHS (e.g. `assert X == sorted(EP(args))`) — not in spec
- Chained comparisons (`a < EP(args) < b`) — not in spec
- Multi-argument primitives (e.g. `sorted(EP(args), key=…)`) — too complex, not required
- Changes to the `test` sub-command or its JSON output format

## Decisions

### D1 — RHS call: swap at parse time, no IR change

When `EP(args)` appears on the right of `==` or `!=`, swap `args` and `expected` during parsing so the IR stays `kind="eq"/"ne"` with `args=call_args, expected=constant`. This avoids adding a "direction" field to `TestCase`.

*Alternative considered*: store a `call_side: Literal["left","right"]` flag — rejected because equality is symmetric and emitters would need to duplicate logic.

### D2 — Membership: new `kind="in"`

`assert EP(args) in container` becomes `kind="in"`, `args=call_args`, `expected=container`. Emitters check `result in expected` (Python) or `expected.some(x => deepEq(x, result))` (JS/TS).

*Alternative considered*: treat as `kind="truthy"` with a wrapper expression — rejected because the container value must be encoded/transmitted to the tester and membership semantics are distinct from a truthy call result.

### D3 — Primitive-wrapped call: new `transform` field on `TestCase`

`assert prim(EP(args)) == X` sets `kind="eq"/"ne"`, `args=call_args`, `expected=X`, and a new `transform: str | None` field carrying the primitive name (e.g. `"sorted"`). Emitters apply the transform to the raw call result before comparing.

Supported primitives: `sorted`, `len`, `list`, `set`, `tuple`, `str`, `int`, `float`, `abs`, `sum`, `min`, `max`. These are recognised by name in `_match_assert`; any other wrapping call is not a match.

*Alternative considered*: encode a full "transform expression" as a string and `eval` it in the tester — rejected due to security concerns and cross-language complexity.

### D4 — JS/TS primitive equivalents

| Python    | JavaScript / TypeScript                                               |
|-----------|-----------------------------------------------------------------------|
| `sorted`  | `arr => [...arr].sort((a,b) => typeof a==='number'?a-b:String(a)<String(b)?-1:1)` |
| `len`     | `v => Array.isArray(v)?v.length:(typeof v==='string'?v.length:Object.keys(v).length)` |
| `list`    | `v => Array.isArray(v)?[...v]:Array.from(v)` |
| `set`     | `v => ({__isSet:true, items:[...new Set(v)]})` |
| `tuple`   | `v => Array.isArray(v)?[...v]:Array.from(v)` |
| `str`     | `v => String(v)` |
| `int`     | `v => Math.trunc(Number(v))` |
| `float`   | `v => Number(v)` |
| `abs`     | `v => Math.abs(v)` |
| `sum`     | `v => v.reduce((a,b)=>a+b,0)` |
| `min`     | `v => Math.min(...v)` |
| `max`     | `v => Math.max(...v)` |

These are emitted as a static `_TRANSFORMS` lookup table inside each generated tester.

### D5 — `_match_assert` pre-pass order

The existing pre-passes for `math.isclose` and `abs(…) < tol` are checked first (they call `_match_isclose` / `_match_abs_tol`). The new primitive-wrapped pattern (`prim(EP(args)) op expected`) is inserted before the plain `ast.Compare` path so it has priority. RHS-call detection is added inside the `ast.Compare` branch. The `ast.In` membership branch is added alongside existing `ast.Eq` / `ast.NotEq`.

## Risks / Trade-offs

**`sorted` numeric vs lexicographic sort in JS** — Python sorts numbers numerically; JS `.sort()` defaults to lexicographic. The D4 mapping uses a comparator that branches on `typeof`. This matches common usage but diverges from Python if the list contains mixed types. Mitigation: document that `sorted` on mixed-type containers has undefined cross-language behaviour (out of spec anyway).

**`kind="in"` with tolerance** — membership with float tolerance (e.g. `assert f(x) in [1.0, 2.0]` plus `--tol`) is theoretically possible but the spec does not require it. For now, tolerance fields are ignored for `kind="in"`. Risk is low; the spec only demonstrates `in` with integer containers.

**New `transform` field serialised into tester** — all three emitters embed `transform` in the JSON case data. Old testers (generated before this change) don't have the field; this is fine because they are never mixed with the new runner logic — both tester and runner are always generated/run together.
