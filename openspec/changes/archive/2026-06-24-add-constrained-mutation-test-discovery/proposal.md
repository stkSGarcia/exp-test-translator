## Why

Many algorithm tests use in-place mutation patterns, where the entrypoint mutates a list or object and later assertions inspect the mutated value. The current discovery contract also requires a root `tests.py`, which prevents users from organizing tests across recursive Python files under the tests directory.

## What Changes

- Discover mutation-style tests when an entrypoint call appears as a standalone statement or assignment and is immediately followed by one or more assertions that inspect the mutated argument or assigned result.
- Reject mutation-style patterns that are separated from their assertions, whose assertions call the entrypoint again, or whose assertions do not reference any mutated or directly assigned variable.
- Discover tests recursively from all `.py` files under `<tests_dir>` instead of requiring a root `tests.py`.
- Treat test-like non-Python files under `<tests_dir>` as discovery errors.
- Report a discovery error when recursive scanning finds no tests.
- Generate test IDs with the Python file path relative to `<tests_dir>` using forward slashes, while preserving line and same-line suffix behavior.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Test discovery source, allowed constructs, mutation-style traceability, discovery errors, and test ID generation change for recursive Python test files.

## Impact

- Affects Python AST discovery and validation in `babel_code_goat.py`.
- Affects generated tester payloads and execution for Python, JavaScript, and TypeScript targets so mutation-style tests invoke the entrypoint before evaluating follow-up assertions.
- Affects CLI behavior for `generate` and `test` whenever `<tests_dir>` contains nested test files, test-like non-Python files, no tests, or mutation-style blocks.
- Requires updates to discovery, generation, execution, and CLI tests in `tests/test_babel_code_goat.py`.
