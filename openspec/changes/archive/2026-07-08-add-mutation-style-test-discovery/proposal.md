## Why

Python test discovery needs to accept common in-place mutation test patterns without making entrypoint traceability ambiguous. Checkpoint 5 also requires discovery to work across arbitrary Python files under the tests directory, with deterministic IDs that remain stable as tests move into nested files.

## What Changes

- Add mutation-style test discovery for statement and assignment entrypoint calls followed immediately by one or more asserts.
- Require every assert in a mutation-style test to reference at least one variable passed to, or directly assigned from, the mutation entrypoint call.
- Reject files that use mutation-style patterns outside those constraints as discovery errors.
- Discover tests recursively in any `.py` file under the configured tests directory instead of requiring a root `tests.py`.
- Treat non-Python files with test-like names as discovery errors.
- Report a discovery error when recursive discovery finds no tests.
- Generate test IDs from the tests-directory-relative path, a forward-slash separator, the source line number, and a `#k` suffix for multiple tests on one line.

## Capabilities

### New Capabilities
- `python-test-discovery`: Python test discovery, validation, and stable test identity across supported source layouts.

### Modified Capabilities

## Related Work

### Related Changes
- `support-loop-construct-tests`: Introduced loop-based parameterized test recognition so compact Python test sources can describe multiple cases. This change complements that work by adding constrained mutation-style recognition and recursive file discovery.
- `add-babel-code-goat`: Established the translation engine and predictable generate-then-test workflow that discovery feeds. This change strengthens the front-end discovery contract before runner generation.
- `support-single-call-test-traceability`: Broadened accepted Python assertion shapes while preserving entrypoint traceability. This change extends the same traceability principle to mutation-style calls whose observable result appears through mutated variables.
- `support-rich-python-test-comparisons`: Expanded supported comparison and exception assertions. This change focuses on where asserts may come from and how they are grouped, not on new comparison operators.

### Related Specs
- `babel-code-goat-cli/support-loop-construct-tests`: Defines allowed Python test constructs and parameterized loop behavior. This change reuses its discovery-error posture for unsupported constructs while adding recursive discovery and mutation-style grouping.

## Impact

- Affects Python test discovery, validation diagnostics, and test ID generation.
- Affects runner generation inputs wherever discovered test IDs and grouped assertion cases are consumed.
- No new external dependencies are expected.
