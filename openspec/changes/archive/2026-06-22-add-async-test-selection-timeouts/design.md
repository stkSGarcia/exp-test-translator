## Context

`babel_code_goat.py` currently discovers tests, reads generated tester metadata, and then executes each discovered `TestCase` through `aggregate_results()`. Each non-loop case is delegated to a target-specific runner: Python and Node run small subprocess harnesses, while C++ and Rust compile a temporary driver and execute the resulting binary. Those runners use fixed subprocess timeouts today and report a timed-out subprocess as a failed case.

The new behavior affects the shared `test` command flow and all target runners. Discovery, test IDs, output JSON shape, and the existing coverage rule remain the contract anchors: after successful discovery, every in-scope test must appear exactly once in `passed` or `failed`.

## Goals / Non-Goals

**Goals:**
- Add `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>` while preserving existing output keys and exit codes.
- Await or otherwise complete async entrypoint results before assertion, mutation, output, or exception checks.
- Make timeout behavior deterministic: timed-out and not-executed in-scope tests are failures after successful discovery.
- Keep the implementation inside the existing single-file CLI and generated temporary harness model.

**Non-Goals:**
- Do not add pytest, unittest, or a general-purpose test runner dependency.
- Do not change generated tester filenames, metadata shape unless needed for backward-compatible options, or existing test ID formats.
- Do not require external async runtimes for Rust or C++; support should use target-standard mechanisms where possible.
- Do not change discovery rules beyond recognizing list/selection/timeout command behavior.

## Decisions

1. Add a small execution-options structure for `test`.
   - Rationale: `command_test()` needs to validate flags once, then pass normalized values into `aggregate_results()` and the target runners without growing positional argument lists indefinitely.
   - Approach: Parse positive millisecond integers into seconds or deadline timestamps, with `None` representing the current default. Reject non-positive and non-integer values by printing the standard error JSON and returning code 2.
   - Alternative considered: Let each runner parse raw CLI strings. That would duplicate validation and make consistent error output harder.

2. Treat `--list-tests` as metadata validation plus discovery only.
   - Rationale: The checkpoint says discovery success produces `status="pass"` with all IDs in `passed`, and listing should be useful even when the solution cannot be executed.
   - Approach: Preserve language, tester-file, tester-metadata, tolerance, and discovery validation. After discovery succeeds, print `{"status":"pass","passed":[ids...],"failed":[]}` and skip solution loading and runner execution.
   - Alternative considered: Require the solution file to exist for listing. That adds work unrelated to discovery and weakens the flag as an inspection tool.

3. Filter selected tests before execution.
   - Rationale: `--run <id>` must ensure only the selected ID appears in output, while total timeout accounting should only apply to the selected scope.
   - Approach: After discovery, locate the requested ID. If absent, return the standard error JSON. If present, pass a one-case list to aggregation. Reject `--list-tests` plus `--run` as a command error.
   - Alternative considered: Execute everything but hide unselected results. That would violate the selection contract and waste time.

4. Move timeout accounting into aggregation and runner calls.
   - Rationale: The current fixed subprocess timeout is target-local and cannot mark not-yet-executed tests failed when the whole run times out.
   - Approach: `aggregate_results()` computes the in-scope case list, tracks a monotonic total deadline, and checks the remaining total budget before each case. The effective per-case subprocess timeout is the smaller of `--timeout-ms` and remaining total time when both are set. If the total deadline is exhausted, append all remaining in-scope test IDs to `failed` and stop.
   - Alternative considered: Wrap the entire CLI process in one global timeout. That cannot produce coverage-rule-compliant JSON for tests skipped by timeout.

5. Await async target results inside target harnesses.
   - Rationale: Assertion evaluation must see the completed value or completed exception, not a coroutine, promise, future, or pending async handle.
   - Approach:
     - Python: detect awaitables with `inspect.isawaitable()` and run them with `asyncio.run()` when the harness is not already inside an event loop. Apply the subprocess timeout as the outer guard.
     - JavaScript/TypeScript: keep the Node harness async and ensure direct calls, mutation calls, and exception paths use the existing promise-aware capture helper consistently.
     - C++: generate driver helpers that unwrap supported `std::future<T>` results with `get()` after waiting within the effective timeout.
     - Rust: generate a small std-only future completion helper for supported future results and rely on the outer subprocess timeout for runaway futures.
   - Alternative considered: Add target runtime dependencies such as Tokio or Boost. That would complicate single-file solution compilation and toolchain assumptions.

## Risks / Trade-offs

- Rust and C++ async support may be limited to target-standard future shapes the generated driver can identify → Cover the supported shapes in regression tests and document unsupported compile-time shapes as ordinary target execution failures.
- Subprocess timeout granularity can vary slightly by platform → Treat timeout tests as behavior tests with practical margins rather than exact millisecond assertions.
- `--list-tests` skipping solution validation may surprise callers who expect every `test` invocation to load the solution → The flag is explicitly discovery-oriented and still validates the tester file plus metadata.
- Total timeout may elapse after a case completes but before result aggregation observes it → Check the monotonic deadline before starting every case and after timeout exceptions so remaining cases are reported as failed.
