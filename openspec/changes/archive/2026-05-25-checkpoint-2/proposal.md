## Why

The test harness (checkpoint 1) supports only basic Python value types and a single `raises`-any pattern. Checkpoint 2 extends it to cover richer Python test idioms: additional container types (`set`, `frozenset`, `Counter`, `deque`, `defaultdict`, `Decimal`), flexible dict key types, float tolerance (global via `--tol` and per-assert overrides), and typed exception + message assertions.

## What Changes

- The `generate` command parser gains support for:
  - Dict keys of any hashable constant type (int, float, bool, tuple, etc.), not just strings
  - `set` / `frozenset` literals as argument and expected value types
  - `collections.Counter`, `collections.deque`, `collections.defaultdict` literals
  - `decimal.Decimal` literals
  - Typed raises blocks: `except ValueError as e: assert "msg" in str(e)` (and regex variant)
  - `math.isclose(a, b, abs_tol=..., rel_tol=...)` tolerance overrides per assertion
  - `abs(a - b) < tol` / `<= tol` tolerance overrides per assertion
- The `test` command gains `--tol <float>` to set a default float comparison tolerance
- The emitted tester files (Python, JS, TS) are updated to handle the above types and tolerance logic

## Capabilities

### New Capabilities

*(none — all changes extend existing capabilities)*

### Modified Capabilities

- `test-harness-generate`: Parser and emitters extended to support richer value types, additional container types, Decimal, per-assert tolerance syntax, and typed/message raises assertions
- `test-harness-run`: `test` command gains `--tol` flag; tester execution updated to apply global and per-assert float tolerance

## Impact

- `babel_code_goat.py` — sole implementation file; parser, value helpers, emitters, and CLI all need updates
- No new external dependencies; `decimal`, `math`, `collections` are stdlib
- Emitted tester files grow slightly in size due to tolerance and typed-raise logic
