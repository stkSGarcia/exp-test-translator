## Why

Async tests currently have no explicit cross-target completion contract, so a translated harness can report before async/await work has finished or hang indefinitely. The `test` command also needs deterministic discovery, selection, and timeout behavior so checkpoint runs can isolate tests and still report complete coverage on timeout.

## Related Work

### Related Changes

- `add-babel-code-goat`: Established the broad cross-language test-harness generator and runner contract; this change complements it by defining async completion and timeout semantics for that runner.
- `support-single-call-traceability`: Motivated one-to-one mapping between discovered tests and entrypoint invocations; this change extends that traceability to `--run` selection and timeout failure reporting.
- `add-loop-as-test-support`: Extended discovery so parameterized loop patterns can be represented as tests; this change relies on that discovery model when listing or selecting discovered IDs.

### Related Specs

- `babel-code-goat-cli/support-mutation-directory-discovery`: Defines recursive discovery, path-based test IDs, and mutation-style test discovery. This change reuses those discovered IDs for `--list-tests` and `--run <test_id>` behavior.
- `babel-code-goat-cli/support-single-call-traceability`: Defines that discovered tests map cleanly to entrypoint invocations. This change adapts that model so selected, timed-out, and not-executed tests remain attributable.
- `babel-code-goat-cli/support-rich-test-comparisons`: Adds optional `test` command flags for comparison behavior. This change follows the same CLI-extension pattern for selection and timeout flags.

## What Changes

- Add async/await completion semantics for every target-language harness before result evaluation.
- Add `test --list-tests` to return discovered test IDs without executing them.
- Add `test --run <test_id>` to execute and report only the selected discovered test.
- Add per-test `--timeout-ms <int>` and whole-run `--total-timeout-ms <int>` controls.
- Require timed-out and not-executed tests to appear in `failed` so coverage remains explicit.

## Capabilities

### New Capabilities

- `async-test-execution-controls`: Async-aware entrypoint completion plus `test` discovery listing, single-test selection, and timeout result reporting.

### Modified Capabilities

- None.

## Impact

- Affects the `test` CLI surface and result JSON contract.
- Affects target-language harness generation and invocation wrappers for async/await completion.
- Affects timeout handling, selected-test filtering, and coverage failure accounting.
