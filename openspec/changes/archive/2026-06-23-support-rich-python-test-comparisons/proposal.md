## Why

Python tests written for the translation harness need to express realistic expected values and exception checks without being rejected during discovery. The current contract is limited to string-keyed dictionaries, a small primitive value set, generic raise-any blocks, and exact numeric comparison, which blocks common Python test cases from being translated and evaluated.

## What Changes

- Expand allowed Python test values to include dictionaries with any supported key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal`.
- Compare the additional containers according to their Python container meaning, including nested structures and numeric comparisons involving `Decimal`.
- Add a `test --tol <float>` flag that sets the default tolerance for applicable float or numeric comparisons, including nested structures.
- Recognize per-assert tolerance overrides expressed with `math.isclose(...)` and `abs(a - b) < tol` or `abs(a - b) <= tol`.
- Extend raise expectations from raise-any blocks to typed exception assertions with substring and regex message matching.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expand supported Python test literals, comparison semantics, tolerance controls, and raise assertion forms.

## Impact

- Affects Python `tests.py` discovery, test model representation, generated tester behavior, and the `test` command CLI.
- Requires updates to Python, JavaScript, and TypeScript tester generation where translated comparison semantics are shared across target languages.
- Adds coverage for richer Python value literals, tolerance-aware numeric comparisons, and typed/message-matching exception assertions.
