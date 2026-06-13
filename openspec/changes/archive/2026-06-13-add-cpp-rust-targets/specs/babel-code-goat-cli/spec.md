## MODIFIED Requirements

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages.

#### Scenario: Generate accepts a supported language
- **WHEN** `generate` is invoked with an existing tests directory, a valid entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs`

#### Scenario: Test rejects an unsupported language
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Tester File Generation
The system SHALL write the expected tester file in `<tests_dir>` when `generate` succeeds. The expected tester filename MUST be `tester.py` for `python`, `tester.js` for `javascript`, `tester.ts` for `typescript`, `tester.cpp` for `cpp`, and `tester.rs` for `rust`.

#### Scenario: Generate writes a Python tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` succeeds
- **THEN** `<tests_dir>/tester.py` exists and the command exits with code 0

#### Scenario: Generate writes a JavaScript tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang javascript` succeeds
- **THEN** `<tests_dir>/tester.js` exists and the command exits with code 0

#### Scenario: Generate writes a TypeScript tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang typescript` succeeds
- **THEN** `<tests_dir>/tester.ts` exists and the command exits with code 0

#### Scenario: Generate writes a C++ tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` succeeds
- **THEN** `<tests_dir>/tester.cpp` exists and the command exits with code 0

#### Scenario: Generate writes a Rust tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` succeeds
- **THEN** `<tests_dir>/tester.rs` exists and the command exits with code 0

### Requirement: Generation Failure Preserves Tester Files
The system MUST NOT create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs` when `generate` fails for any reason.

#### Scenario: Generate fails before tester exists
- **WHEN** `generate` fails and the expected tester file is absent
- **THEN** the expected tester file remains absent

#### Scenario: Generate fails when tester already exists
- **WHEN** `generate` fails and the expected tester file already exists
- **THEN** the existing tester file content remains unchanged

### Requirement: Test Requires Existing Tester
The system MUST require the expected tester file to already exist before running `test`. The `test` command MUST NOT create or modify the tester file.

#### Scenario: Python tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang python` is invoked and `<tests_dir>/tester.py` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: JavaScript tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang javascript` is invoked and `<tests_dir>/tester.js` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: TypeScript tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang typescript` is invoked and `<tests_dir>/tester.ts` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: C++ tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` is invoked and `<tests_dir>/tester.cpp` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Rust tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang rust` is invoked and `<tests_dir>/tester.rs` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Existing tester is preserved during test
- **WHEN** `test` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Allowed Values and Equality
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported hashable key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as arguments and expected values, including nested containers where the Python type allows nesting. Equality and inequality MUST use deep structural or container-semantic comparison for nested containers. Numeric comparison MUST apply the effective tolerance to floats and `decimal.Decimal` values where tolerance is applicable. For C++ and Rust targets, generated tester code MUST preserve `None`/null values anywhere they appear in supported nested values instead of converting them to strings or sentinel scalars.

#### Scenario: Nested values are compared structurally
- **WHEN** a discovered equality assertion compares nested lists, tuples, dictionaries, sets, frozensets, counters, deques, default dictionaries, or decimals
- **THEN** the test result is based on the nested values' structural or container-semantic equality rather than object identity or string formatting

