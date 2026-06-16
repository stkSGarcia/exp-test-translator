## Why

The `test` command currently defines discovery, execution coverage, and JSON output, but it does not specify how async entrypoints complete, how users select a subset of discovered tests, or how timeouts are reported. This change makes those behaviors explicit so every target language reports deterministic results for async tests, filtered runs, and timed-out execution.

## Related Work

### Related Changes

- `add-loop-as-test-support`: clarified discovery coverage by requiring every discovered test ID to appear exactly once in `passed` or `failed`; this change extends that coverage rule to timeout and selection cases.
- `support-mutation-directory-discovery`: broadened discovery beyond direct assertion-style entrypoint calls; this change complements that work by preserving discovery semantics while adding execution controls.
- `support-rich-test-comparisons`: expanded accepted translated test expressions; this change complements those richer test cases by ensuring async results and timeout failures are handled consistently.

### Related Specs

- `babel-code-goat-cli/add-loop-as-test-support`: defines loop-based parameterization and coverage outcomes; this change reuses the coverage outcome rule for timed-out and not-executed tests.
- `babel-code-goat-cli/support-mutation-directory-discovery`: extends discovery layouts and mutation-style tests; this change keeps filtered execution layered on top of successful discovery.
- `babel-code-goat-cli/support-single-call-traceability`: defines test discovery source, allowed constructs, and single-entrypoint traceability; this change preserves those discovery constraints while specifying async completion and execution flags.

## What Changes

- Require generated testers and `test` execution to await async or promise-like entrypoint results to completion in `python`, `javascript`, and `typescript`.
- Add `test` flags:
  - `--list-tests`
  - `--run <test_id>`
  - `--timeout-ms <int>`
  - `--total-timeout-ms <int>`
- Define `--list-tests` output as successful discovery with `status="pass"`, all discovered IDs in `passed`, and `failed=[]`.
- Define `--run <test_id>` output so only the selected test ID appears in `passed` or `failed`.
- Require timed-out or not-executed tests after successful discovery to appear in `failed`.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: add async execution completion, test listing and selection flags, and per-test/total timeout reporting behavior for the existing `test` command contract.

## Impact

- CLI argument parsing for `test`.
- Test discovery and execution orchestration for `python`, `javascript`, and `typescript`.
- Generated tester files and runtime wrappers where they invoke the configured entrypoint.
- JSON result construction, status mapping, and exit-code behavior for list, filtered, timeout, and not-executed cases.
