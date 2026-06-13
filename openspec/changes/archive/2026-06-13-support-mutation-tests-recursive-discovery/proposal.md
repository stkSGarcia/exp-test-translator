## Why

The current discovery contract only accepts tests from a root `tests.py` file and assumes each discovered test can be traced through direct assertion-style entrypoint calls. The checkpoint expands the harness to handle common in-place mutation tests while also letting projects organize test files recursively under the configured tests directory.

## What Changes

- Discover tests from any Python file under `<tests_dir>` recursively instead of requiring `<tests_dir>/tests.py`.
- Treat non-Python files with test-like names as discovery errors so skipped or misnamed tests are surfaced explicitly.
- Report a discovery error when recursive discovery finds no valid tests under `<tests_dir>`.
- Add mutation-style test discovery for entrypoint calls used as statements or assignments immediately followed by one or more assertions.
- Require each mutation-style assertion to reference at least one variable passed to the mutation call or directly assigned from it.
- Reject mutation patterns that fall outside the supported statement/assignment plus adjacent assertion constraints.
- Update test IDs to use the Python file path relative to `<tests_dir>` with forward slashes, followed by the source line and any same-line suffix.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expands test discovery to recursive Python files, adds explicit test-like non-Python file errors, updates test ID path formatting, and supports constrained mutation-style tests.

## Impact

- Updates Python AST discovery and validation for recursive file traversal and mutation-style test grouping.
- Updates generated tester metadata or runner payloads as needed to preserve relative source paths in test IDs.
- Updates JSON result expectations because IDs are no longer always rooted at `tests.py`.
- Adds regression coverage for recursive discovery, non-Python test-like files, no-test errors, supported mutation patterns, and unsupported mutation misuse.
