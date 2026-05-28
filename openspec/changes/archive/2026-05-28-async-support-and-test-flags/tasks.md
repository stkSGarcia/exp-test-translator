## 1. CLI — New flags on `test`

- [x] 1.1 Add `--list-tests` flag to the `test` argparse subparser in `main()`
- [x] 1.2 Add `--run <test_id>` argument to the `test` argparse subparser
- [x] 1.3 Add `--timeout-ms <int>` argument to the `test` argparse subparser
- [x] 1.4 Add `--total-timeout-ms <int>` argument to the `test` argparse subparser

## 2. Orchestrator — `cmd_test` mode dispatch

- [x] 2.1 In `cmd_test`, when `--list-tests` is set: set `_BCG_LIST_TESTS=1` env var and pass it to the subprocess; do NOT open or validate the solution path
- [x] 2.2 In `cmd_test`, when `--run <id>` is set: set `_BCG_RUN_ID=<id>` env var and pass it to the subprocess
- [x] 2.3 In `cmd_test`, when `--timeout-ms` is set: set `_BCG_TIMEOUT_MS=<n>` env var and pass it to the subprocess
- [x] 2.4 In `cmd_test`, when `--total-timeout-ms` is set: wrap `subprocess.run` with `timeout=total_ms/1000`; on `subprocess.TimeoutExpired`, read partial results file (if any) and move all unrecorded IDs to `failed`

## 3. Python emitter — async + flags

- [x] 3.1 Import `asyncio` and `concurrent.futures` in the generated `tester.py` header
- [x] 3.2 In `_load_fn`, after obtaining `fn`, check `asyncio.iscoroutinefunction(fn)` and store the flag; define a `_call_fn(fn, args)` helper that calls `asyncio.run(fn(*args))` for async and `fn(*args)` for sync
- [x] 3.3 In `_run()`, read `_BCG_LIST_TESTS` env var; if set, write all case IDs to results file as passed and return immediately without loading the solution
- [x] 3.4 In `_run()`, read `_BCG_RUN_ID` env var; if set, filter `CASES` to only the matching ID before the test loop; if no case matches, write error result and return
- [x] 3.5 In `_run()`, read `_BCG_TIMEOUT_MS` env var; if set, wrap each `fn(*args)` call via `ThreadPoolExecutor` with `future.result(timeout=ms/1000)`; on `TimeoutError`, append to `failed` and `continue`
- [x] 3.6 Replace direct `fn(*args)` call sites in `_run()` with the new `_call_fn` helper (handles both sync and async)

## 4. JavaScript emitter — async + flags

- [x] 4.1 Wrap the entire test loop in an `async` IIFE (`(async () => { ... })()`); change all entrypoint calls to `await fn(...args)`
- [x] 4.2 Read `_BCG_LIST_TESTS` from `process.env`; if set, write all IDs as passed and exit early
- [x] 4.3 Read `_BCG_RUN_ID` from `process.env`; if set, filter `CASES` to only the matching ID; write error result and exit if no match
- [x] 4.4 Read `_BCG_TIMEOUT_MS` from `process.env`; if set, race each `await fn(...args)` against a `new Promise(resolve => setTimeout(() => resolve('__timeout__'), ms))`; treat `'__timeout__'` sentinel as a failed test

## 5. TypeScript emitter — async + flags

- [x] 5.1 Apply the same async IIFE pattern as the JS emitter in `emit_typescript`
- [x] 5.2 Apply `_BCG_LIST_TESTS`, `_BCG_RUN_ID`, and `_BCG_TIMEOUT_MS` handling identically to the JS emitter

## 6. C++ emitter — async + flags

- [x] 6.1 Add `_BCGIsFuture` type trait (specialisations for `std::future<T>` and `std::shared_future<T>`) to the generated `tester.cpp` header
- [x] 6.2 In the generated test runner, use `_bcg_unwrap()` overloads to call `.get()` on future-typed results before comparison
- [x] 6.3 `--list-tests` handled by orchestrator reading `_BCG_IDS:` comment — no tester change needed
- [x] 6.4 Read `_BCG_RUN_ID` env var; each test block guarded by `if (_run_id == nullptr || std::string(_run_id) == "<id>")`
- [x] 6.5 Each test wrapped in `_bcg_fn_` lambda + `std::async`/`wait_for`; timeout → push to `_failed`

## 7. Rust emitter — async + flags

- [x] 7.1 `_rust_compile_cargo` writes `Cargo.toml` with tokio dep; `_rust_compile` detects `async fn <ep>` and routes to cargo vs rustc
- [x] 7.2 Tester uses `#[cfg(bcg_async)]` + `_rt.block_on(call)` for async; `#[cfg(not(bcg_async))]` direct call for sync; both in `loop{}` for timeout early-exit
- [x] 7.3 `--list-tests` handled by orchestrator reading `_BCG_IDS:` comment — no tester change needed
- [x] 7.4 Read `_BCG_RUN_ID` env var; each block guarded by `if _run_id.as_deref().map_or(true, |id| id == "<tid>")`
- [x] 7.5 `_timeout_ms` read in preamble; `#[cfg(bcg_async)]` blocks use `tokio::time::timeout` with `break` on timeout

## 8. Tests

- [x] 8.1 Add integration test: Python async entrypoint (`async def solve`) passes correctly
- [x] 8.2 Add integration test: JS async entrypoint passes correctly
- [x] 8.3 Add integration test: `--list-tests` outputs all IDs with no solution execution
- [x] 8.4 Add integration test: `--run <id>` executes only the selected test
- [x] 8.5 Add integration test: `--run` with unknown ID returns error
- [x] 8.6 Add integration test: `--timeout-ms` causes a slow test to appear in `failed`
- [x] 8.7 Add integration test: `--total-timeout-ms` causes unrun tests to appear in `failed`
