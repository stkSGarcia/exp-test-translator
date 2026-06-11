## Context

`babel_code_goat.py` currently discovers tests, runs every discovered case in source order, and aggregates boolean case results into the existing JSON contract. Individual target runners own their subprocess execution and use fixed timeout values. JavaScript/TypeScript already await the entrypoint result inside the Node harness, while Python, C++, and Rust currently treat entrypoint calls as synchronous values.

The checkpoint requires two cross-cutting improvements: async entrypoints must be driven to completion for every supported target, and the `test` command must expose discovery, selection, and timeout controls without changing the established `status`/`passed`/`failed` output shape.

## Goals / Non-Goals

**Goals:**

- Add `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Preserve the existing JSON output keys and exit-code mapping.
- Ensure timeout and selection behavior is applied uniformly across Python, JavaScript, TypeScript, C++, and Rust targets.
- Await or otherwise resolve target-specific async entrypoint results before evaluating assertions.

**Non-Goals:**

- Change discovery IDs or the supported Python test-source grammar beyond async-compatible execution semantics.
- Add external runtime dependencies such as `pytest`, `tokio`, or a JavaScript package manager.
- Parallelize case execution.
- Change `generate` command behavior except where generated harness metadata already supports `test`.

## Decisions

1. Add a shared execution options object for `test` orchestration.

   `command_test` should parse and validate selection and timeout flags into a small options value passed into aggregation and case runners. This keeps output assembly, timeout accounting, and target runner invocation in one path instead of scattering flag checks across CLI parsing and target helpers.

   Alternative considered: handle each flag directly in `command_test`. That is simpler initially, but it would duplicate timeout and failure accounting once target-specific runners need custom timeout values.

2. Treat discovery as the first step for listing and selection.

   `--list-tests` should require the same tester metadata and discovery success as normal `test`, then print `{"status":"pass","passed":[...],"failed":[]}` without executing solution code. `--run <test_id>` should filter the discovered case list after discovery; if the ID is absent, the command should return the standard error JSON and exit 2.

   Alternative considered: list IDs by reading test files without tester metadata. That would make `test --list-tests` behave differently from `test` and risk reporting IDs for a stale or invalid generated tester.

3. Use monotonic deadline accounting for total timeouts and per-case subprocess timeouts for individual tests.

   `--timeout-ms` should flow into each target runner and replace the current fixed subprocess execution timeout. `--total-timeout-ms` should establish a monotonic deadline after successful discovery. Before each case, aggregation should stop if the total deadline has expired and mark all remaining selected cases as failed. If a case times out, that case is failed; if the total deadline prevents later cases from running, those not-executed IDs are also failed.

   Alternative considered: use OS-level process groups and signal alarms for the whole command. The subprocess boundary already contains target execution, so monotonic accounting is easier to test and keeps platform assumptions small.

4. Normalize async entrypoint results inside each target harness.

   Python should detect awaitable return values and run them to completion with `asyncio.run` or an equivalent fresh event loop inside the isolated subprocess. JavaScript/TypeScript should keep awaiting the callable result, but the timeout value should be configurable. C++ should wrap invocation results so `std::future<T>` and `std::shared_future<T>` are resolved with `.get()` before assertion evaluation. Rust should wrap invocation results through a helper that accepts either plain values or `Future` results and drives futures with a minimal standard-library executor suitable for self-contained solution code.

   Alternative considered: require async solutions to expose synchronous wrappers. That would push target-specific harness responsibility onto users and would not satisfy the checkpoint’s requirement that the harness run async invocations to completion.

## Risks / Trade-offs

- Async Rust futures that depend on an external runtime may not make progress under a minimal executor -> document and test self-contained futures; timeout handling still reports non-completion as failure.
- C++ async detection can become template-heavy -> keep helper overloads narrow for plain values, `std::future<T>`, and `std::shared_future<T>`.
- Timeout behavior can obscure whether a solution is wrong or slow -> keep the JSON schema unchanged as required, but add tests that assert the timed-out or skipped IDs land in `failed`.
- `--list-tests` still requiring generated tester metadata may surprise callers -> this preserves the existing `test` preconditions and avoids reporting IDs for the wrong entrypoint.

## Migration Plan

No data migration is required. Existing `generate` and `test` invocations should continue to work because all new flags are optional. Rollback is limited to removing the new flag parsing and restoring the previous aggregation signature.

## Open Questions

None.
