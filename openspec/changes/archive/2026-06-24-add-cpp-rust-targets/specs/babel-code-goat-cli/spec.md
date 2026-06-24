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
The system SHALL support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as allowed argument and expected values for every supported target language. Nested allowed values MUST be supported, including `None`/`null` values at any nested position. Equality and inequality checks MUST use deep structural comparison for nested containers according to each container's meaning.

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
- **WHEN** a discovered assertion compares a `collections.deque` value returned by the entrypoint
- **THEN** the test result is based on the deque's ordered contents

#### Scenario: Defaultdict values compare mapping contents
- **WHEN** a discovered assertion compares a `collections.defaultdict` value returned by the entrypoint
- **THEN** the test result is based on mapping contents and does not require matching default factory identity

#### Scenario: Decimal values participate in numeric comparison
- **WHEN** a discovered assertion compares a `decimal.Decimal` value with another numeric supported value
- **THEN** the test result is based on numeric value semantics, including tolerance where applicable

#### Scenario: Nested null values are preserved for compiled targets
- **WHEN** a C++ or Rust solution is tested against discovered arguments or expected values containing `None` inside lists, tuples, dictionaries, sets, counters, deques, or defaultdicts
- **THEN** the generated tester represents those values as target-language nullable values and compares them without dropping or stringifying the null entries

#### Scenario: Unsupported literal fails discovery
- **WHEN** an argument or expected value is outside the allowed value set
- **THEN** discovery fails

### Requirement: Solution callable forms
The system SHALL test code written in the same language as the selected tester. For Python, JavaScript, and TypeScript, the callable under test MUST be accepted when it is either a callable named by the inferred entrypoint or a no-argument constructible class with a callable method or static method of that name. For C++ and Rust, the solution MUST be accepted as a single source file containing a solution function with the inferred entrypoint name and a supported generated signature.

#### Scenario: Top-level callable is used
- **WHEN** the solution exposes a callable with the inferred entrypoint name
- **THEN** the tester invokes that callable for discovered tests

#### Scenario: No-argument class method is used
- **WHEN** a Python, JavaScript, or TypeScript solution exposes a no-argument constructible class with a callable method matching the inferred entrypoint name
- **THEN** the tester constructs the class and invokes that method for discovered tests

#### Scenario: C++ solution function is used
- **WHEN** a C++ solution source file contains a supported function with the inferred entrypoint name
- **THEN** the generated C++ tester compiles with that source and invokes the function for discovered tests

#### Scenario: Rust solution function is used
- **WHEN** a Rust solution source file contains a supported function with the inferred entrypoint name
- **THEN** the generated Rust tester compiles with that source and invokes the function for discovered tests

## ADDED Requirements

### Requirement: Compiled target execution
The system SHALL execute C++ targets with modern C++ support compatible with C++17 or later and Rust targets with Rust 1.70 or later. Generated C++ testers MUST represent `None`/`null` values with `std::optional<T>` and `std::nullopt`; generated Rust testers MUST represent them with `Option<T>` and `None`. Generated compiled testers MUST support the same discovered test kinds, comparison outcomes, output capture expectations, mutation grouping, loop reporting, tolerance metadata, primitive expression evaluation, and result JSON contract as interpreted targets, except Rust tests whose required behavior depends on Python `collections.deque` operations MUST be skippable by the project test suite.

#### Scenario: C++ tester runs rich value tests
- **WHEN** the user generates and tests a C++ solution for discovered tests containing nested containers, nullable values, strings, maps, sets, decimal-like numeric values, sorting, and primitive expressions
- **THEN** the generated C++ tester reports pass, fail, or error using the standard one-line JSON contract

#### Scenario: Rust tester runs rich value tests
- **WHEN** the user generates and tests a Rust solution for discovered tests containing nested containers, nullable values, strings, maps, sets, f64 numeric values, sorting, and primitive expressions
- **THEN** the generated Rust tester reports pass, fail, or error using the standard one-line JSON contract

#### Scenario: C++ exception-style test is evaluated
- **WHEN** a discovered raise expectation test is executed against a C++ solution that throws `std::runtime_error` or another `std::exception`
- **THEN** the generated tester evaluates the exception type/message expectation and reports the test ID in `passed` or `failed`

#### Scenario: Rust panic-style test is evaluated
- **WHEN** a discovered raise expectation test is executed against a Rust solution that uses `panic!`
- **THEN** the generated tester evaluates the panic expectation with `catch_unwind` and reports the test ID in `passed` or `failed`

#### Scenario: Rust owned string map lookup is supported
- **WHEN** a mutation-style Rust test needs to access a `HashMap<String, V>` entry using an owned key such as `String::from("items")`
- **THEN** the generated Rust tester supports the lookup without requiring a borrowed string literal key
