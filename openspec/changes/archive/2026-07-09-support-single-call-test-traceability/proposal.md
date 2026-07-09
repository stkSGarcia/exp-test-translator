## Why

The test harness currently recognizes a narrow set of assertion shapes where the entrypoint call appears in a fixed position. Checkpoint 3 requires broader Python expression support while preserving traceability to exactly one invocation of the configured entrypoint per discovered test.

## What Changes

- Discover supported assertions by locating exactly one configured entrypoint invocation within each test expression instead of requiring it only as the left-hand side of equality-style assertions.
- Reject tests that contain multiple configured entrypoint invocations, no configured entrypoint invocation, or calls to unsupported non-primitive functions.
- Allow primitive Python operations around the entrypoint result, including numeric, string, and container operations needed for comparisons and membership checks.
- Continue to allow tolerance helper calls such as `math.isclose(...)` and `abs(...)` when they wrap exactly one entrypoint invocation according to existing tolerance semantics.
- Preserve existing discovery failure behavior for unsupported constructs and invalid assertion forms.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Test discovery and execution must support primitive expression operations around a single traceable entrypoint call while rejecting unsupported multi-call assertions.

## Impact

- Affects Python AST discovery and assertion normalization in `babel_code_goat.py`.
- Affects generated tester payloads if normalized expected values or derived assertion kinds need to represent primitive expression expectations.
- Adds discovery and end-to-end tests for single-call traceability, multi-call rejection, primitive operations, membership checks, and tolerance helper compatibility.
