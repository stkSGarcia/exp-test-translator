## Why

The current test discovery contract is tied to a single root `tests.py` file and does not define mutation-style tests where the entrypoint mutates an argument in place. The checkpoint makes those common test shapes explicit while keeping discovery deterministic and failure-safe.

## What Changes

- Discover tests from any `.py` file under `<tests_dir>` recursively instead of requiring `<tests_dir>/tests.py`.
- Report a discovery error when no tests are discovered anywhere under `<tests_dir>`.
- Report a discovery error for non-`.py` files with test-like names matching `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}`, while ignoring known generated tester artifacts.
- Add mutation-style test discovery for an entrypoint call used as a standalone statement or assignment, immediately followed by one or more asserts.
- Require every mutation-style assert to contain no entrypoint call and to reference at least one variable passed to the mutation call or directly assigned from it.
- Reject mutation-like patterns outside those constraints as discovery errors.
- Change source-based test IDs to use the forward-slash relative path from `<tests_dir>`, followed by the 1-based source line and any existing `#k` same-line suffix.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expands discovery from a single `tests.py` file to recursive Python files, adds constrained mutation-style tests, strengthens invalid test-like file handling, and generalizes test IDs to include relative paths.

## Impact

- Updates Python test discovery, validation, and source scanning across `<tests_dir>`.
- Updates generated or runtime test metadata as needed to carry relative source paths in test IDs.
- Preserves the existing one-line JSON output and exit-code contract while adding new discovery error cases.
- Existing root `tests.py` test IDs remain compatible, but non-Python test-like files under `<tests_dir>` now cause discovery errors instead of being ignored.
