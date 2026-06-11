## ADDED Requirements

### Requirement: C++ Target Execution
The system SHALL support `cpp` as a target language for generated and executed tests. C++ target execution MUST use modern C++ with C++17 or later semantics, MUST run single-file C++ solutions containing the configured solution function, and MUST represent translated values with idiomatic C++ types including `std::optional<T>` / `std::nullopt`, `std::vector<T>`, `std::map<K,V>`, `std::unordered_map<K,V>`, `std::set<T>`, `long double`, and `std::string`.

#### Scenario: C++ free function executes
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` succeeds and `test <solution.cpp> <tests_dir> --lang cpp` runs against a single-file C++ solution defining `solve`
- **THEN** the command compiles and executes the C++ target tests and reports the discovered test IDs using the standard JSON status contract

#### Scenario: C++ null values use optional
- **WHEN** a discovered C++ target test passes or compares `None` nested inside any supported argument or expected value
- **THEN** the generated C++ harness represents the nullable position using `std::optional<T>` and `std::nullopt`

#### Scenario: C++ target supports documented operations
- **WHEN** a discovered C++ target test uses supported string methods, sorting, collection equality, numeric tolerance, raw output expectations, mutation-style assertions, or exception-style expectations
- **THEN** the C++ target runner evaluates the behavior with the same pass/fail meaning as the Python target, using C++ equivalents such as `std::string`, `std::sort`, and `try` / `catch`

### Requirement: Rust Target Execution
The system SHALL support `rust` as a target language for generated and executed tests. Rust target execution MUST use modern Rust 1.70-or-newer semantics, MUST run single-file Rust solutions containing the configured solution function, and MUST represent translated values with idiomatic Rust types including `Option<T>` / `None`, `Vec<T>`, `HashMap<K,V>`, `BTreeMap<K,V>`, `HashSet<T>`, `f64`, and `String`.

#### Scenario: Rust free function executes
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` succeeds and `test <solution.rs> <tests_dir> --lang rust` runs against a single-file Rust solution defining `solve`
- **THEN** the command compiles and executes the Rust target tests and reports the discovered test IDs using the standard JSON status contract

#### Scenario: Rust null values use Option
- **WHEN** a discovered Rust target test passes or compares `None` nested inside any supported non-deque argument or expected value
- **THEN** the generated Rust harness represents the nullable position using `Option<T>` and `None`

#### Scenario: Rust HashMap String lookup supports owned keys
- **WHEN** a Rust solution mutates a `HashMap<String, V>` argument using an owned key expression such as `get_mut(String::from("items"))`
- **THEN** the translated Rust target values allow the lookup to compile and use the expected map entry

#### Scenario: Rust target supports documented operations
- **WHEN** a discovered Rust target test uses supported string methods, sorting, collection equality, numeric tolerance, raw output expectations, mutation-style assertions, or exception-style expectations
- **THEN** the Rust target runner evaluates the behavior with the same pass/fail meaning as the Python target, using Rust equivalents such as `String` methods, `.sort()` / `.sort_by()`, and `catch_unwind` with `panic!`

### Requirement: Compiled Target Value Model Parity
The system SHALL preserve the supported Python test value model and behavior for C++ and Rust targets, including `None` / `null` at any supported value position. C++ MUST support all allowed value categories. Rust MUST support all allowed value categories except Python `collections.deque` behavior.

#### Scenario: C++ supports all allowed values
- **WHEN** a discovered test uses `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with supported hashable keys, sets, frozensets, counters, deques, default dictionaries, or decimals as arguments or expected values for `--lang cpp`
- **THEN** discovery and C++ target execution preserve the value meaning for comparison and mutation behavior

#### Scenario: Rust supports all non-deque allowed values
- **WHEN** a discovered test uses `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with supported hashable keys, sets, frozensets, counters, default dictionaries, or decimals as arguments or expected values for `--lang rust`
- **THEN** discovery and Rust target execution preserve the value meaning for comparison and mutation behavior

