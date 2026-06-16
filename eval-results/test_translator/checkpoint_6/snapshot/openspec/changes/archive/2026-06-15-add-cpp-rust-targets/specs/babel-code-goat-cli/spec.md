## MODIFIED Requirements

> Extends: babel-code-goat-cli

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. (adapts babel-code-goat-cli/add-babel-code-goat/cli-commands-and-language-validation)

#### Scenario: Generate accepts a supported language
- **GIVEN** an existing tests directory and a valid entrypoint
- **WHEN** `generate` is invoked with `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **GIVEN** an existing tests directory and a valid entrypoint
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs`

#### Scenario: Test rejects an unsupported language
- **GIVEN** a solution path and tests directory
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Tester File Generation
The system SHALL write the expected tester file in `<tests_dir>` when `generate` succeeds. The expected tester filename MUST be `tester.py` for `python`, `tester.js` for `javascript`, `tester.ts` for `typescript`, `tester.cpp` for `cpp`, and `tester.rs` for `rust`.

#### Scenario: Generate writes a C++ tester
- **GIVEN** an existing tests directory containing supported tests
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` succeeds
- **THEN** `<tests_dir>/tester.cpp` exists and the command exits with code 0

#### Scenario: Generate writes a Rust tester
- **GIVEN** an existing tests directory containing supported tests
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` succeeds
- **THEN** `<tests_dir>/tester.rs` exists and the command exits with code 0

### Requirement: Generation Failure Preserves Tester Files
The system MUST NOT create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs` when `generate` fails for any reason.

#### Scenario: Native generate fails before tester exists
- **GIVEN** the selected native tester file is absent
- **WHEN** `generate` fails for `--lang cpp` or `--lang rust`
- **THEN** the expected native tester file remains absent

#### Scenario: Native generate fails when tester already exists
- **GIVEN** the selected native tester file already exists
- **WHEN** `generate` fails for `--lang cpp` or `--lang rust`
- **THEN** the existing native tester file content remains unchanged

### Requirement: Test Requires Existing Tester
The system MUST require the expected tester file to already exist before running `test`. The `test` command MUST NOT create or modify the tester file.

#### Scenario: C++ tester is missing
- **GIVEN** `<tests_dir>/tester.cpp` is missing
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Rust tester is missing
- **GIVEN** `<tests_dir>/tester.rs` is missing
- **WHEN** `test <solution_path> <tests_dir> --lang rust` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Existing native tester is preserved during test
- **GIVEN** the selected C++ or Rust tester file exists
- **WHEN** `test` is invoked for that native target
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Allowed Values and Equality
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported hashable key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as arguments and expected values, including nested containers where the Python type allows nesting. Equality and inequality MUST use deep structural or container-semantic comparison for nested containers. Numeric comparison MUST apply the effective tolerance to floats and `decimal.Decimal` values where tolerance is applicable. C++ and Rust targets MUST preserve these semantics for generated tests, except Python `collections.deque` operations MAY be skipped for Rust targets by marking the generated Rust test as skipped when the translation cannot map the operation to `VecDeque`. (adapts babel-code-goat-cli/add-babel-code-goat/allowed-values-and-equality)

#### Scenario: Nested null values are represented natively
- **GIVEN** a discovered test uses `None` as an argument or expected value inside a nested list, tuple, dictionary, set-compatible value, counter, default dictionary, or decimal-containing structure
- **WHEN** `generate` runs for `--lang cpp` or `--lang rust`
- **THEN** the generated tester represents the nullable position with `std::optional<T>` and `std::nullopt` for C++ or `Option<T>` and `None` for Rust

#### Scenario: Native nested values are compared structurally
- **GIVEN** a discovered equality assertion compares nested supported containers
- **WHEN** `test` runs for `--lang cpp` or `--lang rust`
- **THEN** the test result is based on nested structural or container-semantic equality rather than object identity or string formatting

#### Scenario: Native dictionary keys preserve supported key types
- **GIVEN** a discovered assertion uses a dictionary with supported non-string keys such as integers, booleans, tuples, frozensets, or decimals
- **WHEN** `generate` runs for `--lang cpp` or `--lang rust`
- **THEN** discovery succeeds and generated comparison preserves the key values rather than converting them to strings

#### Scenario: Rust skips unsupported deque operations
- **GIVEN** a discovered test requires Python `collections.deque` behavior that is not translated to Rust `VecDeque`
- **WHEN** `generate` runs for `--lang rust`
- **THEN** the generated Rust tester marks that deque-specific test as skipped instead of failing generation for otherwise supported tests

## ADDED Requirements

### Requirement: Native Target Translation Semantics
The system SHALL generate C++ testers using C++17 or later idioms and Rust testers using Rust 1.70 or later idioms. C++ generated tests MUST use `std::vector<T>`, `std::map<K,V>` or `std::unordered_map<K,V>`, `std::set<T>`, `long double`, `std::string`, `std::sort`, and `try`/`catch` with `std::exception` as appropriate. Rust generated tests MUST use `Vec<T>`, `HashMap<K,V>` or `BTreeMap<K,V>`, `HashSet<T>`, `f64`, `String`, `.sort()` or `.sort_by()`, and `catch_unwind` with `panic!` as appropriate. Rust `HashMap<String, V>` lookup generation MUST accept owned `String` keys, including forms equivalent to `get_mut(String::from("items"))`.

#### Scenario: C++ tester uses target idioms
- **GIVEN** discovered tests use nullable values, collections, decimals, strings, sorting, and exception-style expectations
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` succeeds
- **THEN** `tester.cpp` uses C++17-compatible optionals, containers, `long double`, string methods, sorting, and exception handling for those tests

#### Scenario: Rust tester uses target idioms
- **GIVEN** discovered tests use nullable values, collections, decimals, strings, sorting, and exception-style expectations
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` succeeds
- **THEN** `tester.rs` uses Rust 1.70-compatible options, collections, `f64`, string methods, sorting, and `catch_unwind` handling for those tests

#### Scenario: Rust owned string map lookup compiles
- **GIVEN** a discovered test mutates or reads a `HashMap<String, V>` entry using a string literal key such as `"items"`
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` succeeds
- **THEN** the generated lookup accepts an owned `String` key and compiles without requiring a borrowed key shape unsupported by the generated code

### Requirement: Native Solution File Structure
The system SHALL expect C++ and Rust solutions to be single source files containing the solution functions or callable constructs required by the inferred entrypoint.

#### Scenario: C++ solution is a single file
- **GIVEN** a C++ solution file contains the configured entrypoint as a function or no-argument constructible class method
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs with an existing `tester.cpp`
- **THEN** the generated tester compiles and invokes the entrypoint from that single solution file

#### Scenario: Rust solution is a single file
- **GIVEN** a Rust solution file contains the configured entrypoint as a function or compatible callable construct
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs with an existing `tester.rs`
- **THEN** the generated tester compiles and invokes the entrypoint from that single solution file
