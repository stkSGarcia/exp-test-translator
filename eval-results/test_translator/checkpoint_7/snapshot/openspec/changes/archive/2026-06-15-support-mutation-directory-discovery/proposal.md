## Why

The current discovery contract is centered on `<tests_dir>/tests.py` and direct assertion-style entrypoint calls, which leaves common in-place mutation tests and nested test-file layouts underspecified. This change is needed so generated testers can handle mutation-oriented problems and directory-based test suites while still failing fast on ambiguous discovery inputs.

## Related Work

### Related Changes

- `add-loop-as-test-support`: Added loop constructs and per-iteration discovery to make parameterized tests traceable. This change complements it by expanding where tests can be found and by defining another constrained non-assert-entrypoint pattern.
- `support-single-call-traceability`: Tightened discovered tests so each result maps to exactly one configured entrypoint invocation. This change extends that traceability rule to mutation calls followed by dependent assertions.
- `support-rich-test-comparisons`: Expanded assertion expressions, values, and helper behavior accepted by test translation. This change builds on that broader assertion surface while preserving discovery errors for unsupported file and mutation patterns.

### Related Specs

- `babel-code-goat-cli/add-loop-as-test-support`: Defines loop-based test parameterization and line-based test IDs under `tests.py`; this change adapts that source and ID model to recursive relative paths.
- `babel-code-goat-cli/support-single-call-traceability`: Defines the one-entrypoint-invocation discovery contract; this change applies the same unambiguous mapping to mutation-style statement or assignment calls.
- `babel-code-goat-cli/support-rich-test-comparisons`: Defines supported rich assertion forms and values; this change reuses those assertion semantics for asserts that validate mutated variables.

## What Changes

- Support mutation-style tests where an entrypoint call appears as a statement or assignment and is immediately followed by one or more validating `assert` statements.
- Reject mutation-style patterns that are not immediately followed by valid dependent assertions, or whose assertions do not reference a variable passed to or directly assigned from the mutation call.
- Discover tests from any `.py` file under `<tests_dir>` recursively instead of requiring only a root `tests.py`.
- Treat test-like non-Python files under `<tests_dir>` as discovery errors.
- Treat recursive discovery that finds no tests as a discovery error.
- Change test IDs to use the path relative to `<tests_dir>` with forward slashes, followed by line number and any same-line suffix.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend test discovery, mutation-style test validation, discovery errors, and test ID formatting.

## Impact

- Affects CLI `generate` and `test` discovery behavior for all supported target languages.
- Affects parser/discovery logic, generated tester fixtures, and ID formatting.
- No new runtime dependencies are expected.
