## ADDED Requirements

### Requirement: Compiled target execution
The system SHALL generate and run self-contained compiled-language testers for C++ and Rust solutions. C++ generated testers MUST use C++17 or later language features and Rust generated testers MUST use Rust 1.70-compatible language features. The `test` command MUST compile the generated tester together with the supplied single-file solution and then execute the compiled binary. Compiler, linker, or runtime harness failures MUST produce the standard error JSON and exit code `2`.

#### Scenario: C++ solution is compiled and tested
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang cpp` after generating `<tests_dir>/tester.cpp`
- **THEN** the command compiles the C++ tester with the supplied solution file, runs the resulting binary, and reports discovered test results using the standard JSON output contract

#### Scenario: Rust solution is compiled and tested
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang rust` after generating `<tests_dir>/tester.rs`
- **THEN** the command compiles the Rust tester with the supplied solution file, runs the resulting binary, and reports discovered test results using the standard JSON output contract

#### Scenario: Compiled target build failure is an error
- **WHEN** a C++ or Rust tester cannot be compiled for the supplied solution
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Compiled target value rendering
The system SHALL render discovered test arguments, expected values, and comparison helpers into target-native C++ and Rust code while preserving the supported value and behavior semantics of Python tests. C++ testers MUST represent nullability with `std::optional<T>` and `std::nullopt`; Rust testers MUST represent nullability with `Option<T>`, `Some(value)`, and `None`. Nullable values MUST be supported at any nesting depth when a concrete target type can be inferred.

#### Scenario: Nested C++ null values are generated
- **WHEN** a discovered test passes or expects nested `None` values and the user generates `--lang cpp`
- **THEN** `<tests_dir>/tester.cpp` represents those values with nested `std::optional` values and `std::nullopt` without losing container structure

#### Scenario: Nested Rust null values are generated
- **WHEN** a discovered test passes or expects nested `None` values and the user generates `--lang rust`
- **THEN** `<tests_dir>/tester.rs` represents those values with nested `Option` values and `None` without losing container structure

#### Scenario: C++ target-native containers are generated
- **WHEN** a discovered C++ target test uses supported lists, dictionaries, or sets
- **THEN** the generated tester uses target-native containers such as `std::vector`, `std::map`, `std::unordered_map`, and `std::set` with deep comparison helpers

#### Scenario: Rust target-native containers are generated
- **WHEN** a discovered Rust target test uses supported lists, dictionaries, or sets
- **THEN** the generated tester uses target-native containers such as `Vec`, `HashMap`, `BTreeMap`, and `HashSet` with deep comparison helpers

#### Scenario: Rust owned string map lookup works
- **WHEN** a Rust generated tester mutates or reads a `HashMap<String, V>` entry using a string key from discovered data
- **THEN** the generated code uses an owned `String` key form accepted by Rust, such as `get_mut(String::from("items"))`

### Requirement: Compiled target exception expectations
The system SHALL support discovered raise expectation tests for C++ and Rust targets using target-language exception mechanisms. C++ generated testers MUST evaluate exception expectations with `try` and `catch (const std::exception&)`. Rust generated testers MUST evaluate exception-style expectations with `std::panic::catch_unwind` and `panic!`.

#### Scenario: C++ exception expectation passes
- **WHEN** a discovered raise expectation is generated for `--lang cpp` and the C++ solution throws a matching `std::exception`
- **THEN** the test passes according to the expected exception type and message matching metadata

#### Scenario: Rust panic expectation passes
- **WHEN** a discovered raise expectation is generated for `--lang rust` and the Rust solution panics with matching message metadata
- **THEN** the test passes according to the exception-style expectation

#### Scenario: Missing compiled exception fails
- **WHEN** a discovered raise expectation is generated for C++ or Rust and the solution does not throw or panic
- **THEN** that test ID appears in `failed`

## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate` or `test` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

### Requirement: Tester generation
The system SHALL generate exactly one tester file in `<tests_dir>` for the requested language: `tester.py` for Python, `tester.js` for JavaScript, `tester.ts` for TypeScript, `tester.cpp` for C++, and `tester.rs` for Rust. On successful generation the command MUST exit `0`.

#### Scenario: Python tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang python` and generation succeeds
- **THEN** `<tests_dir>/tester.py` exists and the command exits `0`

#### Scenario: JavaScript tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang javascript` and generation succeeds
- **THEN** `<tests_dir>/tester.js` exists and the command exits `0`

#### Scenario: TypeScript tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang typescript` and generation succeeds
- **THEN** `<tests_dir>/tester.ts` exists and the command exits `0`

#### Scenario: C++ tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang cpp` and generation succeeds
- **THEN** `<tests_dir>/tester.cpp` exists and the command exits `0`

#### Scenario: Rust tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang rust` and generation succeeds
- **THEN** `<tests_dir>/tester.rs` exists and the command exits `0`

#### Scenario: Failed generation preserves tester files
- **WHEN** the user runs `generate` and generation fails
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs`

### Requirement: Test command requires generated tester
The `test` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `test` command MUST NOT create or modify any tester file.

#### Scenario: Missing Python tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python` and `<tests_dir>/tester.py` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing JavaScript tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript` and `<tests_dir>/tester.js` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing TypeScript tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang typescript` and `<tests_dir>/tester.ts` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing C++ tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang cpp` and `<tests_dir>/tester.cpp` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing Rust tester errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang rust` and `<tests_dir>/tester.rs` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Allowed values and equality
The system SHALL support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as allowed argument and expected values for every supported target language except where Rust deque operation tests are explicitly skipped. Nested allowed values MUST be supported, including `None` at any nesting depth. Equality and inequality checks MUST use deep structural comparison for nested containers according to each container's meaning.

#### Scenario: Nested values compare structurally
- **WHEN** a discovered assertion compares nested allowed containers returned by the entrypoint
- **THEN** the test result is based on deep structural equality

#### Scenario: Nested None values compare structurally
- **WHEN** a discovered assertion compares nested containers containing `None` values
- **THEN** the test result preserves null positions and compares them structurally for the selected target language

#### Scenario: Dictionary keys use supported key semantics
- **WHEN** a discovered assertion uses a dictionary with non-string supported keys such as integers, tuples, booleans, or `Decimal` values
- **THEN** discovery succeeds and comparison preserves key identity according to the supported key values

#### Scenario: Sets and frozensets compare unordered contents
- **WHEN** a discovered assertion compares a `set` or `frozenset` value returned by the entrypoint
- **THEN** the test result is based on unordered membership rather than insertion or serialization order

#### Scenario: Counter values compare counts
- **WHEN** a discovered assertion compares a `collections.Counter` value returned by the entrypoint
- **THEN** the test result is based on the counter's element counts

#### Scenario: Deque values compare ordered contents
- **WHEN** a discovered assertion compares a `collections.deque` value returned by the entrypoint for a target that supports deque tests
- **THEN** the test result is based on the deque's ordered contents

#### Scenario: Rust deque operation tests are skipped
- **WHEN** project coverage includes tests that require Python `collections.deque` operation behavior for the Rust target
- **THEN** those Rust-specific tests are skipped rather than treated as Rust target failures

#### Scenario: Defaultdict values compare mapping contents
- **WHEN** a discovered assertion compares a `collections.defaultdict` value returned by the entrypoint
- **THEN** the test result is based on mapping contents and does not require matching default factory identity

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered assertion compares a `decimal.Decimal` value with another numeric supported value
- **THEN** the test result is based on numeric value semantics, including tolerance where applicable

#### Scenario: Unsupported literal fails discovery
- **WHEN** an argument or expected value is outside the allowed value set
- **THEN** discovery fails
