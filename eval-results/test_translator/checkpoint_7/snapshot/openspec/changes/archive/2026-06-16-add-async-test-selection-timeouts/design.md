## Context

The CLI currently discovers tests in `babel_code_goat.py`, validates tester metadata in `command_test`, and aggregates execution results through `aggregate_results`. Python, JavaScript, and TypeScript cases run one test per subprocess through `run_python_case` and `run_node_case`; C++ and Rust use suite-level runners. The checkpoint adds discovery-only listing, selected execution, async completion, and explicit timeout reporting to the existing `test` command contract.

## Related Work

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines coverage and execution outcomes, including the rule that each discovered test ID appears once across `passed` and `failed` and unexecuted discovered tests fail. This informs the timeout design because timed-out and skipped-by-total-timeout cases should be normal execution failures rather than command errors _(see `babel-code-goat-cli/add-loop-as-test-support`)_.

> **`babel-code-goat-cli/support-mutation-directory-discovery`**: Keeps discovery independent from execution style and source layout. This informs the selected-run design because `--run` should filter the discovered case list after discovery, not change discovery itself _(see `babel-code-goat-cli/support-mutation-directory-discovery`)_.

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines the single-entrypoint test model and tester metadata flow. This informs async handling because waiting for a coroutine or promise should happen at the entrypoint invocation boundary, before assertion evaluation _(see `babel-code-goat-cli/support-single-call-traceability`)_.

## Goals / Non-Goals

**Goals:**

- Add `test` parser support for `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- Preserve existing discovery semantics, test IDs, output shape, status values, and exit-code mapping.
- Await Python coroutine results and JavaScript/TypeScript promises before evaluating assertions and output expectations.
- Report per-test timeouts, total timeouts, and tests not reached because of a total timeout as `failed`.
- Cover the behavior in `tests/test_babel_code_goat.py` for all supported target execution paths that can run in the local environment.

**Non-Goals:**

- Changing the test ID generation contract.
- Adding new result JSON keys or timeout diagnostics.
- Changing `generate` output format except where runner templates must await async calls.
- Adding new test language targets.

## Decisions

1. Use a small execution options object passed from `command_test` to aggregation.

   `command_test` should parse and validate the four new flags, then pass normalized values into `aggregate_results`. This keeps CLI concerns at the boundary and avoids threading several loose optional arguments through every helper.

   Alternative considered: store execution options in module-level state. That would make tests harder to isolate and would couple subprocess behavior to ambient state.

2. Run discovery before list or selected filtering.

   `--list-tests` should call `discover_tests`, return all discovered IDs in `passed`, and avoid invoking the solution entirely. `--run <test_id>` should also run full discovery, then select the matching case. This preserves the existing discovery contract and ensures unsupported tests still produce the standard `error` result before execution starts.

   Alternative considered: parse the requested ID and discover only the corresponding source line. That would duplicate discovery logic and could diverge from existing loop and duplicate-ID behavior.

3. Treat selected tests as the active execution scope.

   Coverage is evaluated against active cases after `--run` filtering. In a selected run, unrelated discovered tests do not appear in either array. This follows the checkpoint requirement that only the selected test ID appears in `passed` or `failed`.

   Alternative considered: include unselected discovered tests as skipped failures. That conflicts with the explicit selected-run output contract.

4. Centralize timeout classification in aggregation.

   Per-case runners should return a failure-compatible outcome when their subprocess times out. Aggregation should track total elapsed time before each active case and mark the current plus remaining active cases as failed when `--total-timeout-ms` is exhausted. This directly extends the existing coverage rule _(see `babel-code-goat-cli/add-loop-as-test-support`)_.

   Alternative considered: let each language runner implement total-timeout logic. That would make cross-language results inconsistent and would not handle not-started cases cleanly.

5. Await at the entrypoint boundary.

   The Python subprocess runner should detect awaitable return values from the resolved callable and execute them to completion before `_matches`. The Node runner already invokes the callable through an async capture path, so implementation should preserve that path and add regression coverage for JavaScript and TypeScript promises.

   Alternative considered: require users to call event loops or `.then()` inside solutions. That would make async behavior user-managed and violate the harness-level completion requirement.

## Risks / Trade-offs

- Timeout checks can make edge cases timing-sensitive -> Use generous timeout values in regression tests except for deliberate timeout tests.
- Python event-loop handling can fail when a solution manages its own loop -> Prefer `asyncio.run()` only when the returned value is awaitable and no loop is running in the subprocess.
- C++ and Rust suite runners execute multiple cases in one process -> If those targets remain supported, add suite-level timeout handling and mark active cases failed consistently when the suite times out.
- `--run` with a missing ID could be interpreted as failure instead of error -> Treat it as `error` because no selected execution scope can be formed after discovery.

## Migration Plan

1. Add parser flags and validation while preserving existing `test` calls.
2. Implement listing and selected-run filtering before changing async behavior.
3. Add async awaiting and timeout enforcement for Python and Node-based targets.
4. Audit native suite targets and either thread timeout options through them or explicitly preserve their current unsupported behavior behind tests.
5. Run the full test suite and targeted CLI smoke tests.

## Open Questions

- The active spec names `python`, `javascript`, and `typescript`, while the implementation currently includes `cpp` and `rust` paths. Implementation should confirm whether checkpoint 7's “all target languages” includes those native targets and update the spec if the supported language contract is expanded.
