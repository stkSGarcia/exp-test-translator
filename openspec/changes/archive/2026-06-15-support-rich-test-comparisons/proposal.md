## Why

The current test translation contract only covers a small literal and assertion surface, which prevents real Python tests from expressing common comparison cases. The checkpoint expands the harness so translated tests can preserve Python container semantics, numeric tolerance intent, and precise exception expectations.

## What Changes

- Allow dictionary keys to use any supported valid key type expressible in tests, rather than only strings.
- Add support for `set`, `frozenset`, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` values in arguments and expectations.
- Add a `test --tol <float>` flag that sets the default floating-point comparison tolerance where numeric tolerance is applicable, including nested structures.
- Recognize per-assert tolerance overrides from `math.isclose(...)` and `abs(a - b) < tol` / `<= tol` assertion patterns.
- Treat `decimal.Decimal` values as numeric values for comparison behavior.
- Support typed exception assertions with message substring checks and regular-expression message matching.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expands allowed values, comparison semantics, `test` flags, per-assert tolerance discovery, and exception assertion support.

## Impact

- Updates the Python test discovery and validation rules for richer literal and constructor forms.
- Updates generated tester metadata or runner behavior as needed to carry default and per-test tolerance information.
- Updates cross-language comparison logic so Python, JavaScript, and TypeScript harness execution preserves set-like, mapping, sequence, decimal, and numeric tolerance semantics.
- Extends CLI parsing for `test --tol <float>` while preserving the existing JSON output and exit-code contract.
