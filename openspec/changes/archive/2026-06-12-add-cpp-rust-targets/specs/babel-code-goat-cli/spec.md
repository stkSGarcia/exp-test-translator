## ADDED Requirements

### Requirement: C++ and Rust Target Parity
The system SHALL execute C++ and Rust target tests with the same discovery metadata, test ID, JSON output, value comparison, loop, mutation-style, raw stdout/stderr expectation, numeric tolerance, and exception expectation semantics as Python tests, except that Rust target execution is exempt from Python `collections.deque` behavior. C++ target support MUST use C++17 or later. Rust target support MUST use Rust 1.70 or later. C++ nullable values MUST be represented with `std::optional<T>` and `std::nullopt`. Rust nullable values MUST be represented with `Option<T>`, `Some(value)`, and `None`. C++ high-precision decimal values MUST use `long double`. Rust decimal values MUST use `f64`.

#### Scenario: C++ target supports nullable nested values
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs a discovered test whose arguments or expected values contain `None` nested inside lists, tuples, dictionaries, sets, counters, default dictionaries, or other supported containers
- **THEN** the C++ target preserves those nullable positions using `std::optional<T>` semantics and compares the nested values structurally

#### Scenario: Rust target supports nullable nested values
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs a discovered test whose arguments or expected values contain `None` nested inside lists, tuples, dictionaries, sets, counters, default dictionaries, or other supported non-deque containers
- **THEN** the Rust target preserves those nullable positions using `Option<T>` semantics and compares the nested values structurally

#### Scenario: C++ target supports required collections and primitives
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs discovered tests using supported strings, vectors, maps, unordered maps, sets, sorting, string find/substr/length/empty operations, numeric comparisons, and exception-style expectations
- **THEN** the C++ target executes those tests with C++17+ standard-library constructs and reports pass/fail using the standard JSON result contract

#### Scenario: Rust target supports required collections and primitives
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs discovered tests using supported strings, vectors, hash maps, B-tree maps, hash sets, sorting, string find/split/len/is_empty/to_lowercase/trim operations, numeric comparisons, and exception-style expectations
- **THEN** the Rust target executes those tests with Rust 1.70+ standard-library constructs and reports pass/fail using the standard JSON result contract

#### Scenario: Rust string-key map lookup accepts owned strings
- **WHEN** a Rust target mutation-style test requires a `HashMap<String, V>` lookup or update using an owned `String` key such as `String::from("items")`
- **THEN** the generated Rust harness accepts the owned key and evaluates the mutation assertion instead of failing translation

#### Scenario: Rust deque behavior is skipped
- **WHEN** a discovered test requires Python `collections.deque` behavior and `test` is running with `--lang rust`
- **THEN** the Rust target treats the deque-specific case as outside the Rust target parity surface rather than requiring a `VecDeque` translation

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
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported hashable key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as arguments and expected values, including nested containers where the Python type allows nesting. These value and equality semantics MUST apply to all supported target languages, except that Rust target execution is exempt from Python `collections.deque` behavior. `None` values MUST be preserved anywhere a supported value can appear. Equality and inequality MUST use deep structural or container-semantic comparison for nested containers. Numeric comparison MUST apply the effective tolerance to floats and `decimal.Decimal` values where tolerance is applicable.

#### Scenario: Nested values are compared structurally
- **WHEN** a discovered equality assertion compares nested lists, tuples, dictionaries, sets, frozensets, counters, deques, default dictionaries, or decimals
- **THEN** the test result is based on the nested values' structural or container-semantic equality rather than object identity or string formatting

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
- **WHEN** a discovered equality assertion compares `deque([1, 2, 3])` with `deque([1, 2, 3])` for a non-Rust target
- **THEN** the comparison passes because the ordered contents match

#### Scenario: Defaultdict values compare by mapping contents
- **WHEN** a discovered equality assertion compares `defaultdict(int, {"a": 1})` with `defaultdict(list, {"a": 1})`
- **THEN** the comparison passes because the mapping contents match

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered equality assertion compares `Decimal("1.001")` with `Decimal("1.000")` while the effective tolerance is `0.01`
- **THEN** the comparison passes

#### Scenario: None values are preserved in nested containers
- **WHEN** a discovered equality assertion compares values containing `None` inside nested lists, tuples, dictionaries, sets, counters, deques for non-Rust targets, default dictionaries, or decimals-adjacent structures
- **THEN** the comparison preserves the null positions and passes only when the actual and expected nested structures match

#### Scenario: Unsupported literal value
- **WHEN** a test argument or expected value uses a value outside the allowed set or uses an unhashable dictionary key
- **THEN** discovery fails

### Requirement: Solution Callable Resolution
The code under test MUST be in the same language as the generated tester. The system SHALL call the inferred entrypoint when it is available as a callable named by the entrypoint, as a method with that name on a class constructible with no arguments, or as a static method with that name. C++ and Rust solutions MUST be accepted as single files containing solution functions.

#### Scenario: Callable function is used
- **WHEN** the solution defines a callable named by the inferred entrypoint
- **THEN** the system invokes that callable for each discovered test

#### Scenario: No-argument class method is used
- **WHEN** the solution defines a class constructible with no arguments and that class has a callable method named by the inferred entrypoint
- **THEN** the system constructs the class and invokes the method for each discovered test

#### Scenario: Static method is used
- **WHEN** the solution defines a class with a callable static method named by the inferred entrypoint
- **THEN** the system invokes the static method for each discovered test

#### Scenario: C++ solution function is used
- **WHEN** a single-file C++ solution defines a function named by the inferred entrypoint
- **THEN** the C++ target invokes that function for each discovered test

#### Scenario: Rust solution function is used
- **WHEN** a single-file Rust solution defines a function named by the inferred entrypoint
- **THEN** the Rust target invokes that function for each discovered test
