## Purpose

Defines the Babel Code Goat CLI contract for generating language-specific tester files and running translated tests from a constrained `tests.py` format.
## Requirements
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

### Requirement: Test JSON Output and Exit Codes
The `test` command MUST print exactly one line to stdout containing a JSON object with only the keys `status`, `passed`, and `failed`. The status MUST be one of `pass`, `fail`, or `error`; `passed` and `failed` MUST be arrays. The command MUST exit with code 0 for `pass`, code 1 for `fail`, and code 2 for `error`.

#### Scenario: All tests pass
- **WHEN** all discovered tests pass
- **THEN** `test` prints a single JSON line with `status` set to `pass`, all passing test IDs in `passed`, an empty `failed` array, no extra keys, and exits with code 0

#### Scenario: At least one test fails
- **WHEN** at least one discovered test fails after successful discovery
- **THEN** `test` prints a single JSON line with `status` set to `fail`, includes failed test IDs in `failed`, includes passing test IDs in `passed`, no extra keys, and exits with code 1

#### Scenario: Test command errors
- **WHEN** `test` encounters an error condition before successful test execution
- **THEN** `test` prints a single JSON line with `status` set to `error`, no extra keys, and exits with code 2

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion, mutation assertion, or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. The system MUST reject any non-`.py` file under `<tests_dir>` whose filename has a non-Python extension and matches `test*`, `*_test`, `tests`, or `*_tests` before that extension. The system MUST fail discovery when recursive discovery finds no tests.

#### Scenario: Assertions inside functions are discovered
- **WHEN** a Python test file contains a function with `assert ENTRYPOINT(args...) == expected`
- **THEN** discovery includes that assertion as a test even if the function is never called

#### Scenario: Supported assertion forms are discovered
- **WHEN** a Python test file contains `assert ENTRYPOINT(args...) == expected`, `assert expected == ENTRYPOINT(args...)`, `assert ENTRYPOINT(args...) != expected`, `assert ENTRYPOINT(args...)`, `assert not ENTRYPOINT(args...)`, a supported `math.isclose(...)` assertion, or a supported `abs(a - b) < tol` / `<= tol` assertion
- **THEN** each assertion is discovered as one test

#### Scenario: Primitive operation assertions are discovered
- **WHEN** a Python test file contains a supported primitive expression such as `assert ENTRYPOINT(1, 2) in [1, 2, 3]`, `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`, or `assert ENTRYPOINT("abc").upper() == "ABC"`
- **THEN** each assertion is discovered as one test that evaluates the primitive expression after invoking the entrypoint exactly once

#### Scenario: Loop constructs are discovered
- **WHEN** a Python test file contains a supported `for` loop, `enumerate` loop, index-based loop, `while` loop, or nested loop with allowed assertions in its body
- **THEN** discovery includes loop tests for the loop statements and assertion tests for each executed loop-body assertion

#### Scenario: Recursive Python files are discovered
- **WHEN** `<tests_dir>` contains `tests.py` and `nested/test_more.py` with supported test constructs
- **THEN** discovery includes tests from both Python files

#### Scenario: Test-like non-Python file is rejected
- **WHEN** `<tests_dir>` contains `test_cases.txt`, `case_test.md`, `tests.json`, or `case_tests.yaml`
- **THEN** discovery fails

#### Scenario: Empty recursive discovery is rejected
- **WHEN** `<tests_dir>` contains no supported tests in any recursively discovered Python file
- **THEN** discovery fails

#### Scenario: Multi-entrypoint assertion is rejected
- **WHEN** a Python test file contains an assertion such as `assert ENTRYPOINT(1) == ENTRYPOINT(2)` or `assert ENTRYPOINT(1) + ENTRYPOINT(2) == 3`
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

#### Scenario: Unsupported helper call assertion is rejected
- **WHEN** a Python test file contains an assertion such as `assert helper(ENTRYPOINT(1)) == 2` or `assert ENTRYPOINT(helper(1)) == 2`
- **THEN** discovery fails because the assertion depends on an unsupported non-primitive function call

