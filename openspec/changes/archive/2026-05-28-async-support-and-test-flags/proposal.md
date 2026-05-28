## Why

The test harness silently mishandles async solutions — a coroutine or Promise returned by the entrypoint is never awaited, so every test fails incorrectly. Test runners also lack the ability to select a single test or bound execution time, making it impractical to use the harness inside CI pipelines or interactive workflows.

## What Changes

- **Async entrypoint support in all emitters**: generated tester files for Python, JavaScript, TypeScript, C++, and Rust detect and properly await async entrypoints so coroutines/Promises run to completion.
- **`--list-tests` flag on `test`**: outputs `{"status":"pass","passed":[<all IDs>],"failed":[]}` from the pre-generated tester without executing the solution.
- **`--run <test_id>` flag on `test`**: restricts the run to a single test ID; other tests are omitted from output entirely.
- **`--timeout-ms <int>` flag on `test`**: per-test wall-clock timeout; tests that exceed it appear in `failed`.
- **`--total-timeout-ms <int>` flag on `test`**: total-run wall-clock timeout; not-yet-executed tests when the budget expires appear in `failed`.

## Capabilities

### New Capabilities

- `async-entrypoint`: Async/await support in generated testers across all five target languages — Python (`asyncio.run`), JavaScript/TypeScript (`async`/`await` top-level), C++ (no stdlib async; solved via simple future/thread wrapper), Rust (`tokio::test` or `async-std`). The harness transparently detects whether the entrypoint is async and runs it to completion.

### Modified Capabilities

- `test-harness-run`: New CLI flags (`--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`) and timeout coverage rule (timed-out and not-executed tests appear in `failed`).

## Impact

- `babel_code_goat.py` — `cmd_test`, `main` (argparse), all five emitters (`emit_python`, `emit_javascript`, `emit_typescript`, `emit_cpp`, `emit_rust`), and `_SUBPROC`/`_COMPILE` subprocess plumbing.
- Generated tester files for all five languages change structure to support async and to propagate list/run/timeout mode via environment variables.
- No external dependencies added for Python/JS/TS async; C++ and Rust may need conditional compile flags or crate additions (`tokio` for Rust).
