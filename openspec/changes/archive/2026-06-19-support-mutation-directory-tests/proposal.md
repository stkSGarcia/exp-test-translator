## Why

The current test discovery contract is centered on a single `tests.py` file and direct entrypoint-return assertions. The next checkpoint requires the CLI to recognize tests spread across a directory tree and to support mutation-style problems where the entrypoint mutates an argument rather than returning the asserted value.

## What Changes

- Discover tests recursively from any `.py` file under `<tests_dir>` instead of requiring `<tests_dir>/tests.py`.
- Treat test-like non-Python files under `<tests_dir>` as discovery errors.
- Report a discovery error when no tests are found anywhere under `<tests_dir>`.
- Support mutation-style tests only when an entrypoint call appears as a statement or assignment and is immediately followed by one or more valid asserts.
- Require every mutation-style follow-up assert to reference at least one variable passed to, or directly assigned from, the mutation entrypoint call.
- Reject mutation patterns that do not satisfy the explicit shape and variable-reference constraints.
- Change test IDs to use each test file's forward-slash relative path from `<tests_dir>` followed by line-number and existing uniqueness suffixes.

## Capabilities

### New Capabilities

### Modified Capabilities
- `babel-code-goat-cli`: Expand test discovery sources, mutation-style test recognition, discovery errors, and test ID formats.

## Impact

- Affects the CLI discovery pipeline used by `generate` and `test`.
- Affects generated testers for Python, JavaScript, and TypeScript because discovered test IDs and mutation-style execution data must be preserved across languages.
- Requires tests for recursive file discovery, invalid test-like files, empty discovery, constrained mutation-style validity, and relative-path test ID output.