#### Scenario: Raise-any expectation block is discovered
- **WHEN** a Python test file contains `try: ENTRYPOINT(args...); assert False` followed by `except Exception: pass`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed expectation block is discovered
- **WHEN** a Python test file contains `try: ENTRYPOINT(args...); assert False` followed by `except ValueError as e: assert "bad" in str(e)`
- **THEN** the try/except block is discovered as one test that passes only when the entrypoint raises the expected exception type and message

#### Scenario: Restricted helper imports are accepted
- **WHEN** a Python test file imports `math`, `re`, `collections`, or `decimal`, or imports `Counter`, `deque`, `defaultdict`, or `Decimal` from their standard-library modules for use in supported test expressions
- **THEN** discovery treats those imports as allowed helper declarations rather than executable tests

#### Scenario: Discovery fails
- **WHEN** recursive Python test discovery cannot read or parse a candidate Python file or contains unsupported test constructs
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests where the configured entrypoint is called as a standalone expression statement or as the value of a single-target assignment. A mutation-style entrypoint call MUST be immediately followed by one or more assertion statements with no intervening non-assert statement. Each mutation assertion MUST NOT call the configured entrypoint and MUST reference at least one variable passed directly to the mutation call or directly assigned from the mutation call. A Python test file that uses a mutation-style entrypoint call outside these constraints MUST fail discovery.

#### Scenario: In-place mutation statement is discovered
- **WHEN** a Python test file contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` and then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assertion as one mutation-style test that invokes `sort_colors(a)` before evaluating the assertion

#### Scenario: Mutation assignment is discovered
- **WHEN** a Python test file contains `result = mutate(a)` immediately followed by `assert result == expected`
- **THEN** discovery includes the assertion as one mutation-style test that invokes `mutate(a)` and evaluates the assertion against the assigned `result`

#### Scenario: Multiple immediate mutation assertions are discovered
- **WHEN** a Python test file contains one mutation-style entrypoint call immediately followed by two assertions that each reference a variable passed to the call
- **THEN** discovery includes one mutation-style test for each assertion in source order

#### Scenario: Mutation call without immediate assertion is rejected
- **WHEN** a Python test file contains an entrypoint call as a statement or assignment and the next statement is not an assertion
- **THEN** discovery fails

#### Scenario: Mutation assertion that calls entrypoint is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call followed by an assertion that also calls the configured entrypoint
- **THEN** discovery fails

#### Scenario: Mutation assertion without mutation variable is rejected
- **WHEN** a Python test file contains a mutation-style entrypoint call followed by an assertion that references neither a variable passed to the call nor the variable assigned from the call
- **THEN** discovery fails

### Requirement: Loop-Based Test Parameterization
The system SHALL support loop statements as test constructs in `<tests_dir>/tests.py`. A supported loop statement MUST be reported as a loop test that passes when its body iterates at least once and fails when the loop iterates zero times or cannot be evaluated. Assertions inside executed loop bodies MUST be discovered as per-iteration tests and MUST obey the single-entrypoint-call traceability rule.

#### Scenario: For-in loop reports loop and assertion tests
- **WHEN** `tests.py` contains `cases = [((1, 2), 3), ((2, 3), 5)]` followed by `for args, exp in cases:` with `assert add(*args) == exp` in the loop body
- **THEN** discovery includes a passing loop test for the `for` statement and one assertion test for each executed iteration

#### Scenario: Zero-iteration loop fails without body assertions
- **WHEN** `tests.py` contains `for x in []:` with `assert add(x, x) == 0` in the loop body
- **THEN** `test` prints exactly `{"status":"fail","passed":[],"failed":["tests.py:1"]}` as one stdout line and exits with code 1

#### Scenario: Enumerate loop is supported
- **WHEN** `tests.py` contains `cases = [(1, 2, 3), (4, 5, 9)]` followed by `for _, (a, b, exp) in enumerate(cases):` with `assert add(a, b) == exp` in the loop body
- **THEN** discovery includes a passing loop test and one assertion test for each enumerated case

#### Scenario: Index-based for loop is supported
- **WHEN** `tests.py` contains `cases = [(1, 2, 3), (4, 5, 9)]` followed by `for i in range(len(cases)):` and the body assigns `a, b, exp = cases[i]` before `assert add(a, b) == exp`
- **THEN** discovery includes a passing loop test and one assertion test for each index in the range

#### Scenario: While loop is supported
- **WHEN** `tests.py` contains a finite index-controlled `while` loop over a supported `cases` value and the body asserts the configured entrypoint result
- **THEN** discovery includes a passing loop test and one assertion test for each executed loop iteration

#### Scenario: Nested loops report each loop level
- **WHEN** `tests.py` contains an outer supported loop and an inner supported loop with an assertion in the inner loop body
- **THEN** discovery includes a loop test for the outer loop, a loop test for each executed inner loop instance, and assertion tests for each executed inner iteration

#### Scenario: Multi-call assertion inside nested loops is rejected
- **WHEN** `tests.py` contains nested loops with `assert add(a, b) == add(b, a)` in the inner loop body
- **THEN** discovery fails because the assertion is not traceable to exactly one entrypoint invocation

### Requirement: Raw Output Expectations
The system MUST support raw stdout and stderr expectations immediately preceding a discovered test. The expectation comments MUST use `# expect_stdout: "<python string literal>"` and `# expect_stderr: "<python string literal>"`, and matching MUST compare exact raw text.

