## Why

Mutation-style algorithm tests commonly assert that an input object was modified in place after calling the entrypoint. The discovery contract needs to accept that pattern intentionally while rejecting ambiguous mutation-like code, and tests should no longer be limited to a single root `tests.py` file.

## What Changes

- Discover mutation-style tests where an entrypoint call is a standalone statement or assignment followed immediately by one or more related asserts.
- Require each mutation-style assert to reference at least one variable passed to the mutation call or directly assigned from its result.
- Reject files that use mutation patterns outside the supported adjacency and variable-reference constraints as discovery errors.
- Discover tests recursively from any `.py` file under `<tests_dir>` instead of requiring a root-level `tests.py`.
- Treat non-Python files with test-like names as discovery errors, and report a discovery error when recursive discovery finds no tests.
- Change discovered test IDs to use the test file path relative to `<tests_dir>` with forward slashes, followed by the source line number and same-line suffixes where needed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Test discovery must support constrained mutation-style tests, recursive `.py` discovery, test-like non-Python file rejection, no-test discovery errors, and relative-path test IDs.

## Impact

- Affects Python test discovery and AST validation in `babel_code_goat.py`.
- Affects generated tester payloads and result IDs for Python, JavaScript, and TypeScript targets.
- Adds end-to-end tests for valid mutation-style tests, invalid mutation patterns, recursive discovery, test-like non-Python file errors, empty discovery errors, and relative-path ID formatting.
