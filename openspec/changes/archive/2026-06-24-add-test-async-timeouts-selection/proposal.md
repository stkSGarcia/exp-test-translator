## Why

The `test` command currently assumes synchronous entrypoint execution and always runs the full discovered test set. Async solutions, targeted reruns, discovery-only listing, and bounded execution are needed so the harness can run modern submissions reliably and report complete coverage under timeout conditions.

## What Changes

- Add async/await completion support for entrypoint invocation in every supported target language.
- Extend `test` with `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Make `--list-tests` report successful discovery as `status="pass"` with all discovered IDs in `passed` and an empty `failed` list.
- Make `--run <test_id>` limit execution and reporting to only the selected discovered test ID.
- Make timed-out and not-executed discovered tests appear in `failed` so coverage remains complete.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: The public `test` command contract gains async completion semantics, test listing, single-test selection, per-test timeouts, and total-run timeouts.

## Impact

- Affects `babel_code_goat.py` CLI argument parsing, generated tester templates for Python, JavaScript, TypeScript, C++, and Rust, runner orchestration, and result aggregation.
- Requires pytest coverage for async execution, list-only discovery, selected test runs, per-test timeout reporting, total timeout reporting, and coverage-rule interactions.
