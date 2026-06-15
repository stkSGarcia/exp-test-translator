## 1. Discovery Model

- [x] 1.1 Extend `TestCase` and related pending-case data to carry comparison mode, absolute tolerance, relative tolerance, expected exception type, message matcher kind, and message pattern.
- [x] 1.2 Replace the current `ast.literal_eval`-only value parser with an AST value parser for supported scalars, lists, tuples, dictionaries, set/frozenset literals, and allowed constructor calls.
- [x] 1.3 Track restricted helper imports and aliases for `math`, `re`, `collections`, `decimal`, `Counter`, `deque`, `defaultdict`, and `Decimal` without executing `tests.py`.
- [x] 1.4 Validate dictionary keys as supported hashable values and reject unhashable keys or unsupported value expressions with `DiscoveryError`.

## 2. Rich Value Encoding

- [x] 2.1 Add a deterministic tagged value representation that preserves list, tuple, dict entries, set, frozenset, counter, deque, defaultdict, decimal, and scalar values across subprocess payloads.
- [x] 2.2 Update Python case execution to decode tagged values into native comparison inputs and expected values.
- [x] 2.3 Update Node case execution to decode tagged values into JavaScript runtime equivalents and comparable expected structures.
- [x] 2.4 Update truthiness and deep comparison helpers to use container-semantic equality, non-string dictionary keys, unordered set/frozenset membership, counter counts, deque order, defaultdict mapping contents, and decimal numeric behavior.

## 3. Tolerance Support

- [x] 3.1 Add `test --tol <float>` CLI parsing, validation, and propagation into result aggregation while preserving exact JSON error output on invalid values.
- [x] 3.2 Apply the default tolerance to float and decimal equality or inequality comparisons, including nested supported containers.
- [x] 3.3 Discover `math.isclose(...)` assertions with supported entrypoint/expected operands and `abs_tol` / `rel_tol` keyword overrides.
- [x] 3.4 Discover `abs(a - b) < tol` and `abs(a - b) <= tol` assertions where one operand is the entrypoint call and the other is a supported numeric expected value.
- [x] 3.5 Ensure per-assert tolerance overrides take precedence over the `--tol` default.

## 4. Typed Exception Expectations

- [x] 4.1 Extend try/except discovery to accept typed exception handlers such as `except ValueError as e`.
- [x] 4.2 Discover substring message checks using `assert "text" in str(e)` inside typed exception handlers.
- [x] 4.3 Discover regex message checks using `assert re.search(pattern, str(e))` inside typed exception handlers.
- [x] 4.4 Update Python runner exception matching to check expected built-in exception type plus optional substring or regex message matcher.
- [x] 4.5 Update Node runner exception matching to check thrown error `name` or constructor name plus optional substring or regex message matcher.

## 5. Verification

- [x] 5.1 Add discovery tests for restricted imports, non-string dictionary keys, sets, frozensets, `Counter`, `deque`, `defaultdict`, and `Decimal`.
- [x] 5.2 Add Python execution tests for default `--tol`, omitted tolerance exactness, nested tolerance comparison, and invalid tolerance JSON error behavior.
- [x] 5.3 Add execution tests for `math.isclose`, `abs(...) < tol`, `abs(...) <= tol`, and per-assert override precedence.
- [x] 5.4 Add typed exception tests for matching type, wrong type failure, substring message matching, and regex message matching.
- [x] 5.5 Add JavaScript and TypeScript smoke coverage for tagged value decoding, tolerance comparison, and typed exception matching when Node is available.
- [x] 5.6 Run the repository test suite and `openspec status --change "support-rich-test-comparisons"` to confirm the change is apply-ready.
