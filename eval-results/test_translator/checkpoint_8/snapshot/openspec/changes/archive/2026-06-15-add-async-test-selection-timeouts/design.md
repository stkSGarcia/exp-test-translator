## Context

`babel_code_goat.py` owns test discovery, generated tester rendering, language-specific execution, and the `test` command result aggregation. Current execution has fixed internal subprocess timeouts and runs every discovered case; the CLI does not expose discovery listing, selected execution, or configurable timeout budgets.

## Related Work

> **`babel-code-goat-cli/support-mutation-directory-discovery`**: Defines recursive discovery, path-based test IDs, and mutation-style discovery — informs reuse of discovered `TestCase.id` values for `--list-tests` and `--run <test_id>` because this change must report stable IDs without introducing a second ID scheme.
>
> **`babel-code-goat-cli/support-single-call-traceability`**: Defines traceable mapping from discovered tests to entrypoint invocations — informs result filtering and timeout failure accounting because each selected, timed-out, or not-executed test must remain attributable to one test ID.
>
> **`babel-code-goat-cli/support-rich-test-comparisons`**: Adds optional `test` command flags for comparison behavior — informs the parser and validation shape for new `test` flags because selection and timeout controls should extend the same command surface.

## Goals / Non-Goals

**Goals:**

- Support `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Await async entrypoint results before assertion evaluation in every supported target where async values can be produced.
- Preserve result JSON shape with `status`, `passed`, and `failed`.
- Ensure timed-out and not-executed tests are represented in `failed`.

**Non-Goals:**

- Expanding the supported Python test source syntax.
- Introducing parallel test execution.
- Changing generated test ID formats.
- Adding new target languages.

## Decisions

1. Centralize CLI flag parsing and validation in `build_parser` and `command_test`.

   `--list-tests` can return immediately after successful discovery with `{"status":"pass","passed":[...],"failed":[]}`. `--run <test_id>` should filter the discovered `cases` list before execution and return `error` if the ID is not discovered. This follows the existing `--tol` flag pattern _(see `babel-code-goat-cli/support-rich-test-comparisons`)_.

2. Keep selection based on `TestCase.id`.

   The existing discovery model already assigns stable path-based IDs, including loop and duplicate-line suffixes. Reusing `TestCase.id` avoids a separate selector namespace and preserves traceability _(see `babel-code-goat-cli/support-mutation-directory-discovery` and `babel-code-goat-cli/support-single-call-traceability`)_.

3. Pass timeout budgets through aggregation instead of hard-coding them inside each runner.

   Add optional `timeout_ms` and `total_timeout_ms` values to `aggregate_results`, `execute_case`, and language-specific runner functions. Convert milliseconds to subprocess timeout seconds at the boundary. The aggregate loop should track elapsed monotonic time before scheduling each case and mark any remaining scheduled cases as failed when the total budget is exhausted.

4. Treat timeout as a failed test, not an infrastructure error, once discovery and tester metadata succeeded.

   Per-test and total execution timeouts should append the affected test IDs to `failed` and continue result accounting where possible. Metadata errors, invalid language, missing tester, and discovery errors should keep returning the existing `error` result.

5. Add target-specific async completion at the call adapter closest to entrypoint invocation.

   Python should detect awaitable results with `inspect.isawaitable` and drive them with `asyncio.run` before `_matches`. JavaScript and TypeScript already execute through an async Node wrapper; keep awaiting the callable result and ensure timeout comes from the parent subprocess. C++, Rust, and generated suite runners should treat their native runner process completion as the async boundary unless target-specific future/task support is added in generated code.

## Risks / Trade-offs

- Timeout cancellation may leave child processes running if only the parent process times out -> use `subprocess.run(..., timeout=...)`, which kills the direct process, and keep one subprocess per Python/Node case.
- Total timeout can expire between cases -> check the remaining budget before scheduling each case and mark all unscheduled selected cases as failed.
- `--run` with an unknown ID could be confused with a failing test -> return the existing `error` result so callers can distinguish invalid selection from test failure.
- C++ and Rust async patterns are not currently modeled in discovery or generated assertions -> preserve synchronous suite behavior and rely on process completion until async primitives are explicitly supported.

## Migration Plan

1. Add parser options and validation helpers for positive integer millisecond flags.
2. Implement discovery-only listing and selected-case filtering in `command_test`.
3. Thread timeout budgets through aggregation and runner functions.
4. Add Python awaitable handling and keep Node await behavior covered by tests.
5. Add unit tests for list mode, selected run mode, per-test timeout, total timeout not-executed failures, and Python async entrypoints.

## Open Questions

- Should native C++ and Rust generated testers recognize language-specific async primitives in a later change, or is process completion sufficient for this checkpoint?
