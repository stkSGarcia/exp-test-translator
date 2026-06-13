## Context

`babel_code_goat.py` discovers Python-authored tests into stable `TestCase` IDs, then executes each case through a target-specific harness and aggregates `passed`/`failed` arrays. The current flow runs all discovered cases synchronously with fixed internal subprocess timeouts, while JavaScript/TypeScript already has an async runner shape and Python, C++, and Rust need explicit result normalization for awaitable/future return values. The new CLI flags should reuse the existing discovery and result format rather than adding a second reporting path.

## Goals / Non-Goals

**Goals:**

- Add `test` flags for listing discovered IDs, running one selected ID, per-test timeouts, and total command timeouts.
- Preserve the existing JSON shape and exit-code mapping for pass, fail, and error outcomes.
- Run async entrypoint results to completion before assertions and output expectations are evaluated.
- Treat timed-out and not-executed tests as failed tests when discovery succeeded.

**Non-Goals:**

- Do not add new target languages or replace the generated harness architecture.
- Do not add external async runtimes or package dependencies.
- Do not change test ID generation or discovery rules beyond filtering by an already discovered ID.

## Decisions

1. Extend `command_test` parsing and aggregate execution options.

   `--list-tests` should stop after tester metadata validation and discovery, returning `{"status":"pass","passed":[...ids...],"failed":[]}` with exit code 0. `--run <test_id>` should filter the discovered list before execution; an unknown ID should be an error because it indicates an invalid caller request rather than a failing solution. Timeout flags should parse as positive integer milliseconds before execution begins.

   Alternative considered: make `--run` of an unknown ID return `fail`. Rejected because no discovered test failed; the command could not fulfill the requested selection.

2. Centralize timeout accounting in aggregation.

   Pass timeout configuration into `aggregate_results`, track elapsed monotonic time before each case, and pass the remaining budget into target runners. When the total timeout is exhausted, append the current and remaining unexecuted case IDs to `failed`. Per-test timeout failures should return `False` from the target runner so they naturally land in `failed`.

   Alternative considered: rely only on subprocess-level timeouts. Rejected because total timeout needs to mark not-yet-executed tests as failed and stop scheduling more work.

3. Normalize async target results inside each harness.

   Python should detect `inspect.isawaitable(result)` and run it through an event loop before assertion evaluation. JavaScript and TypeScript should keep awaiting callable results. C++ should unwrap future-like results with `.get()` when the entrypoint returns a future, while preserving direct values. Rust should support `Future` results with a small standard-library `block_on` helper, avoiding third-party runtime dependencies.

   Alternative considered: treat async as JavaScript/TypeScript-only. Rejected because the requirement applies to all supported target languages.

## Risks / Trade-offs

- Async primitives differ by language and ecosystem -> implement the smallest standard-library-compatible normalization per target and cover each target with smoke tests.
- Total timeout can expire between test cases rather than inside the exact assertion boundary -> compute remaining time before launching each case and pass that budget to subprocess calls so long-running cases are interrupted promptly.
- C++ and Rust async support without external runtimes cannot cover every custom executor pattern -> document and test standard/future-like behavior while preserving synchronous compatibility.
