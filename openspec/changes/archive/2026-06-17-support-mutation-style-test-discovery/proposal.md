## Why

The current discovery contract focuses on assertions that call the entrypoint directly from `tests.py`, but common in-place mutation tests call the entrypoint as a statement and assert against mutated inputs afterward. The checkpoint also requires discovery to cover any Python test file under the tests directory, so the contract must move beyond a required root `tests.py`.

## Related Work

### Related Changes

- `add-loop-as-test-support`: added loop statements as discoverable tests and established per-line and per-iteration ID patterns. This change extends that discovery model to mutation-call groups and recursive file paths.
- `support-single-call-traceability`: tightened each discovered test around exactly one configured entrypoint invocation. This change preserves that traceability by accepting mutation-style assertions only when they can be tied to the immediately preceding entrypoint call.
- `support-rich-test-comparisons`: expanded the assertion and value surface for realistic Python tests. This change complements it by adding another common test shape without changing the value-comparison model.

### Related Specs

- `babel-code-goat-cli/support-single-call-traceability`: defines the single-entrypoint traceability rule for discovered tests. This change adapts that rule for mutation-style statement and assignment calls.
- `babel-code-goat-cli/add-loop-as-test-support`: defines line-based test IDs and loop discovery reporting. This change reuses the ID uniqueness pattern while changing the base path from fixed `tests.py` to a relative file path.
- `babel-code-goat-cli/add-babel-code-goat`: defines the base CLI, discovery errors, and JSON output contract. This change keeps those command and error semantics intact while broadening discovery sources.

## What Changes

- Discover tests recursively from any `.py` file under `<tests_dir>` instead of requiring `<tests_dir>/tests.py`.
- Treat mutation-style groups as tests only when a statement or assignment entrypoint call is immediately followed by one or more assertions, no intervening entrypoint call occurs, and every associated assertion references a variable passed to the mutation call or directly assigned from it.
- Report discovery errors for mutation patterns outside those constraints.
- Report discovery errors for test-like non-Python files under `<tests_dir>`.
- Report discovery errors when recursive scanning finds no tests.
- Format non-loop test IDs as `<relative/path.py>:<line>` with forward slashes and append `#<k>` for multiple tests originating from the same line.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: update test discovery source, allowed mutation-style constructs, discovery error cases, and test ID format.

## Impact

- Affects test discovery, test ID generation, and discovery error handling in the Babel Code Goat CLI.
- Generated tester behavior and `test` JSON output semantics remain unchanged except for the broader discovery inputs and ID paths.
- No new external dependencies are required.
