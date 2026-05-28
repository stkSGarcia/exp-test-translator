# Spec: async-entrypoint

## Purpose

Defines how language-specific testers detect and handle async/future-returning entrypoints, ensuring both async and sync entrypoints are invoked correctly across all supported languages.

## Requirements

### Requirement: Python tester awaits async entrypoints
When the solution's entrypoint is an `async` function, the Python tester SHALL detect this at runtime using `asyncio.iscoroutinefunction` and invoke it via `asyncio.run(fn(*args))` instead of `fn(*args)`. Sync entrypoints SHALL be called directly, with no change in behavior.

#### Scenario: Async Python entrypoint returns correct value
- **WHEN** the solution defines `async def solve(x): return x + 1` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

#### Scenario: Sync Python entrypoint unaffected
- **WHEN** the solution defines `def solve(x): return x + 1` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed (no change from current behavior)

#### Scenario: Async Python entrypoint raising an exception
- **WHEN** the solution defines `async def solve(): raise ValueError("bad")` and the test uses a raises assertion
- **THEN** the test is reported as passed

### Requirement: JavaScript tester awaits Promise-returning entrypoints
The JavaScript tester SHALL run its test loop inside an `async` IIFE and `await` every entrypoint call. For sync functions the `await` is a no-op; for functions returning a `Promise` the resolution value is used as the result.

#### Scenario: Async JavaScript entrypoint returns correct value
- **WHEN** the solution exports `async function solve(x) { return x + 1; }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

#### Scenario: Sync JavaScript entrypoint unaffected
- **WHEN** the solution exports `function solve(x) { return x + 1; }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

### Requirement: TypeScript tester awaits Promise-returning entrypoints
The TypeScript tester SHALL apply the same `await`-in-async-IIFE pattern as the JavaScript tester. Both sync and `Promise`-returning entrypoints SHALL be handled correctly.

#### Scenario: Async TypeScript entrypoint returns correct value
- **WHEN** the solution exports `async function solve(x: number): Promise<number> { return x + 1; }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

#### Scenario: Sync TypeScript entrypoint unaffected
- **WHEN** the solution exports `function solve(x: number): number { return x + 1; }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

### Requirement: C++ tester unwraps std::future return values
The C++ tester SHALL detect at compile time, via a type trait `_BCGIsFuture`, whether the entrypoint returns a `std::future` or `std::shared_future`. If so, the tester SHALL call `.get()` on the returned future to obtain the actual result before comparison. For non-future return types the call is unchanged.

#### Scenario: C++ entrypoint returning std::future passes correct value
- **WHEN** the solution defines `std::future<int> solve(int x) { return std::async(std::launch::async, [x]{ return x + 1; }); }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

#### Scenario: C++ entrypoint returning plain value unaffected
- **WHEN** the solution defines `int solve(int x) { return x + 1; }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

### Requirement: Rust tester awaits async entrypoints
The Rust tester SHALL use a single-threaded `tokio` runtime (or equivalent `async` executor) to block on every entrypoint call. For `async fn` entrypoints the executor awaits the future; for sync entrypoints the call is wrapped in `async { fn(args) }` which resolves immediately.

#### Scenario: Rust async entrypoint returns correct value
- **WHEN** the solution defines `async fn solve(x: i64) -> i64 { x + 1 }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed

#### Scenario: Rust sync entrypoint unaffected
- **WHEN** the solution defines `fn solve(x: i64) -> i64 { x + 1 }` and the test asserts `solve(1) == 2`
- **THEN** the test is reported as passed
