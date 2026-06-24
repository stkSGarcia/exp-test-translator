## Why

Parameterized tests written as Python loops are a common, compact way to express multiple cases. The current test discovery contract does not treat loop statements as tests, so checkpoint 4 requires loop constructs to be accepted and reported while preserving existing assertion traceability guarantees inside loop bodies.

## What Changes

- Treat `for` and `while` loop statements in `tests.py` as discovered tests in addition to assertions and supported raise expectation blocks.
- Report each loop statement as passing when it executes at least once and failing when it executes zero times or cannot be evaluated.
- Discover and execute supported assertions inside loop bodies for each iteration, while still requiring every assertion to trace to exactly one configured entrypoint invocation.
- Support common Python iteration patterns for parameterization, including direct iteration, `enumerate(...)`, index-based `range(len(...))`, `while` loops, and nested loops.
- Generate loop and per-iteration assertion test IDs from source line numbers, adding iteration indexes for assertions executed from loop bodies.
- Preserve discovery failure behavior for unsupported loop bodies, unsupported loop iterables, and assertions with zero or multiple entrypoint calls.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Test discovery and execution must support loop statements as first-class tests and parameterization containers for traceable assertions.

## Impact

- Affects Python AST discovery, loop evaluation, and assertion normalization in `babel_code_goat.py`.
- Affects generated tester payloads and runners so loop execution status and per-iteration assertion IDs are reported consistently across Python, JavaScript, and TypeScript targets.
- Adds end-to-end coverage for non-empty loops, zero-iteration loops, nested loops, while loops, generated IDs, and traceability rejection inside loop bodies.
