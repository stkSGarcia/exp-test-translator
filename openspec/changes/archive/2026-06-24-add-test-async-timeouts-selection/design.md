## Context

`babel_code_goat.py` owns discovery, tester generation, execution orchestration, and output validation for Python, JavaScript, TypeScript, C++, and Rust targets. Generated testers currently contain the discovered-test payload and are invoked by the parent `test` command, which validates one JSON result line. JavaScript and TypeScript generated testers already use an async `main()` and await promise-like return values, but Python, C++, Rust, CLI selection, and timeout behavior are not exposed through the public `test` command.

The requested change extends the CLI contract without changing the discovery language or the JSON result shape. All new behavior should preserve the coverage rule that every in-scope discovered test ID appears exactly once in `passed` or `failed`, except discovery errors, which keep the existing error result.

## Goals / Non-Goals

**Goals:**

- Run async entrypoint results to completion for all supported targets or fail them through timeout semantics.
- Add `test --list-tests` for discovery-only reporting using the standard result JSON.
- Add `test --run <test_id>` for targeted execution and targeted reporting.
- Add per-test and total-run timeouts that report timed-out or skipped in-scope tests as failures.
- Keep the `generate` command, discovered test IDs, and result JSON keys stable.

**Non-Goals:**

- Expanding Python test-source syntax beyond the currently supported constructs.
- Adding new target languages or changing generated tester filenames.
- Adding third-party runtime dependencies for async support.
- Reporting timeout metadata outside the existing `status`, `passed`, and `failed` keys.

## Decisions

1. Keep discovery and test selection in the parent CLI.

   The parent `test` command already validates that the generated tester payload matches fresh discovery. It should derive the in-scope test list before invoking a tester: all discovered tests by default, all discovered tests for `--list-tests`, or the single matching test for `--run`. If `--run` references an unknown ID, return the standard error result. Alternative considered: pass all tests into generated testers and let each tester filter. Keeping filtering in the parent makes `--list-tests`, unknown-ID errors, and coverage accounting consistent across languages.

2. Reuse the existing result schema for listing, selection, and timeout outcomes.

   `--list-tests` should skip solution execution and return `{"status":"pass","passed":[...],"failed":[]}` when discovery succeeds. `--run` should only include the selected ID in either `passed` or `failed`. Timeout outcomes should be normal failures, not error results, because discovery succeeded and the affected tests are part of the in-scope coverage set. Alternative considered: add timeout details to JSON. That would break the existing exact-key output contract.

3. Treat async completion as target-local entrypoint normalization.

   Python should detect awaitable results from entrypoint calls and run them to completion with the standard library event loop. JavaScript and TypeScript should continue awaiting promise-like values. C++ generated testers should normalize supported future-like return values by waiting for the result before comparison. Rust generated testers should poll futures through generated standard-library-only support where practical, while preserving synchronous behavior. Alternative considered: require users to wrap async code in synchronous functions. That avoids harness work but does not satisfy the async/await contract.

4. Enforce timeouts from the parent process boundary and, where needed, inside generated testers.

   The parent `test` command should use subprocess timeouts to bound tester execution for Python, JavaScript, TypeScript, C++, and Rust uniformly. Per-test timeouts require generated testers to run and report one test at a time, or the parent to invoke a tester against one selected payload at a time. Total timeout should stop remaining execution and mark any not-yet-reported in-scope tests as failed. Alternative considered: rely only on generated-language timeout mechanisms. That would duplicate process control and be less reliable for compiled binaries.

## Risks / Trade-offs

- Async support differs by target language -> Keep the contract at the entrypoint-result level and cover representative async functions per language in tests.
- Per-test timeout orchestration can be slower if it invokes testers once per test -> Prefer in-process per-test execution when straightforward, but preserve correctness over batching.
- Process termination can lose partial tester output -> Parent aggregation should own final reporting and mark any unresolved in-scope IDs as failed.
- Rust futures without an external runtime may not progress if they depend on reactor APIs -> Document and test standard-library-compatible async functions; avoid adding dependencies unless a future requirement expands runtime support.
