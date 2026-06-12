## Why

The current discovery contract is centered on a single root `tests.py` file and only direct assertion-style entrypoint calls. Checkpoint 5 expands the accepted authoring model so translated tests can cover in-place mutation APIs and organize test files recursively under the tests directory.

## What Changes

- Discover tests from any `.py` file under `<tests_dir>` recursively instead of requiring a root `tests.py`.
- Reject test-like non-Python files under `<tests_dir>` as discovery errors.
- Treat an empty recursive discovery result as a discovery error.
- Support mutation-style tests where an entrypoint call appears as a statement or assignment and is immediately followed by one or more assertions.
- Require each mutation-style assertion to reference a variable passed to the mutation call or directly assigned from its result.
- Reject mutation patterns that fall outside the explicit mutation-style constraints.
- Update test IDs to use forward-slash relative paths from `<tests_dir>`, followed by source line and same-line suffixes when needed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Update test discovery source, mutation-style test recognition, discovery error conditions, and test ID formatting.

## Impact

- Affects CLI `generate` and `test` discovery behavior for all supported target languages.
- Affects parser/discovery code that walks test files, validates unsupported constructs, groups mutation-style call/assert sequences, and assigns test IDs.
- Affects generated tester expectations and repository tests that currently assume root-only `tests.py` IDs.
