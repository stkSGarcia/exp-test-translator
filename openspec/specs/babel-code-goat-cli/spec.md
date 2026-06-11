## Purpose

Defines the Babel Code Goat CLI contract for generating language-specific tester files and running translated tests from a constrained Python test-source format.
## Requirements
### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, and `typescript` as target languages.

#### Scenario: Generate accepts a supported language
- **WHEN** `generate` is invoked with an existing tests directory, a valid entrypoint, and `--lang python`, `--lang javascript`, or `--lang typescript`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, or `tester.ts`

#### Scenario: Test rejects an unsupported language
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Tester File Generation
The system SHALL write the expected tester file in `<tests_dir>` when `generate` succeeds. The expected tester filename MUST be `tester.py` for `python`, `tester.js` for `javascript`, and `tester.ts` for `typescript`.

#### Scenario: Generate writes a Python tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` succeeds
- **THEN** `<tests_dir>/tester.py` exists and the command exits with code 0

#### Scenario: Generate writes a JavaScript tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang javascript` succeeds
- **THEN** `<tests_dir>/tester.js` exists and the command exits with code 0

#### Scenario: Generate writes a TypeScript tester
- **WHEN** `generate <tests_dir> --entrypoint solve --lang typescript` succeeds
- **THEN** `<tests_dir>/tester.ts` exists and the command exits with code 0

### Requirement: Generation Failure Preserves Tester Files
The system MUST NOT create or modify `tester.py`, `tester.js`, or `tester.ts` when `generate` fails for any reason.

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

#### Scenario: Existing tester is preserved during test
- **WHEN** `test` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

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

### Requirement: Mutation-Style Test Discovery
The system SHALL support mutation-style tests when an entrypoint call appears as a standalone statement or as a single-variable assignment and is immediately followed by one or more assert statements in the same statement body. The mutation call MUST be the entrypoint invocation used by each following mutation assert. Each following mutation assert MUST NOT contain an entrypoint call and MUST reference at least one direct variable passed to the mutation call or the variable directly assigned from the mutation call. If a file uses mutation-style entrypoint calls outside these constraints, discovery MUST fail.

#### Scenario: Standalone mutation call is discovered
- **WHEN** a Python test source contains `a = [2, 0, 2, 1, 1, 0]` followed by `sort_colors(a)` followed immediately by `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery includes the assert as one test that invokes `sort_colors` with the initial value of `a` and evaluates the assertion against the mutated argument

#### Scenario: Assignment mutation call is discovered
- **WHEN** a Python test source contains `a = [3, 1, 2]` followed by `result = normalize(a)` followed immediately by `assert result == [1, 2, 3]`
- **THEN** discovery includes the assert as one test that invokes `normalize` with the initial value of `a` and evaluates the assertion against the assigned result

#### Scenario: Multiple immediate mutation asserts are discovered
- **WHEN** a Python test source contains an entrypoint mutation call immediately followed by two assert statements, and each assert references a mutation argument variable or the assigned result variable
- **THEN** discovery includes one test for each assert in source order

#### Scenario: Mutation assert cannot call entrypoint
- **WHEN** a Python test source contains `sort_colors(a)` immediately followed by `assert sort_colors(a) is None`
- **THEN** discovery fails because the mutation assert contains an entrypoint call

#### Scenario: Mutation assert must reference mutation variable
- **WHEN** a Python test source contains `sort_colors(a)` immediately followed by `assert expected == [0, 1, 2]`
- **THEN** discovery fails because the assert does not reference a variable passed to or directly assigned from the mutation call

#### Scenario: Mutation call requires immediate assert
- **WHEN** a Python test source contains an entrypoint call statement or assignment that is not immediately followed by at least one assert statement
- **THEN** discovery fails

### Requirement: Test Discovery Source and Allowed Constructs
The system SHALL discover tests from all `.py` files under `<tests_dir>` recursively. Assertions inside functions MUST count as tests even when the function is not called. The system MUST support allowed non-comment code at any scope consisting of `def ...:` blocks, restricted helper imports for supported test expressions, supported parameter source assignments, supported loop statements, allowed assertions, constrained mutation-style entrypoint call groups, raise-any expectation blocks, and typed exception expectation blocks. Each discovered assertion or expectation block MUST be traceable to exactly one invocation of the configured entrypoint. Assertion expressions MUST NOT depend on more than one configured entrypoint invocation or on unsupported function calls; primitive operations over numbers, strings, and containers are allowed only when they preserve the single-entrypoint trace. The system MUST report a discovery error for non-`.py` files under `<tests_dir>` whose stem matches `test*`, `*_test`, `tests`, or `*_tests`, except for generated tester artifacts named `tester.js` or `tester.ts`.

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
- **WHEN** `<tests_dir>` contains the generated `tester.js` or `tester.ts` file and otherwise contains discoverable Python tests
- **THEN** discovery ignores the generated tester file and succeeds

#### Scenario: No discovered tests is rejected
- **WHEN** recursive discovery under `<tests_dir>` finds no tests
- **THEN** discovery fails

#### Scenario: Discovery fails
- **WHEN** a Python test source cannot be read, cannot be parsed, contains unsupported test constructs, or a non-`.py` test-like file is present under `<tests_dir>`
- **THEN** `test` prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Loop-Based Test Parameterization
The system SHALL support loop statements as test constructs in Python test sources under `<tests_dir>`. A supported loop statement MUST be reported as a loop test that passes when its body iterates at least once and fails when the loop iterates zero times or cannot be evaluated. Assertions inside executed loop bodies MUST be discovered as per-iteration tests and MUST obey the single-entrypoint-call traceability rule.

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
Each discovered test ID MUST be based on the forward-slash relative source path from `<tests_dir>` followed by the 1-based source line where the test originates. Non-loop tests MUST use the format `<relative-path>:<line>`. If multiple non-loop tests originate from the same source path and source line, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes so each ID is unique. Loop statement tests MUST use the loop statement line, appending any active outer iteration path for nested loop instances. Assertions inside loops MUST append zero-based iteration indexes after the assertion line using `<relative-path>:<line>:<index>` for a single loop and `<relative-path>:<line>:<outer-index>:<inner-index>` for nested loops. If multiple tests share the same source path, source line, and iteration path, IDs MUST append `#0`, `#1`, and subsequent zero-based suffixes.

