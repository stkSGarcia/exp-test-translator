## Context

`babel_code_goat.py` owns discovery, generated tester metadata, per-language execution, and JSON result aggregation. The current command path discovers all tests and then executes them through `aggregate_results`; Python and Node cases run one subprocess per case, while C++ and Rust compile a harness for the full case set.

## Related Work

> **`babel-code-goat-cli/support-mutation-style-test-discovery`**: defines recursive discovery and stable test IDs — informs `--list-tests` and `--run` because selection must operate on discovered IDs without changing discovery semantics.

> **`babel-code-goat-cli/support-single-call-traceability`**: defines the single-entrypoint invocation model — informs async handling because awaited completion must wrap the one configured entrypoint call, not add new callable patterns.

> **`babel-code-goat-cli/add-loop-as-test-support`**: defines coverage and execution outcomes — informs timeout aggregation because timed-out and not-executed discovered tests must still be represented exactly once.

## Goals / Non-Goals

**Goals:**
- Add `test` CLI parsing for `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms`.
- Reuse existing discovery and test ID generation for listing and selection.
- Await Python coroutines and JavaScript/TypeScript promises before comparison.
- Apply per-test and total timeout budgets while preserving the existing `status`/`passed`/`failed` JSON shape.
- Keep C++ and Rust behavior compatible with the existing compiled harness approach.

**Non-Goals:**
- No changes to discovery syntax, ID formats, or allowed Python test constructs.
- No new JSON output fields for timeout reasons or diagnostics.
- No requirement to add async language features to C++ or Rust beyond honoring timeout budgets for their compiled harnesses.

## Decisions

1. **Apply selection after successful discovery.** `command_test` should discover all cases first, then handle `--list-tests` or filter by `--run`. This keeps ID calculation identical to normal execution _(see `babel-code-goat-cli/support-mutation-style-test-discovery`)_.

   Alternative considered: parse `--run` as a source location and discover only matching syntax. That would duplicate discovery rules and risk diverging from existing ID semantics.

2. **Represent listing as a normal pass result with discovered IDs in `passed`.** `--list-tests` should avoid solution execution entirely after tester metadata and discovery succeed, then return `{"status":"pass","passed":[...],"failed":[]}`.

   Alternative considered: add a separate `status` or output key for discovery. The existing output contract allows only `status`, `passed`, and `failed`, so listing should stay inside that shape.

3. **Pass timeout budgets through aggregation rather than hiding them in subprocess defaults.** Replace hard-coded subprocess timeouts with explicit values derived from `--timeout-ms` and `--total-timeout-ms`, while retaining reasonable internal defaults only for compiler/tool invocations when no user timeout applies.

   Alternative considered: keep fixed 10-second subprocess limits and treat flags as validation-only. That would not satisfy caller-controlled timeout behavior.

4. **Track not-executed discovered IDs in aggregation.** For interpreted targets, the aggregator can stop starting new tests when total time is exhausted and append the remaining selected IDs to `failed`. For compiled targets, if the compiled harness exceeds the total budget or cannot return partial output, all selected non-loop tests not proven passed should fail. This follows the coverage rule from `babel-code-goat-cli/add-loop-as-test-support`.

   Alternative considered: return `error` for timeout exhaustion. The checkpoint requires timed-out and not-executed tests to appear in `failed`, so successful discovery plus timeout should be a failing test result.

5. **Await async results inside the language-specific runner.** Python runner code should detect awaitables with `inspect.isawaitable` and drive them to completion before matching expectations. Node runner code should continue using async wrapper execution and ensure the entrypoint result is awaited before assertion matching _(see `babel-code-goat-cli/support-single-call-traceability`)_.

   Alternative considered: await in the parent process. The parent process does not own in-language values, stdout/stderr capture, or exception semantics.

## Risks / Trade-offs

- Total timeout precision may vary by platform and subprocess startup cost -> compute deadlines using a monotonic clock and pass remaining time to subprocess calls.
- Compiled target partial results are harder to preserve when the whole harness process times out -> treat unreported selected tests as failed, preserving coverage even when pass/fail detail is incomplete.
- Very small timeout values can fail before a runtime starts -> still report selected discovered IDs as failed because discovery succeeded.
- `--run` for an unknown ID is not specified by the checkpoint -> treat it as an error only if implementation needs a defined branch; otherwise prefer an empty selected set only after confirming desired behavior.

## Migration Plan

1. Add parser flags and validation in `build_parser` / `command_test`.
2. Extend execution helpers to accept timeout budgets and await async values.
3. Update aggregation to support listing, selected case sets, per-test timeouts, and total timeout exhaustion.
4. Add regression tests in `tests/test_babel_code_goat.py` for listing, selected execution, async Python/Node behavior, and timeout failure coverage.

## Open Questions

- Should `--run <test_id>` with an ID absent from discovery return `error`, or should it return `fail` with the requested ID? The checkpoint only defines behavior for selected test IDs that exist.
