## Context

The harness discovers tests from `tests.py`, serializes them into generated tester files, and re-validates discovery during `test` before invoking the selected target-language tester. Today discovery normalizes tuples to lists, requires dictionary keys to be strings, rejects sets and common Python collection types, and records only simple equality, inequality, truthy, falsy, and raise-any checks. Runtime comparison is split between Python helpers and generated JavaScript/TypeScript helper code.

This change needs richer Python test semantics while preserving the existing one-line JSON result contract, line-based IDs, and generated-tester workflow.

## Goals / Non-Goals

**Goals:**

- Accept the additional literal/container forms listed in `steps/checkpoint_2.md` during Python test discovery.
- Preserve Python container meaning for equality and inequality, including unordered set semantics, Counter counts, deque order, defaultdict default-factory-insensitive contents, and Decimal numeric values.
- Add default tolerance through `test --tol <float>` and per-assert tolerance metadata for recognized `math.isclose` and `abs(a - b) < tol` / `<= tol` forms.
- Support typed raise assertions with substring and regex message matching.
- Keep generated tester payloads deterministic and JSON-compatible.

**Non-Goals:**

- Running arbitrary Python expressions from `tests.py` during discovery.
- Supporting every `collections` type or every possible `math.isclose` spelling.
- Adding tolerance handling to truthy or falsy assertions.
- Changing the JSON result shape, test ID format, or language support matrix.

## Decisions

1. Encode discovered values with explicit type tags before JSON serialization.

   `normalize_value` should become a parser that converts supported Python literals and constructor calls into a small tagged representation, for example plain JSON primitives for existing simple values and tagged objects for `set`, `frozenset`, `Counter`, `deque`, `defaultdict`, non-string dict keys, and `Decimal`. This avoids lossy conversions such as stringifying dictionary keys or treating sets as ordered arrays. An alternative was to embed Python `repr` strings and evaluate them in testers, but that would be unsafe and unusable for JavaScript/TypeScript testers.

2. Parse only constrained constructor/import forms for the new Python-specific values.

   Discovery should accept `set(...)`, `frozenset(...)`, `Counter(...)`, `deque(...)`, `defaultdict(...)`, and `Decimal(...)` when the callee is an allowed name or imported module attribute, and all constructor arguments are themselves supported literals. Imports for `collections`, named collection classes, `decimal.Decimal`, `math`, and `re` should be allowed only when they enable these supported expressions. An alternative was to require every new value to be expressible through `ast.literal_eval`, but that cannot represent the requested collection and Decimal forms.

3. Centralize comparison semantics in generated helper functions.

   Python execution can decode tagged values back into comparable Python values or compare directly on tags. JavaScript/TypeScript testers should compare the tagged representation against normalized actual return values, including support for JS arrays/objects/Map/Set where practical. Numeric comparisons should route through a shared tolerance-aware comparator for equality and inequality, with recursive application to nested containers. An alternative was to pre-render expected values into target-language source literals, but the existing payload extraction and re-validation flow is simpler to preserve with JSON data.

4. Represent tolerance as test metadata.

   Each equality-like test should carry an optional tolerance policy: default tolerance from `test --tol`, exact mode, or per-assert overrides from `math.isclose` / absolute-difference assertions. Generated testers should receive the effective default tolerance at execution time, not during `generate`, so changing `--tol` on `test` does not require regenerating testers. Per-assert overrides remain serialized with the discovered test because they are part of test source semantics.

5. Extend raise tests with expected exception metadata.

   Raise-any remains supported, while typed blocks should store the expected exception name plus optional message matcher metadata: substring containment or regex pattern. Python testers can match actual exception classes by name and MRO; JavaScript/TypeScript testers can match error constructor names and message text. An alternative was to treat typed Python exceptions as Python-only, but the harness already translates Python tests across supported target languages.

## Risks / Trade-offs

- Tagged values increase generated payload size and helper complexity -> keep the encoding minimal, deterministic, and covered by direct discovery and execution tests.
- Python and JavaScript exception class names do not always align -> require name matching for typed assertions and fail closed when no meaningful name is available.
- Decimal has higher precision than JavaScript numbers -> preserve Decimal strings in payloads and compare as numeric strings where exact Decimal behavior matters; for target-language actual values, compare numerically within tolerance when a Decimal participates in a numeric comparison.
- Allowing imports could accidentally broaden accepted `tests.py` code -> whitelist only import forms needed for supported constructors and assertion helpers.
