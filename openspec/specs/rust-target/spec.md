# Spec: rust-target

## Purpose

The Rust emitter produces a `tester.rs` file that is concatenated with a solution file and compiled via `rustc --edition 2021` to report test results.

## Requirements

### Requirement: Rust tester encodes all supported value types except deque
The Rust emitter SHALL produce valid Rust code encoding every value type supported by the IR except `deque`: `None` (as `Option<T>` with `None`/`Some(v)`), `bool`, `int` (as `i64`), `float`/`Decimal` (as `f64`), `str` (as `String`), `list` (as `Vec<T>`), `tuple` (as `Vec<T>` or tuple syntax), `dict` (as `BTreeMap<K, V>`), `set`/`frozenset` (as `BTreeSet<T>`), `Counter` (as `BTreeMap<K, i64>`), `defaultdict` (as `BTreeMap<K, V>`).

#### Scenario: None encoded as Option None
- **WHEN** a test case argument or expected value is Python `None`
- **THEN** the generated `tester.rs` represents it as `None` with the appropriate `Option<T>` type

#### Scenario: Integer encoded as i64
- **WHEN** a test case argument or expected value is a Python `int`
- **THEN** the generated `tester.rs` uses `i64` to represent it

#### Scenario: Float and Decimal encoded as f64
- **WHEN** a test case argument or expected value is a Python `float` or `Decimal`
- **THEN** the generated `tester.rs` uses `f64` to represent it (with possible precision loss for Decimal)

#### Scenario: List encoded as Vec
- **WHEN** a test case argument or expected value is a Python `list`
- **THEN** the generated `tester.rs` uses `vec![...]` to represent it

#### Scenario: Dict encoded as BTreeMap
- **WHEN** a test case argument or expected value is a Python `dict`
- **THEN** the generated `tester.rs` uses `BTreeMap` with keys and values recursively encoded

#### Scenario: Set and frozenset encoded as BTreeSet
- **WHEN** a test case argument or expected value is a Python `set` or `frozenset`
- **THEN** the generated `tester.rs` uses `BTreeSet<T>` with elements recursively encoded

### Requirement: Rust tester skips deque test cases
Test cases whose args or expected value contain a `deque` value SHALL be emitted as failing test cases with a skip message, not silently omitted. This preserves the coverage invariant (all test IDs accounted for in `passed` or `failed`).

#### Scenario: Deque test case appears in failed
- **WHEN** a test case has an argument or expected value containing a Python `deque`
- **THEN** the Rust tester reports that test ID in `failed` with a message indicating deque is not supported

#### Scenario: Non-deque test cases unaffected
- **WHEN** test cases contain no deque values
- **THEN** the Rust tester runs them normally and reports results in `passed` or `failed` based on outcome

### Requirement: Rust tester compiles with rustc edition 2021
The generated `tester.rs` SHALL compile without errors when combined with a valid solution file. The combination is achieved at test time by concatenating solution source and tester source into a temporary file, then compiling with `rustc --edition 2021`.

#### Scenario: Clean compilation
- **WHEN** solution.rs and tester.rs are concatenated and compiled via `rustc --edition 2021 runner.rs -o bin`
- **THEN** the compiler exits `0` with no errors

### Requirement: Rust tester writes results to _BCG_RESULTS_FILE
The compiled Rust binary SHALL read the `_BCG_RESULTS_FILE` environment variable and write the JSON results object (`{"passed": [...], "failed": [...]}`) to that file before exiting.

#### Scenario: Results file written
- **WHEN** the compiled binary is run with `_BCG_RESULTS_FILE=/tmp/results.json` in the environment
- **THEN** `/tmp/results.json` contains a valid JSON object with `passed` and `failed` arrays

### Requirement: Rust tester supports exception testing via catch_unwind
The Rust tester SHALL use `std::panic::catch_unwind` to test for expected panics. For `kind="raises"` test cases, the tester SHALL call `catch_unwind` around the entrypoint call and report passed if a panic occurred, failed otherwise.

#### Scenario: Raises test passes on panic
- **WHEN** the solution function panics and the test case has `kind="raises"`
- **THEN** the test case is reported as passed

#### Scenario: Raises test fails when no panic occurs
- **WHEN** the solution function returns normally and the test case has `kind="raises"`
- **THEN** the test case is reported as failed

### Requirement: Rust tester supports tolerance-based float comparison
The Rust tester SHALL apply `_BCG_TOL` (from env) as a global absolute tolerance for `f64` comparisons, and per-test-case `tol_abs`/`tol_rel` overrides as defined in the IR. Per-test overrides take precedence over the global tolerance.

#### Scenario: Global tolerance applied
- **WHEN** `_BCG_TOL=0.01` is set and the solution returns an `f64` within 0.01 of expected
- **THEN** the test case is reported as passed

#### Scenario: Exact equality when no tolerance set
- **WHEN** no `_BCG_TOL` is set and the solution returns an `f64` that differs from expected
- **THEN** the test case is reported as failed

### Requirement: Rust tester uses owned String keys for HashMap lookups
When the emitted Rust code performs map lookups with string keys, it SHALL use `String::from("key")` (owned `String`) rather than `&str` slices, to ensure compatibility with `HashMap<String, V>`.

#### Scenario: String key lookup compiles and works
- **WHEN** the solution returns a `HashMap<String, V>` and a test case checks a key
- **THEN** the emitted lookup uses an owned `String` key and the comparison succeeds