#### Scenario: Stdout expectation matches exactly
- **WHEN** a `# expect_stdout: "<python string literal>"` comment immediately precedes a test
- **THEN** the test passes its stdout expectation only if the entrypoint produces exactly that stdout text for the test

#### Scenario: Stderr expectation matches exactly
- **WHEN** a `# expect_stderr: "<python string literal>"` comment immediately precedes a test
- **THEN** the test passes its stderr expectation only if the entrypoint produces exactly that stderr text for the test

#### Scenario: Output expectation does not match
- **WHEN** a raw stdout or stderr expectation is present and the captured output differs by any character
- **THEN** the corresponding test ID appears in `failed`

### Requirement: Test IDs
Each discovered test ID MUST be based on the Python source file path relative to `<tests_dir>` using forward slashes, followed by the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative-path>:<line>`. If multiple non-loop tests originate from the same source path and source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement source path and line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source path, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single test on a root file line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single test on a nested file line
- **WHEN** one test originates from line 5 of `<tests_dir>/subdir/tests.py`
- **THEN** its test ID is `subdir/tests.py:5`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `<tests_dir>/nested/test_foo.py`
- **THEN** their test IDs are `nested/test_foo.py:12#0`, `nested/test_foo.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/nested/tests.py`
- **THEN** the loop test ID is `nested/tests.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/nested/tests.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `nested/tests.py:3:0` and `nested/tests.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop in `<tests_dir>/tests.py` at line 2 executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `tests.py:3:0` and the assertion test ID is `tests.py:4:0:1`

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

### Requirement: Coverage and Execution Outcomes
If tests are discoverable, every discovered test ID MUST appear exactly once in either `passed` or `failed`. Loop statement tests MUST be reported independently from loop-body assertion tests. Assertions inside loop bodies MUST be discovered and reported only for iterations that execute. Tests not executed for any reason after successful discovery MUST be listed in `failed`. If test discovery fails, the output MUST be exactly `{"status":"error","passed":[],"failed":[]}`.

#### Scenario: Every discovered test is reported
- **WHEN** discovery succeeds and three tests are discovered
- **THEN** each of the three test IDs appears exactly once across the `passed` and `failed` arrays

#### Scenario: A discovered test is not executed
- **WHEN** discovery succeeds but a discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Zero-iteration loop body assertions are not reported
- **WHEN** a supported loop statement executes zero iterations and its body contains an assertion
- **THEN** the loop statement test ID appears in `failed` and no assertion test ID from that loop body appears in `passed` or `failed`

#### Scenario: Discovery failure has empty results
- **WHEN** discovery fails before tests can be enumerated
- **THEN** `test` reports `status` as `error` with empty `passed` and `failed` arrays

### Requirement: Test Default Numeric Tolerance
The `test` command SHALL accept an optional `--tol <float>` flag. When provided, the value MUST become the default absolute numeric tolerance for equality and inequality comparisons involving floats or `decimal.Decimal` values, including values nested inside supported containers. When omitted, numeric equality MUST remain exact unless a per-assert tolerance override is present. Invalid tolerance values MUST be treated as a test command error.