#### Scenario: Null values are preserved in compiled targets
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` or `--lang rust` runs a discovered assertion whose arguments or expected values contain `None` at the top level or inside a nested container
- **THEN** the generated compiled-target tester preserves the value as target-language nullability and compares it structurally

#### Scenario: Dictionary keys use supported key types
- **WHEN** a discovered assertion uses a dictionary with supported non-string keys such as integers, booleans, tuples, frozensets, or decimals
- **THEN** discovery succeeds and comparison preserves the key values rather than converting them to strings

#### Scenario: Sets and frozensets compare by membership
- **WHEN** a discovered equality assertion compares `set([2, 1])` with `{1, 2}` or `frozenset([2, 1])` with `frozenset([1, 2])`
- **THEN** the comparison passes regardless of member order

#### Scenario: Counter values compare by counts
- **WHEN** a discovered equality assertion compares `Counter({"a": 2, "b": 1})` with `Counter(["a", "a", "b"])`
- **THEN** the comparison passes because the element counts match

#### Scenario: Deque values compare by ordered contents
- **WHEN** a discovered equality assertion compares `deque([1, 2, 3])` with `deque([1, 2, 3])`
- **THEN** the comparison passes because the ordered contents match

#### Scenario: Defaultdict values compare by mapping contents
- **WHEN** a discovered equality assertion compares `defaultdict(int, {"a": 1})` with `defaultdict(list, {"a": 1})`
- **THEN** the comparison passes because the mapping contents match

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered equality assertion compares `Decimal("1.001")` with `Decimal("1.000")` while the effective tolerance is `0.01`
- **THEN** the comparison passes

#### Scenario: Unsupported literal value
- **WHEN** a test argument or expected value uses a value outside the allowed set or uses an unhashable dictionary key
- **THEN** discovery fails

### Requirement: Solution Callable Resolution
The code under test MUST be in the same language as the generated tester. For Python, JavaScript, and TypeScript targets, the system SHALL call the inferred entrypoint when it is available as a callable named by the entrypoint, as a method with that name on a class constructible with no arguments, or as a static method with that name. For C++ and Rust targets, the solution MUST be a single file containing a callable function named by the inferred entrypoint.

#### Scenario: Callable function is used
- **WHEN** the solution defines a callable named by the inferred entrypoint
- **THEN** the system invokes that callable for each discovered test

#### Scenario: No-argument class method is used
- **WHEN** a Python, JavaScript, or TypeScript solution defines a class constructible with no arguments and that class has a callable method named by the inferred entrypoint
- **THEN** the system constructs the class and invokes the method for each discovered test

#### Scenario: Static method is used
- **WHEN** a Python, JavaScript, or TypeScript solution defines a class with a callable static method named by the inferred entrypoint
- **THEN** the system invokes the static method for each discovered test

#### Scenario: C++ solution function is used
- **WHEN** a C++ solution file defines a function named by the inferred entrypoint
- **THEN** the generated C++ tester compiles the single-file solution and invokes that function for each discovered test

#### Scenario: Rust solution function is used
- **WHEN** a Rust solution file defines a function named by the inferred entrypoint
- **THEN** the generated Rust tester compiles the single-file solution and invokes that function for each discovered test

## ADDED Requirements

### Requirement: Compiled Target Behavior Parity
The system SHALL execute supported discovered tests for `cpp` and `rust` targets with the same pass/fail/error semantics as Python, JavaScript, and TypeScript targets. This includes direct assertions, primitive operations, loop-expanded assertions, mutation-style tests, raw stdout/stderr expectations, default and per-assert numeric tolerances, raise-any expectations, and typed exception-style expectations where the target can express the expected exception category.

#### Scenario: C++ target runs supported discovered tests
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs after a matching `tester.cpp` has been generated
- **THEN** every supported discovered test is executed against the C++ solution and reported through the standard `status`, `passed`, and `failed` JSON output

#### Scenario: Rust target runs supported discovered tests
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs after a matching `tester.rs` has been generated
- **THEN** every supported discovered test is executed against the Rust solution and reported through the standard `status`, `passed`, and `failed` JSON output

#### Scenario: Compiled target command errors before execution
- **WHEN** a compiled target cannot be prepared before any discovered test can execute because the generated tester metadata is invalid, the required compiler is unavailable, or the solution cannot be compiled
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: C++ Target Runtime Mapping
The system SHALL generate C++17-or-later tester code for `--lang cpp`. Generated C++ testers MUST use idiomatic target representations for supported Python-test values and operations, including `std::optional<T>`/`std::nullopt` for nullable values, `std::vector<T>` for sequence values, standard map types for mapping values, `std::set<T>` or equivalent membership containers for set values, `std::string` for strings, `long double` for decimal-like numeric values, `std::sort` for supported sorting operations, and C++ exception handling for exception-style tests.

#### Scenario: C++ nullable values use optional semantics
- **WHEN** a generated C++ tester passes or compares a supported value containing Python `None`
- **THEN** the generated C++ code represents the nullable position with `std::optional<T>` and `std::nullopt` or an equivalent generated nullable wrapper

#### Scenario: C++ collections use structural comparison
- **WHEN** a generated C++ tester compares supported nested sequences, maps, sets, counters, default dictionaries, or deques
- **THEN** the comparison uses the target representations' contents rather than pointer identity or serialized strings

#### Scenario: C++ string and sorting operations are supported
- **WHEN** a discovered test expression uses supported string methods or `sorted(...)` around the single entrypoint result
- **THEN** the generated C++ tester evaluates the equivalent operation using standard C++ string APIs or `std::sort`

#### Scenario: C++ exception expectation is supported
- **WHEN** a discovered raise-any or typed exception expectation is executed for `--lang cpp`
- **THEN** the generated C++ tester treats matching `std::exception`-style failures as passing expectation cases and reports non-matching outcomes as failed tests

### Requirement: Rust Target Runtime Mapping
The system SHALL generate Rust 1.70-or-later tester code for `--lang rust`. Generated Rust testers MUST use idiomatic target representations for supported Python-test values and operations, including `Option<T>` with `Some(value)` and `None` for nullable values, `Vec<T>` for sequence values, `HashMap<K,V>` or `BTreeMap<K,V>` for mapping values, `HashSet<T>` or equivalent membership containers for set values, `String` for strings, `f64` for decimal-like numeric values, Rust sorting methods for supported sorting operations, and `catch_unwind`/`panic!` for exception-style tests.

#### Scenario: Rust nullable values use option semantics
- **WHEN** a generated Rust tester passes or compares a supported value containing Python `None`
- **THEN** the generated Rust code represents the nullable position with `Option<T>` using `Some(value)` and `None` or an equivalent generated nullable wrapper

#### Scenario: Rust collections use structural comparison
- **WHEN** a generated Rust tester compares supported nested sequences, maps, sets, counters, or default dictionaries
- **THEN** the comparison uses the target representations' contents rather than pointer identity or serialized strings

#### Scenario: Rust string-keyed map lookups compile
- **WHEN** a generated Rust tester evaluates a supported expression that reads or updates a `HashMap<String, V>` value using a Python string key
- **THEN** the generated Rust code performs a valid owned or borrowed `String` key lookup and compiles successfully

#### Scenario: Rust string and sorting operations are supported
- **WHEN** a discovered test expression uses supported string methods or `sorted(...)` around the single entrypoint result
- **THEN** the generated Rust tester evaluates the equivalent operation using Rust `String`/`str` APIs or Rust sorting methods

#### Scenario: Rust exception expectation is supported
- **WHEN** a discovered raise-any or typed exception expectation is executed for `--lang rust`
- **THEN** the generated Rust tester treats matching `panic!` outcomes captured with `catch_unwind` as passing expectation cases and reports non-matching outcomes as failed tests

### Requirement: Rust Deque Limitation
The Rust target MUST NOT claim support for Python `collections.deque` operations until a first-class `VecDeque` mapping is specified. Repository regression tests that require deque-specific behavior MUST skip Rust-target execution rather than expecting generated Rust testers to translate those deque operations.

#### Scenario: Rust deque-specific regression is skipped
- **WHEN** repository regression coverage exercises Python `collections.deque` behavior that depends on deque-specific operations
- **THEN** the Rust-target variant of that regression is marked skipped instead of requiring generated Rust code to translate the operation