#### Scenario: Null appears anywhere
- **WHEN** a discovered C++ or Rust target test contains `None` as a top-level value, nested list element, nested tuple element, dictionary key or value where hashability allows it, set member, counter key, default dictionary value, or return expectation
- **THEN** the target runner represents and compares the null value without converting it to a string, zero, false, or an absent value

### Requirement: Rust Deque Handling
The system MUST NOT require Rust target execution to support Python `collections.deque` operations. Tests that require deque behavior for Rust MUST be skipped or excluded for Rust target verification rather than translated to Rust `VecDeque` behavior.

#### Scenario: Rust deque behavior is excluded
- **WHEN** a test suite contains cases that require Python `collections.deque` behavior and the same suite is verified for `--lang rust`
- **THEN** those Rust-specific verification cases are marked skipped or excluded instead of requiring the Rust target runner to map the behavior to `VecDeque`

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

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from all `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, constrained mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. The system MUST report a discovery error for non-`.py` files under `<tests_dir>` whose stem matches `test*`, `*_test`, `tests`, or `*_tests`, except for generated tester artifacts named `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs`.

#### Scenario: Assertions inside functions are discovered
- **WHEN** a Python test source under `<tests_dir>` contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Tests in nested Python files are discovered
- **WHEN** `<tests_dir>/nested/test_values.py` contains `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test

#### Scenario: Supported assertion forms are discovered
- **WHEN** a Python test source contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** a Python test source contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** a Python test source contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** a Python test source contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** a Python test source contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** a Python test source contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** a Python test source contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** a Python test source imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Non-Python test-like file is rejected
- **WHEN** `<tests_dir>` contains a non-`.py` file with a filename such as `test_data.json`, `values_test.txt`, `tests.yaml`, or `integration_tests.md`
- **THEN** discovery fails

#### Scenario: Generated non-Python tester file is ignored by discovery
- **WHEN** `<tests_dir>` contains the generated `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs` file and otherwise contains discoverable Python tests
- **THEN** discovery ignores the generated tester file and succeeds

#### Scenario: No discovered tests is rejected
- **WHEN** recursive discovery under `<tests_dir>` finds no tests
- **THEN** discovery fails

#### Scenario: Discovery fails
- **WHEN** a Python test source cannot be read, cannot be parsed, contains unsupported test constructs, or a non-`.py` test-like file is present under `<tests_dir>`
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Solution Callable Resolution
The code under test MUST be in the same language as the generated tester. For Python, JavaScript, and TypeScript targets, the system SHALL call the inferred entrypoint when it is available as a callable named by the entrypoint, as a method with that name on a class constructible with no arguments, or as a static method with that name. For C++ and Rust targets, the system SHALL call a single-file solution function named by the inferred entrypoint.

#### Scenario: Callable function is used
- **WHEN** the solution defines a callable named by the inferred entrypoint
- **THEN** the system invokes that callable for each discovered test

#### Scenario: No-argument class method is used
- **WHEN** a Python, JavaScript, or TypeScript solution defines a class constructible with no arguments and that class has a callable method named by the inferred entrypoint
- **THEN** the system constructs the class and invokes the method for each discovered test

#### Scenario: Static method is used
- **WHEN** a Python, JavaScript, or TypeScript solution defines a class with a callable static method named by the inferred entrypoint
- **THEN** the system invokes the static method for each discovered test

#### Scenario: C++ single-file function is used
- **WHEN** a C++ solution file defines a function named by the inferred entrypoint and `test` is invoked with `--lang cpp`
- **THEN** the system compiles the solution with the generated C++ tester and invokes that function for each executable discovered test

#### Scenario: Rust single-file function is used
- **WHEN** a Rust solution file defines a function named by the inferred entrypoint and `test` is invoked with `--lang rust`
- **THEN** the system compiles the solution with the generated Rust tester and invokes that function for each executable discovered test