#### Scenario: Default tolerance matches nested float values
- **WHEN** `test <solution_path> <tests_dir> --lang python --tol 0.01` runs a discovered assertion comparing `[1.0, {"x": 2.005}]` with `[1.0, {"x": 2.0}]`
- **THEN** the comparison passes because the nested float difference is within the default tolerance

#### Scenario: Omitted default tolerance preserves exact comparison
- **WHEN** `test <solution_path> <tests_dir> --lang python` runs a discovered assertion comparing `1.001` with `1.0` without a per-assert tolerance override
- **THEN** the comparison fails

#### Scenario: Invalid tolerance errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --tol nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Per-Assert Numeric Tolerance Overrides
The system SHALL discover per-assert numeric tolerance overrides using `math.isclose(ENTRYPOINT(args...), expected, abs_tol=..., rel_tol=...)` and `abs(a - b) < tol` or `abs(a - b) <= tol` where one side of `a - b` is the entrypoint call and the other side is a supported numeric expected value. Per-assert tolerance overrides MUST take precedence over the `test --tol` default for that discovered test. `decimal.Decimal` values MUST participate in these numeric tolerance comparisons.

#### Scenario: Math isclose override is discovered
- **WHEN** `tests.py` contains `assert math.isclose(solve(1), 1.01, abs_tol=0.02)`
- **THEN** discovery includes one test that passes when the result is within the assertion's absolute tolerance

#### Scenario: Absolute-difference less-than override is discovered
- **WHEN** `tests.py` contains `assert abs(solve(1) - 1.0) < 0.01`
- **THEN** discovery includes one test that passes only when the absolute difference is less than `0.01`

#### Scenario: Absolute-difference less-than-or-equal override is discovered
- **WHEN** `tests.py` contains `assert abs(Decimal("1.00") - solve(1)) <= Decimal("0.01")`
- **THEN** discovery includes one test that passes when the absolute difference is less than or equal to `Decimal("0.01")`

#### Scenario: Per-assert tolerance overrides default tolerance
- **WHEN** `test <solution_path> <tests_dir> --lang python --tol 0.5` runs `assert math.isclose(solve(1), 1.0, abs_tol=0.01)`
- **THEN** the test uses `0.01` as its absolute tolerance instead of `0.5`

### Requirement: Typed Exception Expectations
The system SHALL support typed exception expectation blocks in addition to raise-any expectation blocks. Typed exception blocks MUST pass only when the entrypoint raises the expected exception type. When the block asserts a substring check against `str(e)` or a regex check using `re.search(pattern, str(e))`, the message matcher MUST also pass.

#### Scenario: Typed exception with substring match is discovered
- **WHEN** `tests.py` contains a `try` block that calls the entrypoint, asserts `False`, and catches `ValueError as e` with `assert "bad" in str(e)`
- **THEN** discovery includes one test that passes only when the entrypoint raises `ValueError` and its message contains `bad`

#### Scenario: Typed exception with regex match is discovered
- **WHEN** `tests.py` imports `re` and catches `ValueError as e` with `assert re.search(r"bad", str(e))`
- **THEN** discovery includes one test that passes only when the entrypoint raises `ValueError` and its message matches the regex

#### Scenario: Wrong exception type fails typed expectation
- **WHEN** a typed exception expectation catches `ValueError` and the entrypoint raises a different exception type
- **THEN** the discovered test ID appears in `failed`

### Requirement: Async Entrypoint Execution
The system SHALL run each target-language entrypoint invocation to completion before evaluating result expressions, mutation assertions, stdout/stderr expectations, or exception expectations. Python awaitables, JavaScript and TypeScript promises, C++ standard future-like results, and Rust future results MUST be completed by the generated harness before comparison. If an async invocation does not complete before the applicable timeout, the discovered test ID MUST appear in `failed`.

#### Scenario: Python async entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang python` runs a discovered test against a Python solution whose entrypoint is an `async def` coroutine function
- **THEN** the Python harness awaits the coroutine result before evaluating the test assertion

#### Scenario: JavaScript promise entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang javascript` runs a discovered test against a JavaScript solution whose entrypoint returns a `Promise`
- **THEN** the JavaScript harness awaits the promise result before evaluating the test assertion