#### Scenario: Single root test on a line
- **WHEN** one test originates from line 12 of `<tests_dir>/tests.py`
- **THEN** its test ID is `tests.py:12`

#### Scenario: Single nested test on a line
- **WHEN** one test originates from line 10 of `<tests_dir>/nested/test_foo.py`
- **THEN** its test ID is `nested/test_foo.py:10`

#### Scenario: Multiple tests on one line
- **WHEN** multiple tests originate from line 12 of `tests.py`
- **THEN** their test IDs are `tests.py:12#0`, `tests.py:12#1`, and so on in discovery order

#### Scenario: Loop statement test ID
- **WHEN** a supported top-level `for` statement originates from line 2 of `<tests_dir>/cases/test_loop.py`
- **THEN** the loop test ID is `cases/test_loop.py:2`

#### Scenario: Loop body assertion test IDs
- **WHEN** a supported top-level loop in `<tests_dir>/cases/test_loop.py` executes two iterations and an assertion in its body originates from line 3
- **THEN** the assertion test IDs are `cases/test_loop.py:3:0` and `cases/test_loop.py:3:1` in iteration order

#### Scenario: Nested loop test IDs
- **WHEN** a supported outer loop at line 2 of `<tests_dir>/nested/tests.py` executes and an inner loop at line 3 executes during outer iteration 0 with an assertion at line 4 during inner iteration 1
- **THEN** the inner loop test ID is `nested/tests.py:3:0` and the assertion test ID is `nested/tests.py:4:0:1`

### Requirement: Allowed Values and Equality
The system MUST support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported hashable key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as arguments and expected values, including nested containers where the Python type allows nesting. Equality and inequality MUST use deep structural or container-semantic comparison for nested containers. Numeric comparison MUST apply the effective tolerance to floats and `decimal.Decimal` values where tolerance is applicable.

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

#### Scenario: Unsupported literal value
- **WHEN** a test argument or expected value uses a value outside the allowed set or uses an unhashable dictionary key
- **THEN** discovery fails

### Requirement: Solution Callable Resolution
The code under test MUST be in the same language as the generated tester. The system SHALL call the inferred entrypoint when it is available as a callable named by the entrypoint, as a method with that name on a class constructible with no arguments, or as a static method with that name.

#### Scenario: Callable function is used
- **WHEN** the solution defines a callable named by the inferred entrypoint
- **THEN** the system invokes that callable for each discovered test

#### Scenario: No-argument class method is used
- **WHEN** the solution defines a class constructible with no arguments and that class has a callable method named by the inferred entrypoint
- **THEN** the system constructs the class and invokes the method for each discovered test

#### Scenario: Static method is used
- **WHEN** the solution defines a class with a callable static method named by the inferred entrypoint
- **THEN** the system invokes the static method for each discovered test

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
