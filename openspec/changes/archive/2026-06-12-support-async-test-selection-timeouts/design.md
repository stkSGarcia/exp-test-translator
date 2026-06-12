## Context

`babel_code_goat.py` currently discovers tests through `discover_tests`, stores stable `TestCase.id` values, and executes each case through `aggregate_results` -> `execute_case` -> a language-specific runner. The `test` command accepts `--tol` only, runs every discovered case in order, and relies on hard-coded subprocess timeouts inside the Python, Node, C++, and Rust runners. Loop tests are resolved from discovery metadata, while all non-loop cases invoke the configured entrypoint inside the target harness.

Checkpoint 7 extends this path in two directions: the target harnesses must complete async entrypoint invocations before evaluating assertions, and the `test` command must expose discovery listing, selected execution, per-test timeout, and total-run timeout controls.

## Goals / Non-Goals

**Goals:**

- Run async entrypoint calls to completion for every supported target before comparison, mutation assertion evaluation, output matching, or exception matching.
- Add `test --list-tests` as a discovery-only mode that returns the discovered IDs in the existing JSON shape.
- Add `test --run <test_id>` as a post-discovery filter that executes only the selected case.
- Add validated `--timeout-ms` and `--total-timeout-ms` controls while preserving the existing pass/fail/error JSON contract.
- Report timed-out and not-executed discovered tests in `failed` after discovery succeeds.

**Non-Goals:**

- Changing test discovery syntax, test ID generation, tester metadata format, or the three-key JSON result shape.
- Adding external async runtimes or package managers for target languages.
- Supporting arbitrary C++ coroutine frameworks, Rust async runtimes, browser APIs, or I/O timers that require project-specific runtime setup.
- Making `--list-tests` bypass language validation, tester metadata validation, or discovery validation.

## Decisions

1. Keep discovery as the single source of test IDs.

   `command_test` should validate language, tolerance, timeout flags, tester presence, tester metadata, and discovery before deciding whether to list, filter, or execute. `--list-tests` returns `{"status":"pass","passed":[...ids...],"failed":[]}` and exits 0 when discovery succeeds.

   Alternative considered: list tests by reading cached metadata from the generated tester file. Generated tester files intentionally contain only metadata today, so caching IDs there would make `test` results stale when source tests change.

2. Apply `--run` after discovery and before aggregation.

   The selected ID should be matched against the discovered `TestCase.id` values. A known ID produces a one-case execution set, so only that ID can appear in `passed` or `failed`. An unknown ID is a test command error because it does not correspond to a discovered test.

   Alternative considered: report an unknown selected ID in `failed`. That would violate the discovered-test coverage rule because the ID was never discovered.

3. Move timeout policy into the aggregation layer.

   Parse `--timeout-ms` and `--total-timeout-ms` as positive integers. Pass a per-case timeout budget from `aggregate_results` into `execute_case` and the language runners. Track a monotonic total deadline in `aggregate_results`; when the deadline is exhausted, mark the current and remaining selected cases as failed without attempting more target execution.

   Alternative considered: leave hard-coded subprocess timeouts inside each runner and only add CLI parsing. That would expose flags that do not actually control the execution path.

4. Normalize async completion inside each target runner before assertion evaluation.

   Python runners should detect awaitable results and drive them with `asyncio.run` before evaluating encoded expressions or mutation assertions. JavaScript and TypeScript should await returned Promises inside the existing async Node wrapper. C++ should unwrap standard future-like results such as `std::future<T>` and `std::shared_future<T>` before comparison. Rust should run returned futures with a small std-only executor helper suitable for target `async fn` results that do not require an external reactor.

   Alternative considered: make the Python parent process special-case async results after each target returns. That cannot work reliably because target-local expression evaluation, mutation state, stdout/stderr capture, and exception handling happen inside the harness.

5. Treat timeout and skipped execution as post-discovery failures.

   Once discovery succeeds, every case selected for execution must appear exactly once in either `passed` or `failed`. A per-case timeout returns `False` for that case. A total timeout marks all not-yet-executed selected cases as failed in discovery order. Discovery, metadata, language, and invalid-flag failures remain `status="error"` with empty arrays.

   Alternative considered: return `status="error"` for execution timeouts. The checkpoint explicitly says timed-out or not-executed tests must appear in `failed`, so timeouts are execution failures rather than command errors after discovery succeeds.

## Risks / Trade-offs

- Target async behavior differs by language -> Keep async completion helpers target-local and cover the idiomatic zero-dependency path for each supported language.
- Total timeout can expire between cases rather than interrupting arbitrary in-process Python logic -> Continue executing non-loop tests through subprocess or target runner boundaries and check the deadline before each case.
- C++ and Rust async support is limited without external runtimes -> Support standard future/future-like completion that can be driven by the generated harness, and document runtime-dependent async code as outside this change.
- Compiled targets may spend much of the per-case budget compiling harnesses -> Include compile and run work in the per-case timeout so callers get a real upper bound for each selected case.
- `--list-tests` still requires an existing tester file -> This preserves the current generate-before-test contract and ensures the entrypoint comes from trusted tester metadata.

## Migration Plan

No migration is required for existing generated tester files. Existing `test` invocations continue to run all discovered tests with the default timeout behavior. New flags are opt-in, and invalid new flag values should fail with the existing command error JSON.

## Open Questions

None for the checkpoint scope.
