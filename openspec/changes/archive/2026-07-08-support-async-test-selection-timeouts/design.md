## Context

The harness is implemented primarily in `babel_code_goat.py`, with CLI parsing in `build_parser`, command behavior in `command_test`, generated runner sources in `python_tester_source`, `javascript_tester_source`, `cpp_tester_source`, and `rust_tester_source`, and regression coverage in `tests/test_babel_code_goat.py`. Current `test` execution validates the generated tester payload against freshly discovered tests, runs the target tester, parses one JSON result line, and returns that result.

Checkpoint 7 adds execution-control behavior rather than a new discovery grammar: async invocations must complete, users can list or select tests by discovered ID, and timeout outcomes must preserve the existing result coverage rule.

## Related Work

**`babel-code-goat-cli/support-rich-python-test-comparisons`**: Defines the richer CLI and assertion/result behavior for realistic tests - informs keeping comparison and exception evaluation inside the generated runners because rich Python assertions remain the source contract.

**`compiled-targets/add-cpp-rust-targets`**: Adds C++ and Rust target selection to the same generate/test workflow - informs placing timeout enforcement in the host `test` command where possible because compiled runners are launched through `subprocess` rather than interpreted in-process.

**`python-test-discovery/add-mutation-style-test-discovery`**: Defines recursive discovery and path-based IDs - informs using `discover_tests` output as the single source for `--list-tests`, `--run`, and not-executed timeout failures because selection needs stable discovered IDs.

**`babel-code-goat-cli/support-loop-construct-tests`**: Extends allowed constructs and parameterized test IDs - informs filtering by already-assigned IDs after discovery because loop-expanded and parameterized IDs must stay identical across list, selected run, and full run modes.

**`babel-code-goat-cli/add-babel-code-goat`**: Establishes the root CLI, generated tester workflow, JSON result shape, and coverage accounting - informs preserving `{"status","passed","failed"}` as the only result contract because callers already depend on it.

## Goals / Non-Goals

**Goals:**
- Add `test` CLI flags `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Use current discovery and payload validation before list, selection, or execution.
- Ensure async entrypoint results are awaited before assertions wherever the target runtime supports async values.
- Report timed-out and not-executed in-scope tests in `failed`.

**Non-Goals:**
- No new Python test discovery syntax beyond the current checkpoint 7 async use cases.
- No change to the JSON output keys or discovery failure contract.
- No attempt to make C++ or Rust language-level async frameworks universal; compiled targets should honor process timeout accounting and any supported synchronous/async-compatible entrypoint form.

## Decisions

1. Use discovery as the canonical ID source for list and selection.

`command_test` should continue extracting the generated payload and re-running `discover_tests`. For `--list-tests`, return `make_result("pass", [ids], [])` after validation and skip target execution. For `--run`, filter both the discovered JSON list and the payload tests to the selected ID before execution; an unknown ID should produce `RESULT_ERROR` because it is an invalid execution request against the generated tester contract. This follows the path-based ID requirements and loop expansion behavior. _(see `python-test-discovery/add-mutation-style-test-discovery`, `babel-code-goat-cli/support-loop-construct-tests`)_

Alternative considered: make generated testers implement their own discovery listing. That would duplicate discovery semantics per language and risk divergent IDs.

2. Pass execution controls through environment variables or generated-runner arguments while preserving one JSON line.

The Python and JavaScript/TypeScript generated testers already evaluate individual tests and can accept a filtered payload or read timeout settings from environment. The host `command_test` should own selection filtering before launching testers, while per-test timeout values can be passed via environment so runner source signatures stay compact. _(see `babel-code-goat-cli/add-babel-code-goat`)_

Alternative considered: regenerate testers for each selected run. That would mutate files during `test`, which conflicts with the existing generate-then-test workflow.

3. Enforce total timeout in the host process wrapper.

`command_test` already invokes target runners through `subprocess.run`; `--total-timeout-ms` should map to the subprocess timeout for Python, JavaScript/TypeScript, and compiled executable runs. If the process timeout fires, the host can synthesize a fail result by combining any known completed IDs only when safely parseable, otherwise marking all in-scope discovered IDs as failed. This preserves coverage accounting even when a target process is killed. _(see `compiled-targets/add-cpp-rust-targets`, `babel-code-goat-cli/add-babel-code-goat`)_

Alternative considered: implement only in generated runners. That would not protect compile steps or target runtimes that hang before the runner can report.

4. Await async values at the runner boundary.

JavaScript/TypeScript already awaits promise-like returned values. Python should detect awaitable entrypoint results and drive them to completion with `asyncio.run` or an equivalent event-loop helper before evaluating assertions. Compiled targets should preserve current synchronous behavior unless their generated harness can represent a supported async-compatible entrypoint. _(see `babel-code-goat-cli/support-rich-python-test-comparisons`, `compiled-targets/add-cpp-rust-targets`)_

Alternative considered: require tests to call async helpers themselves. That would violate the checkpoint requirement that the harness run async/await entrypoint semantics to completion.

## Risks / Trade-offs

- Timeout accounting may lose partial results if the whole target process is killed before output is parseable -> mark all in-scope tests not confidently known as passed in `failed`.
- Python event loop handling can conflict with a solution that manages its own running loop -> isolate test execution in the generated tester subprocess and use a small awaitable helper around each invocation.
- Per-test timeouts are straightforward in Python and JavaScript but less granular for compiled runners -> enforce at least total/process timeout for compiled targets and add per-test support where generated code can check elapsed time around each test.
- `--run` filtering changes result coverage from all discovered tests to the selected in-scope test -> keep the spec explicit that only the selected ID may appear.

## Migration Plan

1. Add CLI arguments and validation in `build_parser` and `command_test`.
2. Add list and selection tests in `tests/test_babel_code_goat.py` before changing runner behavior.
3. Update Python and JavaScript/TypeScript runner execution for async and per-test timeout behavior.
4. Update compiled execution wrappers for total timeout accounting and any feasible generated-runner per-test timeout checks.
5. Add timeout and async regression tests across supported target groups, using skips for unavailable compilers as existing tests do.

## Open Questions

- Should an unknown `--run <test_id>` return `status="error"` or `status="fail"` with that requested ID in `failed`? The current design chooses `error` because the ID is not discoverable.
- Should per-test timeout include compile time for compiled targets? The current design treats compile time as outside per-test execution and covered by total timeout only.
