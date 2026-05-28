## Context

`babel_code_goat.py` generates tester files for five languages and runs them as subprocesses. The orchestrator (`cmd_test`) communicates with the tester subprocess via a shared JSON results file (`_BCG_RESULTS_FILE`) and environment variables (`_BCG_TOL`).

Currently the generated testers call the solution entrypoint synchronously. If the entrypoint is `async` (a Python coroutine function or a JS/TS function returning a `Promise`), the call returns immediately with an unawaited coroutine/Promise and every test fails. C++ and Rust don't have a standard async story, so for those languages the concern is timeout/future unwrapping only.

The `test` command accepts no selection or timeout flags, so callers cannot scope a run to one test or bound its wall-clock time.

## Goals / Non-Goals

**Goals:**
- Python testers: detect `asyncio.iscoroutinefunction` at runtime and dispatch via `asyncio.run`.
- JS/TS testers: `await` every entrypoint call (no-op for sync; correct for `Promise`-returning functions).
- C++ testers: detect `std::future`-returning entrypoints via `if constexpr` + `_BCGIsFuture` trait and call `.get()` with an optional timeout.
- Rust testers: use `tokio::runtime::Builder::new_current_thread` to block-on any `async fn`; detect via a `_bcg_is_async!` macro that tries to call `.await` in a closure.
- Add four flags to `test`: `--list-tests`, `--run <id>`, `--timeout-ms <ms>`, `--total-timeout-ms <ms>`.
- Timed-out and not-yet-executed tests appear in `failed` per coverage rule.

**Non-Goals:**
- Parallelising test execution within a single tester run.
- Detecting `async` at `generate` time (all detection is runtime/compile-time inside the generated tester).
- Supporting `async for` / async generators as entrypoints.
- Adding new target languages.

## Decisions

### D1 — Async detection per language

| Language | Mechanism | Rationale |
|---|---|---|
| Python | `asyncio.iscoroutinefunction(fn)` at runtime | Reliable stdlib API; no overhead for sync fns |
| JavaScript | `await result` unconditionally in an `async` IIFE | `await nonPromise` is a no-op; zero added complexity |
| TypeScript | Same as JS | Same rationale |
| C++ | `if constexpr (is_future_v<decltype(fn(args...))>)` | Compile-time detection via type trait; `.get()` only called when return type is a `std::future`/`std::shared_future` |
| Rust | `tokio::runtime::Handle::block_on` wrapped in a macro that detects `impl Future` at compile time | `block_on` works for both sync (wraps in `async {}`) and async fns via `async { fn(args).await }` |

**Alternative considered**: generate two tester variants (sync/async) and select at `generate` time. Rejected — requires re-running `generate` if the solution changes from sync to async, breaking the generate-once/test-many model.

### D2 — Passing mode to the tester subprocess

New environment variables follow the existing `_BCG_*` convention:

| Env var | Set when |
|---|---|
| `_BCG_LIST_TESTS=1` | `--list-tests` passed |
| `_BCG_RUN_ID=<id>` | `--run <id>` passed |
| `_BCG_TIMEOUT_MS=<n>` | `--timeout-ms <n>` passed |
| `_BCG_TOTAL_TIMEOUT_MS=<n>` | `--total-timeout-ms <n>` passed |

**Alternative considered**: pass flags as subprocess argv. Rejected — compiled targets (C++, Rust) receive args differently and extending argv complicates the harness; environment variables are already the established channel.

### D3 — Per-test timeout implementation

Each language implements timeout differently inside the tester:
- **Python**: `concurrent.futures.ThreadPoolExecutor` + `future.result(timeout=ms/1000)`. Cancels on timeout.
- **JS/TS**: `Promise.race([callPromise, timeout Promise])` — resolves to a sentinel on timeout.
- **C++**: `std::async(std::launch::async, fn, args...)` then `.wait_for(std::chrono::milliseconds(ms))`.
- **Rust**: `tokio::time::timeout(Duration::from_millis(ms), async { fn(args).await })`.

### D4 — `--list-tests` does not run the solution

The tester subprocess skips loading/executing the solution when `_BCG_LIST_TESTS=1`. It writes all case IDs to `_BCG_RESULTS_FILE` as `{"passed": [<all ids>], "failed": []}`. The solution path argument is still required by the CLI for consistency but is not opened.

### D5 — `--run <id>` filters at the tester level

The tester subprocess skips all cases whose `id != _BCG_RUN_ID`. The orchestrator sees only the one test in `passed` or `failed`. IDs not matching the filter are silently omitted (not moved to `failed`).

## Risks / Trade-offs

- **C++ async detection via `if constexpr`**: requires C++17. Existing C++ emission already targets C++17 (`g++ -std=c++17`); no compiler flag change needed. If a solution returns a raw `std::future` but the test expects a concrete value, the type-trait path handles it. If the solution uses coroutines (`co_return`), that is out of scope.
- **Rust `tokio` dependency**: the Rust emitter's generated tester now imports `tokio`. If `tokio` is not in the cargo workspace, the tester won't compile. Mitigation: the generated tester emits a `[dependencies]` block comment and the `cmd_test` Rust path must link a minimal tokio. This may require a temporary `Cargo.toml`-per-run approach. **This is a known complexity; if tokio is unavailable the test will error, not silently pass.**
- **Thread-based per-test timeout in Python**: threads cannot be forcibly killed, so a slow test continues consuming resources after timeout; only the result is discarded. For typical coding-challenge solutions this is acceptable.
- **Total timeout accuracy**: `_BCG_TOTAL_TIMEOUT_MS` is tracked per-test from the tester side. If a single test hangs indefinitely, the tester process itself must be killed by the orchestrator. The orchestrator sets `subprocess.run(..., timeout=total_ms/1000)` and moves all unrecorded IDs to `failed` when the process is killed.

## Migration Plan

No stored state. Changes are backward-compatible: all new flags are optional, and async detection is transparent to sync solutions. No migration steps required.

## Open Questions

- Should C++ async via `std::experimental::coroutine` / C++20 `co_await` be supported? Currently out of scope but the trait-based approach could be extended.
- Should Rust compilation use a persistent workspace (to avoid re-downloading `tokio` on every run) or a temp workspace per invocation?
