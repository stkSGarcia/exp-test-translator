## Why

The current test discovery contract does not treat Python loops as tests, so common parameterized test patterns cannot report whether the parameter source actually exercised anything. The checkpoint requires loop statements to become first-class tests while keeping assertions inside loop bodies traceable to exactly one entrypoint invocation.

## What Changes

- Discover supported `for` and `while` loop statements in `tests.py` as loop tests.
- Allow supported parameter source assignments needed by loop-based tests, such as literal case lists and index variables.
- Report a loop test as passing when the loop body iterates at least once.
- Report a loop test as failing when the loop iterates zero times or cannot be evaluated.
- Discover assertions inside loop bodies and apply the existing single-entrypoint-call traceability rules to each assertion.
- Generate stable test IDs for loop statements and iteration-indexed IDs for assertions inside loop bodies, including nested loops.
- Preserve the existing JSON output and exit-code contract, with zero-iteration loop failures producing `status: "fail"` and exit code 1.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Expands test discovery, reporting, and test ID requirements to support loop-as-test parameterization constructs.

## Impact

- Updates Python AST discovery and validation for supported `for`, `enumerate`, index-based, `while`, and nested loop constructs.
- Updates supported setup statement handling for loop parameter sources and loop index state.
- Updates generated tester metadata or execution plans to represent loop tests separately from assertions executed inside loop bodies.
- Updates result aggregation so zero-iteration loops fail without reporting unexecuted body assertions.
- Adds regression coverage for loop pass/fail behavior, assertion traceability in loops, nested loops, and iteration-indexed IDs across supported target languages.
