## Context

`babel_code_goat.py` is a single-file CLI with three layers: a Python AST parser (`parse_tests`), an IR (`TestCase`), and code emitters for Python/JS/TS. Checkpoint 1 supports `None`, `bool`, `int`, `float`, `str`, `list`, `tuple`, `dict` (string keys only), and a single `raises`-any pattern. The parser uses `_ast_to_value` to convert AST nodes to Python values, which are then serialised to JSON and embedded in emitted tester code.

The constraint is that all values must be serialisable to JSON (the transport between `parse_tests` and the emitted tester). Types that have no direct JSON equivalent (`set`, `frozenset`, `Decimal`, `Counter`, `deque`, `defaultdict`) require a tagged-value encoding strategy.

## Goals / Non-Goals

**Goals:**
- Support any hashable constant as a dict key (int, float, bool, tuple of constants, etc.)
- Parse `set`/`frozenset` literals and the four `collections` types + `Decimal` as values
- Add `--tol <float>` to `test` and thread it into the tester subprocess
- Parse `math.isclose(a, b, abs_tol=..., rel_tol=...)` and `abs(a-b) < tol` / `<= tol` as per-assertion tolerance overrides
- Parse typed raises blocks with optional string-contains and regex message assertions
- Emit correct comparison logic in Python/JS/TS testers for all new types

**Non-Goals:**
- Supporting arbitrary Python expressions (comprehensions, lambdas, generator calls)
- Full `numpy`/`pandas` type support
- Tolerance for non-numeric comparisons
- Cross-assert `--tol` propagation into JS/TS (only Python tester needs to handle Decimal; JS/TS receive numeric JSON values)

## Decisions

### Tagged-value encoding for non-JSON types

**Decision:** Represent non-JSON-serialisable values as `{"__type__": "<tag>", "value": <json-safe-repr>}` objects in the embedded case data.

**Rationale:** JSON is the only reliable zero-dependency transport between the Python parser and all three emitted testers. A tagged dict is unambiguous, inspectable, and easy to decode in Python, JS, and TS with a small helper. Alternatives like pickle (Python-only), repr (Python-only, eval is unsafe), or base64-encoded bytes all have higher coupling or security issues.

**Tags:**
| Python type | tag | value field |
|---|---|---|
| `set` | `"set"` | sorted list of elements (elements must themselves be JSON-encodable after recursion) |
| `frozenset` | `"frozenset"` | sorted list of elements |
| `Decimal` | `"decimal"` | string representation |
| `Counter` | `"counter"` | dict of counts |
| `deque` | `"deque"` | list of elements |
| `defaultdict` | `"defaultdict"` | dict of entries (default_factory ignored for comparison) |
| tuple (as key) | `"tuple"` | list of elements |

Non-string dict keys are encoded as tagged values in a parallel `keys` / `values` list pair: `{"__type__": "dict", "keys": [...], "values": [...]}`.

### Tolerance encoding in IR

**Decision:** Extend `TestCase` with two new optional fields: `tol_abs: float | None` and `tol_rel: float | None`. The `--tol` global default is passed via an environment variable `_BCG_TOL` (like `_BCG_RESULTS_FILE`) so the subprocess can read it.

**Rationale:** Embedding tolerance per case avoids global state in the tester and allows per-assert overrides to coexist cleanly with the global default. The global `--tol` becomes the fallback when no per-assert override exists.

### Typed raises IR

**Decision:** Extend `TestCase` `kind="raises"` to optionally carry `exc_type: str | None`, `msg_contains: str | None`, and `msg_regex: str | None`.

**Rationale:** A separate `kind` value (e.g. `"raises_typed"`) would duplicate all the dispatch logic. Extending the existing `raises` kind with optional fields keeps the emitter switch simple: if `exc_type` is `None`, behave as before; otherwise add the type check and message match.

### Parser for tolerance overrides

**Decision:** Detect tolerance overrides by matching `assert math.isclose(a, b, ...)` and `assert abs(a - b) < tol` / `<= tol` at the AST level inside `_match_assert`. If matched, extract `abs_tol` / `rel_tol` and rewrite the test as `kind="eq"` with the tolerance fields set.

**Rationale:** These are the two idioms explicitly listed in checkpoint 2. AST matching is precise and doesn't require regex on source text.

## Risks / Trade-offs

- **Set element ordering in JS/TS:** JS `Set` and Python `set` are unordered. Comparison must check that each element exists in the other set (O(n²) for sets of complex objects). → Mitigation: implement `setEq` helper in emitters that iterates and deep-compares.
- **Decimal in JS/TS:** JSON transmits `Decimal` as a string tag. JS/TS testers decode it as a plain number (parseFloat). This may lose precision for very large decimals. → Acceptable for test harness use; document limitation if needed.
- **`defaultdict` default_factory:** The factory type is not transmitted (only the populated entries). A `defaultdict(int)` with no entries compares equal to `{}`. → Acceptable; tests that care about default values will have entries.
- **`math.isclose` relative tolerance in emitters:** Python's `math.isclose` default `rel_tol=1e-9` differs from JS's typical `Number.EPSILON`. → Use the extracted `rel_tol` and `abs_tol` values explicitly in all emitters; do not use language defaults.
