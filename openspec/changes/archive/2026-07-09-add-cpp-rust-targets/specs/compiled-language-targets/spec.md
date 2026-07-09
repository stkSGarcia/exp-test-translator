## ADDED Requirements
> Extends: babel-code-goat-cli/add-babel-code-goat

### Requirement: Compiled target command support (adapts babel-code-goat-cli/add-babel-code-goat/supported-command-interface)
The system SHALL accept `--lang cpp` and `--lang rust` for both `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang>` and `test <solution_path> <tests_dir> --lang <target_lang>`.

#### Scenario: Generate accepts C++ target
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang cpp`
- **THEN** the command succeeds if the discovered tests can be translated for C++

#### Scenario: Test accepts Rust target
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang rust`
- **THEN** the command executes the Rust tester when the expected generated tester file exists

### Requirement: Compiled tester generation (adapts babel-code-goat-cli/add-babel-code-goat/tester-generation)
The system SHALL generate exactly one compiled tester file in `<tests_dir>` for the requested compiled target: `tester.cpp` for C++ and `tester.rs` for Rust.

#### Scenario: C++ tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang cpp` and generation succeeds
- **THEN** `<tests_dir>/tester.cpp` exists and the command exits `0`

#### Scenario: Rust tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang rust` and generation succeeds
- **THEN** `<tests_dir>/tester.rs` exists and the command exits `0`

### Requirement: Compiled solution callable forms (adapts babel-code-goat-cli/add-babel-code-goat/solution-callable-forms)
The system SHALL test C++ and Rust code written in the same language as the selected compiled tester, using a single solution file containing the solution functions named by the inferred entrypoint.

#### Scenario: C++ solution file is tested
- **WHEN** the user runs `test solution.cpp <tests_dir> --lang cpp` and `<tests_dir>/tester.cpp` exists
- **THEN** the system compiles and executes a C++17-or-later test binary that calls the entrypoint from `solution.cpp`

#### Scenario: Rust solution file is tested
- **WHEN** the user runs `test solution.rs <tests_dir> --lang rust` and `<tests_dir>/tester.rs` exists
- **THEN** the system compiles and executes a Rust 1.70-or-later test binary that calls the entrypoint from `solution.rs`

### Requirement: Compiled value model parity (adapts babel-code-goat-cli/add-babel-code-goat/allowed-values-and-equality)
The system SHALL support every Python-test value type and equality behavior supported by interpreted targets for C++ and Rust targets, including `None`/`null` values anywhere in scalars, collections, maps, expected values, arguments, and mutation payloads.

#### Scenario: Nested null values are preserved
- **WHEN** a discovered test uses `None` inside a list, tuple, dictionary, argument, expected value, or mutation payload
- **THEN** C++ generation represents the value with `std::optional<T>` and `std::nullopt` where required, and Rust generation represents the value with `Option<T>`, `Some(value)`, and `None` where required

#### Scenario: Compiled collection values are compared
- **WHEN** a discovered test uses supported collection values
- **THEN** C++ generation supports `std::vector<T>`, `std::map<K,V>`, `std::unordered_map<K,V>`, and `std::set<T>`, and Rust generation supports `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, and `HashSet<T>`

#### Scenario: Compiled scalar and string behaviors are compared
- **WHEN** a discovered test uses numeric, string, sorting, or exception-style behavior supported by interpreted targets
- **THEN** C++ generation supports `long double`, `std::string` methods, `std::sort()`, and `std::runtime_error` assertions, and Rust generation supports `f64`, `String` methods, `.sort()` or `.sort_by()`, and `catch_unwind` with `panic!`

### Requirement: Compiled test command requires generated tester (adapts babel-code-goat-cli/add-babel-code-goat/test-command-requires-generated-tester)
The `test` command SHALL require the expected compiled tester file for the selected language to already exist in `<tests_dir>`, and MUST NOT create or modify `tester.cpp` or `tester.rs`.

#### Scenario: Missing C++ tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang cpp` and `<tests_dir>/tester.cpp` is missing
- **THEN** stdout reports an error result and stderr names `tester.cpp` as the missing generated tester

#### Scenario: Missing Rust tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang rust` and `<tests_dir>/tester.rs` is missing
- **THEN** stdout reports an error result and stderr names `tester.rs` as the missing generated tester

### Requirement: Rust deque behavior skip
The system SHALL skip Python `collections.deque` operations for Rust targets when the standard translation cannot map the operation to Rust target behavior.

#### Scenario: Rust deque test is skipped
- **WHEN** a discovered Python test requires `collections.deque` behavior and the selected target is `rust`
- **THEN** the generated or translated test is marked with a Rust-specific skip rather than producing an invalid Rust tester
