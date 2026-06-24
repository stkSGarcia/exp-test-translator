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
The system SHALL support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as allowed argument and expected values. Nested allowed values MUST be supported, and `None`/null MUST be accepted anywhere inside nested arguments, expected values, dictionary keys where supported by the target representation, and container values. Equality and inequality checks MUST use deep structural comparison for nested containers according to each container's meaning.

#### Scenario: None value is accepted
- **WHEN** a discovered assertion passes `None` as an argument or compares the entrypoint result to `None`
- **THEN** discovery succeeds and the selected tester compares the value using target null semantics

#### Scenario: Nested None values compare structurally
- **WHEN** a discovered assertion compares nested allowed containers that contain `None`
- **THEN** the test result is based on deep structural equality including the nested null positions

#### Scenario: Nested values compare structurally
- **WHEN** a discovered assertion compares nested allowed containers returned by the entrypoint
- **THEN** the test result is based on deep structural equality

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
- **WHEN** a discovered assertion compares a `collections.deque` value returned by the entrypoint for a target that supports deque translation
- **THEN** the test result is based on the deque's ordered contents

#### Scenario: Defaultdict values compare mapping contents
- **WHEN** a discovered assertion compares a `collections.defaultdict` value returned by the entrypoint
- **THEN** the test result is based on mapping contents and does not require matching default factory identity

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered assertion compares a `decimal.Decimal` value with another numeric supported value
- **THEN** the test result is based on numeric value semantics, including tolerance where applicable

#### Scenario: Unsupported literal fails discovery
- **WHEN** an argument or expected value is outside the allowed value set
- **THEN** discovery fails

### Requirement: Solution callable forms
The system SHALL test code written in the same language as the selected tester. The callable under test MUST be accepted when it is either a callable named by the inferred entrypoint or a no-argument constructible class with a callable method or static method of that name. For C++ and Rust targets, the generated tester MUST accept single-file solutions that expose the entrypoint as a function, static method, or no-argument constructible class method using target-native types.

#### Scenario: Top-level callable is used
- **WHEN** the solution exposes a callable with the inferred entrypoint name
- **THEN** the tester invokes that callable for discovered tests

#### Scenario: No-argument class method is used
- **WHEN** the solution exposes a no-argument constructible class with a callable method matching the inferred entrypoint name
- **THEN** the tester constructs the class and invokes that method for discovered tests

#### Scenario: C++ function solution is used
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang cpp` and the solution exposes a compatible C++ function with the inferred entrypoint name
- **THEN** the generated C++ tester compiles with the solution and invokes that function for discovered tests

#### Scenario: Rust function solution is used
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang rust` and the solution exposes a compatible Rust function with the inferred entrypoint name
- **THEN** the generated Rust tester compiles with the solution and invokes that function for discovered tests

## ADDED Requirements

### Requirement: C++ target execution
The system SHALL generate and execute C++ testers using modern C++17 or later. Generated C++ testers MUST support nullable values with `std::optional<T>` and `std::nullopt`, strings with `std::string`, ordered collections with `std::vector<T>`, map-like values with `std::map<K,V>` or `std::unordered_map<K,V>`, sets with `std::set<T>`, decimal/high-precision numeric values with `long double`, sorting with `std::sort`, and exception-style tests with `try`, `throw std::runtime_error`, and `catch (const std::exception& e)` semantics.

#### Scenario: C++ null argument and expected value pass
- **WHEN** generated C++ tests include `None` as an argument or expected value
- **THEN** the C++ tester represents those values with `std::optional<T>`/`std::nullopt` and reports the discovered test according to the standard result JSON

#### Scenario: C++ rich containers compare structurally
- **WHEN** generated C++ tests include nested vectors, maps, unordered maps, sets, counters, decimals, and strings
- **THEN** the C++ tester evaluates assertions with the same structural, unordered, count, numeric, and string semantics as the Python-authored tests

#### Scenario: C++ exception-style test passes
- **WHEN** a discovered raise expectation is executed against a C++ solution that throws a matching `std::exception`
- **THEN** the C++ tester reports that test ID in `passed`

#### Scenario: C++ compile failure reports error
- **WHEN** the generated C++ tester cannot be compiled with the provided solution
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Rust target execution
The system SHALL generate and execute Rust testers using Rust 1.70 or later. Generated Rust testers MUST support nullable values with `Option<T>`, `Some(value)`, and `None`, strings with `String`, ordered collections with `Vec<T>`, map-like values with `HashMap<K,V>` and `BTreeMap<K,V>`, sets with `HashSet<T>`, decimal numeric values with `f64`, sorting with `.sort()` or `.sort_by()`, string methods including `find`, `split`, `len`, `is_empty`, `to_lowercase`, and `trim`, owned `String` lookup keys for `HashMap<String, V>`, and exception-style tests with `catch_unwind` and `panic!`.

#### Scenario: Rust null argument and expected value pass
- **WHEN** generated Rust tests include `None` as an argument or expected value
- **THEN** the Rust tester represents those values with `Option<T>` and reports the discovered test according to the standard result JSON

#### Scenario: Rust rich containers compare structurally
- **WHEN** generated Rust tests include nested vectors, hash maps, tree maps, hash sets, counters, decimals, and strings
- **THEN** the Rust tester evaluates assertions with the same structural, unordered, count, numeric, and string semantics as the Python-authored tests

#### Scenario: Rust owned String map lookup is supported
- **WHEN** a Rust solution uses an owned key such as `String::from("items")` to call `get_mut` on a `HashMap<String, V>` received from the tester
- **THEN** the generated Rust tester supports the solution call shape without requiring borrowed string literals

#### Scenario: Rust exception-style test passes
- **WHEN** a discovered raise expectation is executed against a Rust solution that panics in the expected way
- **THEN** the Rust tester uses `catch_unwind` and reports that test ID in `passed`

#### Scenario: Rust compile failure reports error
- **WHEN** the generated Rust tester cannot be compiled with the provided solution
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Rust deque handling
The system SHALL skip tests that require Python `collections.deque` behavior for Rust targets. The skip MUST be represented in the project test suite with `@pytest.mark.skipif` when the selected target is Rust and the Python test fixture requires deque behavior.

#### Scenario: Rust deque-specific parity test is skipped
- **WHEN** the Python test suite parameterizes a parity case that requires `collections.deque` behavior and the selected target is Rust
- **THEN** that pytest case is skipped rather than requiring the generated Rust tester to translate deque behavior

#### Scenario: Non-deque Rust values remain supported
- **WHEN** generated Rust tests include supported values other than Python deque behavior
- **THEN** those tests are generated and executed normally
