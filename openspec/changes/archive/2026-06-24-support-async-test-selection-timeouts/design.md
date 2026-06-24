## Context

The harness discovers Python-authored tests, serializes the discovered model into generated testers, and runs target-language solutions through the `test` command. The current command already preserves strict JSON output, generated-tester workflow boundaries, stale-discovery validation, and cross-target result accounting for Python, JavaScript, TypeScript, C++, and Rust.

Checkpoint 7 adds two related concerns. First, target entrypoints may use async/await-style semantics and must be driven to completion before assertions or output expectations are evaluated. Second, `test` needs selection and timeout controls without losing deterministic result reporting.

## Goals / Non-Goals

**Goals:**

- Support async entrypoint completion in every target language where the selected runtime exposes asynchronous return values or futures.
- Add list-only discovery reporting through `test --list-tests`.
- Add single-test execution through `test --run <test_id>`.
- Add per-test and total-run timeout controls that produce normal failing result JSON when discovery succeeded.
- Preserve strict stdout, exit-code, generated-tester, stale-validation, and coverage semantics for existing flows.

**Non-Goals:**

- Supporting arbitrary async test functions in Python test source.
- Adding new target languages or managing external async runtimes beyond the existing language toolchains.
- Changing generated test IDs, JSON output keys, or existing `generate` command behavior.
- Reporting timeout details in the public JSON shape.

## Decisions

1. Treat async completion as part of entrypoint invocation.

   Each generated tester should wrap the configured entrypoint call in a target-specific completion helper and pass the resolved value or raised error into the existing assertion machinery. Python should detect awaitables and run them with an event loop. JavaScript and TypeScript should `await` promise-like values. C++ should unwrap supported future-like return values before assertion evaluation. Rust should run supported future return values to completion through a small generated executor or a standard-library-compatible polling strategy when practical.

   Alternative considered: require users to expose synchronous wrappers. That would keep testers simpler but fail the checkpoint requirement and make async solutions second-class.

2. Keep list and selection in the CLI result layer.

   `--list-tests` should run discovery and generated-tester validation, then return `{"status":"pass","passed":[...],"failed":[]}` without invoking the solution. `--run <test_id>` should filter execution to the matching discovered ID after discovery and stale validation. An unknown selected ID should be a usage/precondition error because the requested test cannot be run.

   Alternative considered: have generated testers implement listing themselves. That duplicates discovery-state behavior across languages and risks making list output dependent on target runtime availability.

3. Enforce timeouts around execution boundaries and normalize them into failure results.

   `--timeout-ms` should bound an individual selected or all-test invocation. `--total-timeout-ms` should bound the full run after discovery and validation. Once discovery succeeds, a timeout should result in `status="fail"` with timed-out IDs and any not-yet-executed discovered IDs in `failed` according to the coverage rule. If both timeout flags are present, the earliest deadline wins.

   Alternative considered: treat timeout as a harness error. That would conflict with the coverage rule, which requires discovered but unexecuted tests to be listed in `failed`.

4. Preserve deterministic result ordering.

   Listing, selected execution, timeout failure filling, and normal execution should preserve discovered ID order. `--run` is the only mode that narrows result coverage to a single selected ID; all-test execution remains responsible for every discovered ID.

## Risks / Trade-offs

- Cross-target async primitives differ → Keep the public contract at the result level and implement the smallest target-specific completion helper in each generated tester.
- C++ and Rust async support may require stricter assumptions than Python or JavaScript → Cover supported future shapes explicitly and fail unsupported async return shapes as failed tests once discovery succeeds.
- Process-level timeout handling can leave child processes running → Prefer subprocess timeouts and cleanup in the CLI runner where compiled/interpreted testers are launched.
- `--run` conflicts with the existing all-discovered coverage wording → Modify the result coverage requirement so selected runs report exactly the selected discovered ID while normal runs still cover every discovered ID.
