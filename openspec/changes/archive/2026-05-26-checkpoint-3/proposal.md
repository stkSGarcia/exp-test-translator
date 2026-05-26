## Why

The test harness currently only recognises assertions where the entrypoint call sits as the top-level left operand of a comparison or a bare `assert`. Checkpoint 3 extends recognition to three more natural assertion forms — call on the right-hand side, membership tests, and entrypoint calls wrapped in a single primitive operation — while preserving the single-call-per-test invariant.

## What Changes

- Parser recognises `assert expected == ENTRYPOINT(args)` and `assert expected != ENTRYPOINT(args)` (call on RHS — treated symmetrically by swapping expected/args at parse time)
- Parser recognises `assert ENTRYPOINT(args) in container` as a membership assertion (new `"in"` kind)
- Parser recognises `assert prim(ENTRYPOINT(args)) == expected` and `assert prim(ENTRYPOINT(args)) != expected` where `prim` is any supported primitive operation (`sorted`, `len`, `list`, `set`, `tuple`, `str`, `int`, `float`, `abs`, `sum`, `min`, `max`)
- `TestCase` IR gains a `transform` field (string or None) to carry the primitive operation name
- All three emitters (Python, JavaScript, TypeScript) updated to apply `transform` before comparison and to handle the `"in"` kind

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `test-harness-generate`: New assertion patterns (RHS call, membership, primitive-wrapped call) are recognised and emitted; `"in"` test-case kind added; `transform` field added to emitted case data

## Impact

- `babel_code_goat.py`: `TestCase` dataclass; `_match_assert`, `_match_isclose`, `_match_abs_tol` parser helpers; `emit_python`, `emit_javascript`, `emit_typescript` emitter functions