#### Scenario: TypeScript promise entrypoint is awaited
- **WHEN** `test <solution_path> <tests_dir> --lang typescript` runs a discovered test against a TypeScript solution whose entrypoint returns a `Promise`
- **THEN** the TypeScript harness awaits the promise result before evaluating the test assertion

#### Scenario: C++ future entrypoint is completed
- **WHEN** `test <solution_path> <tests_dir> --lang cpp` runs a discovered test against a C++ solution whose entrypoint returns a standard future-like result
- **THEN** the C++ harness completes the future and evaluates the resolved value for the test assertion

#### Scenario: Rust future entrypoint is completed
- **WHEN** `test <solution_path> <tests_dir> --lang rust` runs a discovered test against a Rust solution whose entrypoint returns a future
- **THEN** the Rust harness completes the future and evaluates the resolved value for the test assertion

#### Scenario: Async mutation completes before assertions
- **WHEN** a discovered mutation-style test invokes an async entrypoint and then asserts against a mutated argument or assigned result
- **THEN** the harness waits for the entrypoint invocation to complete before evaluating the mutation assertion

### Requirement: Test Discovery Listing and Selection
The `test` command SHALL accept `--list-tests` and `--run <test_id>` flags. `--list-tests` MUST perform validation and discovery without executing the solution. `--run <test_id>` MUST execute only the discovered test whose ID exactly matches `<test_id>`. Supplying both `--list-tests` and `--run <test_id>` in one invocation MUST be treated as a test command error.

#### Scenario: List tests reports discovered IDs
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked and discovery succeeds
- **THEN** the command prints a single JSON line with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` equal to `[]`, no extra keys, and exits with code 0

#### Scenario: List tests does not execute solution code
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests` is invoked for a solution that would fail or time out if executed and discovery succeeds
- **THEN** the command reports the discovered IDs as passing discovery without invoking the solution entrypoint

#### Scenario: Run selected passing test
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2` is invoked and the discovered test with ID `tests.py:2` passes
- **THEN** the command prints a single JSON line with `status` set to `pass`, `passed` equal to `["tests.py:2"]`, and `failed` equal to `[]`

#### Scenario: Run selected failing test
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:3` is invoked and the discovered test with ID `tests.py:3` fails
- **THEN** the command prints a single JSON line with `status` set to `fail`, `passed` equal to `[]`, `failed` equal to `["tests.py:3"]`, and exits with code 1

#### Scenario: Unknown selected test ID errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --run missing.py:1` is invoked and no discovered test has ID `missing.py:1`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: List and run flags conflict
- **WHEN** `test <solution_path> <tests_dir> --lang python --list-tests --run tests.py:1` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Test Timeout Controls
The `test` command SHALL accept `--timeout-ms <int>` and `--total-timeout-ms <int>` flags. Timeout values MUST be positive integers. `--timeout-ms` MUST bound each selected executable test attempt. `--total-timeout-ms` MUST bound the full selected execution set after discovery and selection. After discovery succeeds, timed-out tests and selected tests not executed because the total timeout elapsed MUST appear in `failed`.

#### Scenario: Per-test timeout fails the timed-out test
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms 10` runs a discovered test whose entrypoint invocation does not complete within 10 milliseconds
- **THEN** that discovered test ID appears in `failed` and the command exits with code 1

#### Scenario: Total timeout fails not-executed selected tests
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 10` discovers three tests and the total timeout elapses before all three tests are executed
- **THEN** every selected discovered test that was not executed because of the elapsed total timeout appears in `failed`

#### Scenario: Selected timeout output contains only selected ID
- **WHEN** `test <solution_path> <tests_dir> --lang python --run tests.py:2 --timeout-ms 10` runs the selected test and it times out
- **THEN** the command prints a single JSON line with `status` set to `fail`, `passed` equal to `[]`, and `failed` equal to `["tests.py:2"]`

#### Scenario: Invalid per-test timeout errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --timeout-ms nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Non-positive total timeout errors
- **WHEN** `test <solution_path> <tests_dir> --lang python --total-timeout-ms 0` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
