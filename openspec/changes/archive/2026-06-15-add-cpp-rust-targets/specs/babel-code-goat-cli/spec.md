## MODIFIED Requirements

> Extends: `babel-code-goat-cli/add-babel-code-goat`
> Extends: `babel-code-goat-cli/support-single-call-traceability`
> Extends: `babel-code-goat-cli/support-mutation-directory-discovery`

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages, and MUST reject unsupported target languages without creating or modifying tester files. (adapts `babel-code-goat-cli/add-babel-code-goat/cli-commands-and-language-validation`)

#### Scenario: C++ language is accepted
- **GIVEN** `<tests_dir>/tests.py` contains supported tests for the requested entrypoint
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang cpp` is invoked
- **THEN** the command succeeds and writes the C++ tester artifacts for that test set

#### Scenario: Rust language is accepted
- **GIVEN** `<tests_dir>/tests.py` contains supported tests for the requested entrypoint
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang rust` is invoked
- **THEN** the command succeeds and writes the Rust tester artifacts for that test set

#### Scenario: Unsupported language is rejected
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang <unsupported>` is invoked
- **THEN** the command reports an error and does not create or modify any tester file

### Requirement: Test Requires Existing Tester
The system MUST require the expected tester file to already exist before running `test`. The `test` command MUST NOT create or modify the tester file, including `tester.cpp` for `--lang cpp` and `tester.rs` for `--lang rust`. (adapts `babel-code-goat-cli/add-babel-code-goat/test-requires-existing-tester`)

#### Scenario: C++ tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` is invoked and `<tests_dir>/tester.cpp` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one JSON line

#### Scenario: Rust tester is missing
- **WHEN** `test <solution_path> <tests_dir> --lang rust` is invoked and `<tests_dir>/tester.rs` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one JSON line

#### Scenario: Existing native tester is preserved during test
- **GIVEN** the expected native tester file exists
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` or `test <solution_path> <tests_dir> --lang rust` is invoked
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Allowed Values and Equality
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, and dictionaries with string keys as arguments and expected values for every supported target language, including nested containers. For C++ and Rust targets, `None`/`null` MUST be supported anywhere the Python test value model allows it, including inside lists, tuples, and dictionaries. Equality and inequality assertions MUST compare translated values according to the Python test expectations represented in the generated tester. (adapts `babel-code-goat-cli/add-babel-code-goat/allowed-values-and-equality`)

#### Scenario: Nested null values are translated for C++
- **GIVEN** a Python test passes and expects values containing `None` inside nested lists and dictionaries
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang cpp` is invoked
- **THEN** the generated C++ tester represents those values with nullable C++ types and preserves the expected equality behavior

#### Scenario: Nested null values are translated for Rust
- **GIVEN** a Python test passes and expects values containing `None` inside nested lists and dictionaries
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang rust` is invoked
- **THEN** the generated Rust tester represents those values with `Option<T>` values and preserves the expected equality behavior

#### Scenario: Interpreted and native target outcomes match
- **GIVEN** the same supported Python tests are generated for Python, C++, and Rust
- **WHEN** each generated tester is run against equivalent target solutions
- **THEN** each target reports the same passed and failed test identifiers for value equality and inequality checks

## ADDED Requirements

### Requirement: C++ Target Semantics
The system SHALL generate and test C++ solutions as single-file C++17-or-newer programs. Generated C++ code MUST use idiomatic standard library types for translated values, including `std::optional<T>` and `std::nullopt` for nullability, `std::vector<T>`, `std::map<K,V>`, `std::unordered_map<K,V>`, `std::set<T>`, `long double`, and `std::string`.

#### Scenario: C++ tester uses native value mappings
- **GIVEN** Python tests include nullable values, containers, strings, decimals, sorting, and exception-style expectations
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang cpp` is invoked
- **THEN** the generated `tester.cpp` uses C++17-or-newer constructs that can compile and evaluate those expectations

#### Scenario: C++ test command runs generated tester
- **GIVEN** `<tests_dir>/tester.cpp` exists and `<solution_path>` contains the C++ solution functions
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` is invoked
- **THEN** the command compiles or executes the generated tester and reports passed and failed tests as JSON

### Requirement: Rust Target Semantics
The system SHALL generate and test Rust solutions as single-file Rust 1.70-or-newer programs. Generated Rust code MUST use idiomatic standard library types for translated values, including `Option<T>`, `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, `HashSet<T>`, `f64`, and `String`.

#### Scenario: Rust tester uses native value mappings
- **GIVEN** Python tests include nullable values, containers, strings, decimals, sorting, and exception-style expectations
- **WHEN** `generate <tests_dir> --entrypoint <entrypoint> --lang rust` is invoked
- **THEN** the generated `tester.rs` uses Rust 1.70-or-newer constructs that can compile and evaluate those expectations

#### Scenario: Rust string-key map lookup accepts owned keys
- **GIVEN** a translated Python test mutates or reads a string-keyed dictionary
- **WHEN** the Rust tester generates `HashMap<String, V>` access code
- **THEN** the generated lookup accepts owned `String` keys such as `String::from("items")`

#### Scenario: Rust test command runs generated tester
- **GIVEN** `<tests_dir>/tester.rs` exists and `<solution_path>` contains the Rust solution functions
- **WHEN** `test <solution_path> <tests_dir> --lang rust` is invoked
- **THEN** the command compiles or executes the generated tester and reports passed and failed tests as JSON

### Requirement: Rust Deque Handling
The system MUST skip Python tests that require `collections.deque` behavior when generating or running Rust targets if the standard translation does not map those operations to `VecDeque`.

#### Scenario: Rust deque test is skipped
- **GIVEN** a Python test requires `collections.deque` behavior
- **WHEN** the test set is generated or run with `--lang rust`
- **THEN** the deque-dependent test is marked skipped for Rust without causing unrelated Rust tests to fail
