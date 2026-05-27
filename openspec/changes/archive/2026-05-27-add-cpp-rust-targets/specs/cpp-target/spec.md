## ADDED Requirements

### Requirement: C++ tester encodes all supported value types
The C++ emitter SHALL produce valid C++17 code encoding every value type supported by the IR: `None` (as `std::optional` with `std::nullopt`), `bool`, `int` (as `long long`), `float`/`Decimal` (as `long double`), `str` (as `std::string`), `list` (as `std::vector`), `tuple` (as `std::vector` or `std::tuple`), `dict` (as `std::map`), `set`/`frozenset` (as `std::set`), `Counter` (as `std::map<K, long long>`), `deque` (as `std::deque`), and `defaultdict` (as `std::map`).

#### Scenario: None value encoded as nullopt
- **WHEN** a test case argument or expected value is Python `None`
- **THEN** the generated `tester.cpp` represents it as `std::nullopt` with the appropriate `std::optional<T>` wrapper

#### Scenario: Integer encoded as long long
- **WHEN** a test case argument or expected value is a Python `int`
- **THEN** the generated `tester.cpp` uses `long long` to represent it

#### Scenario: Float and Decimal encoded as long double
- **WHEN** a test case argument or expected value is a Python `float` or `Decimal`
- **THEN** the generated `tester.cpp` uses `long double` to represent it

#### Scenario: List encoded as std::vector
- **WHEN** a test case argument or expected value is a Python `list`
- **THEN** the generated `tester.cpp` uses `std::vector<T>` to represent it

#### Scenario: Dict encoded as std::map
- **WHEN** a test case argument or expected value is a Python `dict`
- **THEN** the generated `tester.cpp` uses `std::map<K, V>` with keys and values recursively encoded

#### Scenario: Set and frozenset encoded as std::set
- **WHEN** a test case argument or expected value is a Python `set` or `frozenset`
- **THEN** the generated `tester.cpp` uses `std::set<T>` with elements recursively encoded

#### Scenario: Deque encoded as std::deque
- **WHEN** a test case argument or expected value is a Python `deque`
- **THEN** the generated `tester.cpp` uses `std::deque<T>` with elements recursively encoded

### Requirement: C++ tester compiles with g++ or clang++ in C++17 mode
The generated `tester.cpp` SHALL compile without errors or warnings when combined with a valid solution file using `g++ -std=c++17` or `clang++ -std=c++17`.

#### Scenario: Clean compilation with g++
- **WHEN** `tester.cpp` and a correct `solution.cpp` are compiled via `g++ -std=c++17 tester.cpp solution.cpp -o bin`
- **THEN** the compiler exits `0` with no errors

#### Scenario: Clean compilation with clang++
- **WHEN** `tester.cpp` and a correct `solution.cpp` are compiled via `clang++ -std=c++17 tester.cpp solution.cpp -o bin`
- **THEN** the compiler exits `0` with no errors

### Requirement: C++ tester declares entrypoint as extern function
The generated `tester.cpp` SHALL declare the solution entrypoint as an `extern` C++ function with a signature derived from the test cases, so it can be linked against a separately compiled `solution.cpp`.

#### Scenario: Extern declaration present
- **WHEN** `generate` is run with `--lang cpp --entrypoint solve`
- **THEN** `tester.cpp` contains an `extern` or forward declaration for `solve` matching the expected call signature

### Requirement: C++ tester writes results to _BCG_RESULTS_FILE
The compiled C++ binary SHALL read the `_BCG_RESULTS_FILE` environment variable and write the JSON results object (`{"passed": [...], "failed": [...]}`) to that file before exiting.

#### Scenario: Results file written
- **WHEN** the compiled binary is run with `_BCG_RESULTS_FILE=/tmp/results.json` in the environment
- **THEN** `/tmp/results.json` contains a valid JSON object with `passed` and `failed` arrays

### Requirement: C++ tester supports exception testing
The C++ tester SHALL use `try { ... } catch (const std::exception& e)` to test for expected exceptions. For typed raises (exc_type), the tester SHALL catch the appropriate exception type when possible; for untyped raises it SHALL catch `std::exception`.

#### Scenario: Untyped raises test passes on any exception
- **WHEN** the solution function throws any exception and the test case has `kind="raises"`
- **THEN** the test case is reported as passed

#### Scenario: Untyped raises test fails when no exception thrown
- **WHEN** the solution function returns normally and the test case has `kind="raises"`
- **THEN** the test case is reported as failed

### Requirement: C++ tester supports tolerance-based float comparison
The C++ tester SHALL apply `_BCG_TOL` (from env) as a global absolute tolerance for floating-point comparisons, and per-test-case `tol_abs`/`tol_rel` overrides as defined in the IR. Per-test overrides take precedence over the global tolerance.

#### Scenario: Global tolerance applied to double comparison
- **WHEN** `_BCG_TOL=0.01` is set and the solution returns a `long double` within 0.01 of expected
- **THEN** the test case is reported as passed

#### Scenario: Per-test abs_tol overrides global tolerance
- **WHEN** `_BCG_TOL=0.5` is set but the test case has `tol_abs=0.001` and the result differs by 0.01
- **THEN** the test case is reported as failed (per-test override applies)
