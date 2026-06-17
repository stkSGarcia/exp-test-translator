## MODIFIED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. (adapts babel-code-goat-cli/add-babel-code-goat/cli-commands-and-language-validation)

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
The system SHALL write the expected tester file in `<tests_dir>` when `generate` succeeds. The expected tester filename MUST be `tester.py` for `python`, `tester.js` for `javascript`, `tester.ts` for `typescript`, `tester.cpp` for `cpp`, and `tester.rs` for `rust`. (adapts babel-code-goat-cli/add-babel-code-goat/tester-file-generation)

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
The system MUST NOT create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs` when `generate` fails for any reason. (adapts babel-code-goat-cli/add-babel-code-goat/generation-failure-preserves-tester-files)

#### Scenario: Generate fails before tester exists
- **WHEN** `generate` fails and the expected tester file is absent
- **THEN** the expected tester file remains absent

#### Scenario: Generate fails when tester already exists
- **WHEN** `generate` fails and the expected tester file already exists
- **THEN** the existing tester file content remains unchanged

### Requirement: Test Requires Existing Tester
The system MUST require the expected tester file to already exist before running `test`. The `test` command MUST NOT create or modify the tester file. (adapts babel-code-goat-cli/add-babel-code-goat/test-requires-existing-tester)

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
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported hashable key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as arguments and expected values, including nested containers where the Python type allows nesting. C++ and Rust generated testers MUST preserve the same value and comparison semantics supported by Python tests, including `None`/null values at any supported nesting position. Equality and inequality MUST use deep structural or container-semantic comparison for nested containers. Numeric comparison MUST apply the effective tolerance to floats and `decimal.Decimal` values where tolerance is applicable. Rust targets MAY skip tests that explicitly require Python `collections.deque` behavior when those tests are guarded by a Rust-specific skip marker. (adapts babel-code-goat-cli/add-babel-code-goat/allowed-values-and-equality)

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
- **WHEN** a discovered equality assertion compares `deque([1, 2, 3])` with `deque([1, 2, 3])`
- **THEN** the comparison passes because the ordered contents match

#### Scenario: Defaultdict values compare by mapping contents
- **WHEN** a discovered equality assertion compares `defaultdict(int, {"a": 1})` with `defaultdict(list, {"a": 1})`
- **THEN** the comparison passes because the mapping contents match

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered equality assertion compares `Decimal("1.001")` with `Decimal("1.000")` while the effective tolerance is `0.01`
- **THEN** the comparison passes

#### Scenario: Null values are preserved in nested compiled-target values
- **WHEN** a C++ or Rust target test uses `None` as an argument, expected value, dictionary value, sequence element, or nested container member
- **THEN** the generated tester represents that value as target-language null/optional state and compares it structurally

#### Scenario: Rust deque-specific tests are skipped when guarded
- **WHEN** a test requires `collections.deque` behavior and is explicitly guarded to skip for Rust
- **THEN** the Rust target does not execute that deque-specific test

#### Scenario: Unsupported literal value
- **WHEN** a test argument or expected value uses a value outside the allowed set or uses an unhashable dictionary key
- **THEN** discovery fails

### Requirement: Solution Callable Resolution
The code under test MUST be in the same language as the generated tester. The system SHALL call the inferred entrypoint when it is available as a callable named by the entrypoint, as a method with that name on a class constructible with no arguments, or as a static method with that name. For C++ and Rust targets, generated testers MUST compile or link against a single solution file containing the solution function or supported callable construct for that target. (adapts babel-code-goat-cli/add-babel-code-goat/solution-callable-resolution)

#### Scenario: Callable function is used
- **WHEN** the solution defines a callable named by the inferred entrypoint
- **THEN** the system invokes that callable for each discovered test

#### Scenario: No-argument class method is used
- **WHEN** the solution defines a class constructible with no arguments and that class has a callable method named by the inferred entrypoint
- **THEN** the system constructs the class and invokes the method for each discovered test

#### Scenario: Static method is used
- **WHEN** the solution defines a class with a callable static method named by the inferred entrypoint
- **THEN** the system invokes the static method for each discovered test

#### Scenario: Compiled solution file is used
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` or `--lang rust` is invoked and the expected tester exists
- **THEN** the system compiles or runs the generated tester with the single-file solution at `<solution_path>` and reports results using the standard test JSON contract

## ADDED Requirements

> Extends: babel-code-goat-cli/add-babel-code-goat

### Requirement: Compiled Target Type and Operation Mapping
The system SHALL generate C++17-or-newer and Rust-1.70-or-newer tester code that maps supported Python test values and primitive operations to target-language equivalents. C++ testers MUST support `std::optional<T>` and `std::nullopt` for null values, `std::vector<T>`, `std::map<K,V>`, `std::unordered_map<K,V>`, `std::set<T>`, `long double` numeric values for decimal/high-precision comparisons, `std::string` operations for supported string assertions, `std::sort()` for supported sorting assertions, and `std::runtime_error`/`std::exception` handling for exception-style tests. Rust testers MUST support `Option<T>` with `Some(value)` and `None`, `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, `HashSet<T>`, owned `String` lookup keys for mutable map access, `f64` numeric values for decimal assertions, supported `String` methods, `.sort()`/`.sort_by()` for sorting assertions, and `catch_unwind` with `panic!` for exception-style tests.

#### Scenario: C++ null and container mappings are emitted
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` processes tests containing nested containers and `None` values
- **THEN** the generated `tester.cpp` uses C++ optional and standard-library container representations that preserve the source test values

#### Scenario: Rust null and container mappings are emitted
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` processes tests containing nested containers and `None` values
- **THEN** the generated `tester.rs` uses Rust option and standard-library collection representations that preserve the source test values

#### Scenario: Rust owned string map lookup is supported
- **WHEN** a Rust target test mutates or looks up a `HashMap<String, V>` entry using an owned string key such as `String::from("items")`
- **THEN** the generated tester accepts the lookup and executes the assertion instead of failing due to key type mismatch

#### Scenario: Exception-style tests run on compiled targets
- **WHEN** a discovered raise-any or typed expectation block targets C++ or Rust
- **THEN** the generated tester evaluates the exception-style expectation using the target-language exception or panic-catching mechanism
