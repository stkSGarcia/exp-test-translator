## Why

The test discovery contract currently does not cover in-place mutation tests or recursive test files, so valid checkpoint tests that call the entrypoint as a statement cannot be translated reliably. The checkpoint also needs explicit discovery errors for ambiguous mutation patterns and invalid test-like files so failures stay traceable.

## Related Work

### Related Changes

- `add-loop-as-test-support`: Motivated by parameterized Python tests and source-line test IDs; this change complements it by extending discovery from single root files to recursive files while preserving line-based IDs.
- `support-rich-test-comparisons`: Motivated by broader assertion expression support; this change reuses that strict expression-discovery style for mutation assertions rather than accepting arbitrary statement sequences.
- `support-single-call-traceability`: Motivated by keeping each discovered test mapped to one configured entrypoint call; this change extends that traceability rule to statement and assignment entrypoint calls followed by dependent assertions.

### Related Specs

- `babel-code-goat-cli/support-single-call-traceability`: Defines the core test discovery source, allowed constructs, and single-entrypoint traceability behavior; this change adapts that discovery contract for mutation-style statement and assignment calls.
- `babel-code-goat-cli/support-rich-test-comparisons`: Defines richer assertion comparison handling; this change builds on that assertion parsing surface for post-mutation assertions.
- `babel-code-goat-cli/add-loop-as-test-support`: Defines loop-based tests and line-based test IDs; this change reuses the ID suffix convention and extends IDs to include relative paths from the tests directory.

## What Changes

- Discover tests recursively from any `.py` file under `<tests_dir>` instead of requiring `<tests_dir>/tests.py`.
- Treat entrypoint calls used as statements or direct assignments as mutation-style tests only when immediately followed by one or more dependent asserts.
- Reject mutation-style patterns where the required dependent assert sequence is missing, interrupted, or does not reference a mutated or assigned variable.
- Report discovery errors for non-Python files under `<tests_dir>` that use test-like names.
- Report discovery errors when recursive discovery finds no tests.
- Emit test IDs as forward-slash relative paths plus line numbers, with the existing `#<k>` suffix for multiple tests on one line.

## Capabilities

### New Capabilities

- `babel-code-goat-cli`: Covers CLI generation and execution behavior for translated test harnesses, including recursive test discovery, mutation-style test recognition, and stable test IDs.

### Modified Capabilities

- None.

## Impact

- Affects test discovery in `babel_code_goat.py`.
- Requires focused coverage in `tests/test_babel_code_goat.py` for recursive discovery, invalid test-like files, no-test errors, mutation-style success cases, and mutation-style rejection cases.
- Does not add external dependencies or change the CLI command shape.
