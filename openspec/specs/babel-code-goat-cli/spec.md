# babel-code-goat-cli Specification

## Purpose
TBD - created by archiving change add-babel-code-goat. Update Purpose after archive.
## Requirements
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

### Requirement: Test output and exit codes
The `test` command SHALL print exactly one line to stdout containing a JSON object with only the keys `status`, `passed`, and `failed`. The `status` value MUST be `pass`, `fail`, or `error`. The command MUST exit `0` for `pass`, `1` for `fail`, and `2` for `error`.

#### Scenario: Passing run reports pass
- **WHEN** every discovered test passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, all test IDs in `passed`, no test IDs in `failed`, and no extra keys

#### Scenario: Failing run reports fail
- **WHEN** at least one discovered test fails and no harness error prevents reporting
- **THEN** stdout contains one JSON line with `status` set to `fail`, passing test IDs in `passed`, failing test IDs in `failed`, and the command exits `1`

#### Scenario: Error run reports error
- **WHEN** discovery fails or a required test precondition is not met
- **THEN** stdout contains one JSON line with `status` set to `error`, empty `passed` and `failed` arrays, and the command exits `2`

### Requirement: Test discovery source
The system SHALL discover tests from any `.py` file under `<tests_dir>` recursively. Non-`.py` files under `<tests_dir>` whose names match test-like patterns MUST be discovery errors. Test-like patterns are `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, and `*_tests.<ext>`, where `<ext>` is any extension other than `py`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. If no tests are discovered recursively under `<tests_dir>`, discovery MUST fail.

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_cases.py` contains a supported assertion and no root `tests.py` exists
- **THEN** the assertion is discovered as a test

#### Scenario: Root tests file remains valid
- **WHEN** `<tests_dir>/tests.py` contains a supported assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

#### Scenario: Non-Python test-like file is rejected
- **WHEN** `<tests_dir>/nested/test_cases.txt` exists
- **THEN** discovery fails

#### Scenario: Empty recursive discovery is an error
- **WHEN** no supported tests are discovered in any `.py` file under `<tests_dir>`
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed direct-call assertion forms, constrained mutation-style entrypoint call statements or assignments, mutation-style assertions immediately following those calls, and supported raise expectation blocks as non-comment code in discovered Python test files. Each allowed direct-call assertion, each mutation-style assertion, each supported raise expectation block, and each supported loop statement MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

#### Scenario: Equality assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...) == expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Inequality assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...) != expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Truthy assertion is discovered
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Falsy assertion is discovered
- **WHEN** a discovered Python test file contains `assert not ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Raise-any block is discovered
- **WHEN** a discovered Python test file contains a `try` block that calls the entrypoint, then asserts `False`, and catches `Exception` with `pass`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed raise block is discovered
- **WHEN** a discovered Python test file contains a `try` block that calls the entrypoint, then asserts `False`, and catches a specific exception type such as `ValueError`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception matching that type

#### Scenario: Typed raise block with substring message check is discovered
- **WHEN** a discovered Python test file contains a typed exception handler that asserts a string literal is contained in `str(e)`
- **THEN** the block is discovered as one test that also requires the raised exception message to contain that substring

#### Scenario: Typed raise block with regex message check is discovered
- **WHEN** a discovered Python test file contains a typed exception handler that asserts `re.search(<pattern>, str(e))`
- **THEN** the block is discovered as one test that also requires the raised exception message to match that regex pattern

#### Scenario: Math isclose assertion is discovered
- **WHEN** a discovered Python test file contains `assert math.isclose(ENTRYPOINT(args...), expected, abs_tol=abs_tol, rel_tol=rel_tol)`
- **THEN** the assertion is discovered as one test with per-assert absolute and relative tolerance metadata

#### Scenario: Absolute difference tolerance assertion is discovered
- **WHEN** a discovered Python test file contains `assert abs(ENTRYPOINT(args...) - expected) < tol` or `assert abs(ENTRYPOINT(args...) - expected) <= tol`
- **THEN** the assertion is discovered as one test with a per-assert absolute tolerance and strictness metadata

#### Scenario: Literal assignment for parameterization is accepted
- **WHEN** a discovered Python test file contains a simple assignment such as `cases = [((1, 2), 3)]` used by a supported loop
- **THEN** discovery accepts the assignment as parameterization data and does not report the assignment itself as a test

#### Scenario: For loop is discovered
- **WHEN** a discovered Python test file contains a supported `for ... in ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: While loop is discovered
- **WHEN** a discovered Python test file contains a supported `while ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: Mutation call statement is discovered
- **WHEN** a discovered Python test file contains an entrypoint call statement immediately followed by a valid mutation-style assertion
- **THEN** the mutation-style assertion is discovered as one test

#### Scenario: Mutation assignment is discovered
- **WHEN** a discovered Python test file contains an assignment from an entrypoint call immediately followed by a valid mutation-style assertion
- **THEN** the mutation-style assertion is discovered as one test

#### Scenario: Unsupported code fails discovery
- **WHEN** a discovered Python test file contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Single-call traceable assertions
The system SHALL discover supported direct-call assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject direct-call assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls. Mutation-style assertions are governed by the mutation-style requirements.

#### Scenario: Entrypoint call on right side is discovered
- **WHEN** a discovered Python test file contains `assert 3 == ENTRYPOINT(1, 2)`
- **THEN** the assertion is discovered as one test traceable to the single `ENTRYPOINT(1, 2)` invocation

#### Scenario: Multiple entrypoint calls fail discovery
- **WHEN** a discovered Python test file contains `assert ENTRYPOINT(1) == ENTRYPOINT(2)`
- **THEN** discovery fails

#### Scenario: Unsupported helper call fails discovery
- **WHEN** a discovered Python test file contains `assert normalize(ENTRYPOINT(1)) == 1`
- **THEN** discovery fails

#### Scenario: Tolerance helper remains traceable
- **WHEN** a discovered Python test file contains `assert math.isclose(ENTRYPOINT("near"), 1.0, abs_tol=0.01)`
- **THEN** the assertion is discovered as one test with per-assert tolerance metadata traceable to the single entrypoint invocation

### Requirement: Primitive operation assertions
The system SHALL support primitive operations over supported numbers, strings, and containers inside discovered assertion expressions when those expressions contain exactly one configured entrypoint invocation. Primitive operations MUST be evaluated by generated testers as part of the same discovered test and MUST NOT require a second entrypoint invocation.

#### Scenario: Membership assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(1, 2) in [1, 2, 3]`
- **THEN** the assertion is discovered as one test that passes only when the single entrypoint result is a member of the expected container

#### Scenario: Primitive wrapper assertion is discovered
- **WHEN** `tests.py` contains `assert sorted(ENTRYPOINT([3, 1, 2])) == [1, 2, 3]`
- **THEN** the assertion is discovered as one test that invokes the entrypoint once and compares the sorted primitive result to the expected list

#### Scenario: Primitive numeric expression is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(2) + 1 == 4`
- **THEN** the assertion is discovered as one test that applies the primitive numeric operation to the single entrypoint result

#### Scenario: Primitive container expression preserves structural comparison
- **WHEN** `tests.py` contains `assert ENTRYPOINT("items")[0] == "first"`
- **THEN** the assertion is discovered as one test that applies the primitive container access to the single entrypoint result before comparison

### Requirement: Test IDs
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-path>:<line>` using the test file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same relative path and line outside loop expansion, the system MUST suffix them as `<relative-path>:<line>#0`, `<relative-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that relative path.

#### Scenario: Single test ID uses relative path and line
- **WHEN** one non-loop test originates on line 12 of `nested/test_foo.py`
- **THEN** its ID is `nested/test_foo.py:12`

#### Scenario: Root tests file ID remains familiar
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of `nested/test_foo.py` outside loop expansion
- **THEN** their IDs are `nested/test_foo.py:12#0` and `nested/test_foo.py:12#1`

#### Scenario: Loop statement ID uses relative path and loop line
- **WHEN** a loop statement originates on line 2 of `nested/test_foo.py`
- **THEN** the loop test ID is `nested/test_foo.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `nested/test_foo.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_foo.py:3:0` and `nested/test_foo.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `nested/test_foo.py`
- **THEN** the assertion test IDs are `nested/test_foo.py:5:0`, `nested/test_foo.py:5:1`, `nested/test_foo.py:5:2`, and `nested/test_foo.py:5:3`

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

### Requirement: Tolerance-aware numeric comparisons
The system SHALL apply the `test --tol <float>` default tolerance to equality and inequality comparisons where both compared values are numeric or nested numeric values. Per-assert tolerance overrides from `math.isclose(...)` and supported `abs(a - b)` assertions MUST override the default tolerance for that assertion.

#### Scenario: Default tolerance applies to nested floats
- **WHEN** a discovered equality assertion compares nested containers that contain floats differing by no more than the `--tol` value
- **THEN** the test passes for those numeric leaves

#### Scenario: Default tolerance does not change nonnumeric equality
- **WHEN** a discovered equality assertion compares strings, booleans, or container structure
- **THEN** the test uses exact structural semantics for those nonnumeric values

#### Scenario: Math isclose overrides default tolerance
- **WHEN** a discovered `math.isclose` assertion specifies `abs_tol` or `rel_tol`
- **THEN** the test uses those per-assert tolerances instead of the `--tol` default

#### Scenario: Absolute difference strictness is preserved
- **WHEN** a discovered absolute-difference assertion uses `< tol`
- **THEN** a difference exactly equal to `tol` fails

#### Scenario: Absolute difference inclusive comparison is preserved
- **WHEN** a discovered absolute-difference assertion uses `<= tol`
- **THEN** a difference exactly equal to `tol` passes

### Requirement: Typed raise and message matching
The system SHALL support raise expectation blocks that require a specific exception type and optionally require the raised exception message to contain a substring or match a regex. Raise expectation blocks without a specific type MUST continue to pass when any exception is raised.

#### Scenario: Typed exception match passes
- **WHEN** a discovered typed raise expectation catches `ValueError` and the entrypoint raises `ValueError`
- **THEN** the test passes

#### Scenario: Wrong exception type fails
- **WHEN** a discovered typed raise expectation catches `ValueError` and the entrypoint raises `TypeError`
- **THEN** the test fails

#### Scenario: Message substring match passes
- **WHEN** a discovered typed raise expectation asserts `"bad" in str(e)` and the raised exception message contains `bad`
- **THEN** the test passes the message check

#### Scenario: Message substring mismatch fails
- **WHEN** a discovered typed raise expectation asserts `"bad" in str(e)` and the raised exception message does not contain `bad`
- **THEN** the test fails

#### Scenario: Regex message match passes
- **WHEN** a discovered typed raise expectation asserts `re.search(r"bad", str(e))` and the raised exception message matches the pattern
- **THEN** the test passes the message check

#### Scenario: Regex message mismatch fails
- **WHEN** a discovered typed raise expectation asserts `re.search(r"bad", str(e))` and the raised exception message does not match the pattern
- **THEN** the test fails

### Requirement: Stdout and stderr expectations
The system SHALL support raw stdout and stderr expectations from comments immediately preceding a test: `# expect_stdout: "<python string literal>"` and `# expect_stderr: "<python string literal>"`. Matching MUST compare exact raw text.

#### Scenario: Stdout expectation matches exactly
- **WHEN** an `expect_stdout` comment immediately precedes a test and the entrypoint writes exactly that text to stdout
- **THEN** the stdout expectation passes

#### Scenario: Stderr expectation mismatch fails test
- **WHEN** an `expect_stderr` comment immediately precedes a test and the entrypoint writes different text to stderr
- **THEN** the test appears in `failed`

### Requirement: Result coverage accounting
When tests are discoverable, the system SHALL place every discovered test ID exactly once in either `passed` or `failed`. Any discovered test that is not executed for any reason MUST be listed in `failed`.

#### Scenario: Unexecuted discovered test is failed
- **WHEN** discovery succeeds but a discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Every discovered ID is reported once
- **WHEN** discovery succeeds and the run completes
- **THEN** each discovered test ID appears exactly once across the `passed` and `failed` arrays

### Requirement: Discovery failure output
If test discovery fails, the system SHALL output exactly `{"status":"error","passed":[],"failed":[]}` and exit with status code `2`.

#### Scenario: Malformed tests produce discovery error
- **WHEN** `tests.py` cannot be parsed or contains unsupported constructs
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

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

### Requirement: Loop statement tests
The system SHALL treat each supported `for` and `while` loop statement as a test. A loop test MUST pass when the loop body executes at least once. A loop test MUST fail when the loop iterates zero times or cannot be evaluated safely. A failing loop test MUST use normal failing test result semantics: `status` is `fail`, the loop test ID appears in `failed`, and the command exits `1` unless another error condition takes precedence.

#### Scenario: Non-empty for loop passes
- **WHEN** `tests.py` contains `for args, exp in [((1, 2), 3)]:` with a supported loop body
- **THEN** the loop statement test passes because the body executes at least once

#### Scenario: Empty for loop fails
- **WHEN** `tests.py` contains `for x in []:` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Zero range loop fails
- **WHEN** `tests.py` contains `for i in range(0):` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Empty string loop fails
- **WHEN** `tests.py` contains `for ch in "":` with a supported loop body
- **THEN** the loop statement test fails and no tests from the body are reported

#### Scenario: Unsupported loop evaluation fails loop test
- **WHEN** a loop iterable or `while` condition cannot be evaluated using the supported parameterization subset
- **THEN** the loop statement test fails and tests from the body are not reported

### Requirement: Loop parameterization patterns
The system SHALL support common Python iteration patterns for parameterized tests, including direct iteration over supported literal containers or strings, `enumerate(...)`, index-based `range(len(...))`, and `while` loops controlled by supported variables and primitive updates.

#### Scenario: Direct tuple unpacking loop expands assertions
- **WHEN** `tests.py` contains `for a, b in [(1, 2), (3, 4)]:` and a supported assertion in the loop body
- **THEN** the loop test is reported and the body assertion is reported once per iteration using the values from that iteration

#### Scenario: Enumerate loop expands assertions
- **WHEN** `tests.py` contains `for _, (a, b, exp) in enumerate(cases):` and a supported assertion in the loop body
- **THEN** the loop test is reported and the body assertion is reported once per enumerated case

#### Scenario: Index-based range loop expands assertions
- **WHEN** `tests.py` contains `for i in range(len(cases)):` and uses `cases[i]` in a supported assertion
- **THEN** the loop test is reported and the body assertion is reported once per index

#### Scenario: While loop expands assertions
- **WHEN** `tests.py` contains a supported `while i < len(cases):` loop whose body advances `i`
- **THEN** the loop test is reported and the body assertion is reported once per loop iteration

#### Scenario: Nested loop levels are separate loop tests
- **WHEN** `tests.py` contains a supported loop nested inside another supported loop
- **THEN** each loop statement is reported as its own loop test and assertions in the nested body are reported per executed inner iteration

### Requirement: Loop body traceability
The system SHALL apply existing single-call traceability rules to every assertion executed inside a loop body. Each loop body assertion MUST trace to exactly one configured entrypoint invocation after loop variables are resolved. Discovery MUST fail when a loop body assertion contains zero configured entrypoint invocations, more than one configured entrypoint invocation, or an unsupported non-primitive helper call.

#### Scenario: Single-call loop body assertion is discovered
- **WHEN** `tests.py` contains a supported loop whose body contains `assert add(a, b) == exp`
- **THEN** each executed assertion is discovered as a test traceable to exactly one `add(a, b)` invocation

#### Scenario: Multiple entrypoint calls in loop body fail discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert add(a, b) == add(b, a)`
- **THEN** discovery fails

#### Scenario: Zero entrypoint calls in loop body fail discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert exp == 3`
- **THEN** discovery fails

#### Scenario: Unsupported helper call in loop body fails discovery
- **WHEN** `tests.py` contains a supported loop whose body contains `assert normalize(add(a, b)) == exp`
- **THEN** discovery fails

### Requirement: Mutation-style tests
The system SHALL support mutation-style tests when an entrypoint call is a standalone expression statement or the value of an assignment, and that statement is immediately followed by one or more assertion statements with no intervening non-assert statement. Each mutation-style assertion MUST contain zero configured entrypoint calls and MUST reference at least one variable passed to the mutation call or directly assigned from the mutation call. Files that use mutation-style patterns outside these constraints MUST fail discovery.

#### Scenario: Standalone mutation call with mutated argument assertion is discovered
- **WHEN** a discovered Python test file contains `items = [2, 0, 1]`, followed by `ENTRYPOINT(items)`, followed immediately by `assert items == [0, 1, 2]`
- **THEN** the assertion is discovered as one mutation-style test that invokes the entrypoint once before evaluating the assertion

#### Scenario: Assigned mutation result assertion is discovered
- **WHEN** a discovered Python test file contains `items = [2, 0, 1]`, followed by `result = ENTRYPOINT(items)`, followed immediately by `assert result is None` or `assert items == [0, 1, 2]`
- **THEN** each immediate assertion that references `result` or `items` is discovered as one mutation-style test

#### Scenario: Multiple immediate mutation assertions share one call
- **WHEN** a discovered Python test file contains a valid mutation call followed immediately by two valid assertions that reference variables tied to that call
- **THEN** both assertions are discovered as mutation-style tests that execute after a single entrypoint invocation for the group

#### Scenario: Mutation call without following assertion is rejected
- **WHEN** a discovered Python test file contains a standalone entrypoint call statement that is not immediately followed by an assertion
- **THEN** discovery fails

#### Scenario: Intervening statement breaks mutation group
- **WHEN** a discovered Python test file contains an entrypoint mutation call, then any non-assert statement, then an assertion about the mutated variable
- **THEN** discovery fails

#### Scenario: Mutation assertion must reference related variable
- **WHEN** a discovered Python test file contains an entrypoint mutation call followed by `assert expected == [0, 1, 2]`
- **THEN** discovery fails because the assertion does not reference a variable passed to or assigned from the mutation call

#### Scenario: Mutation assertion cannot call entrypoint
- **WHEN** a discovered Python test file contains an entrypoint mutation call followed by `assert ENTRYPOINT(items) == [0, 1, 2]`
- **THEN** discovery fails

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

### Requirement: Async entrypoint completion
The system SHALL run awaitable or async-like entrypoint invocations to completion before evaluating the discovered test outcome for every supported target language. If async completion does not finish before an applicable timeout, the affected test MUST be reported as failed rather than passed.

#### Scenario: Python coroutine result is awaited
- **WHEN** a Python solution exposes an `async def` entrypoint and the user runs `test <solution_path> <tests_dir> --lang python`
- **THEN** each selected test awaits the coroutine result before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: JavaScript promise result is awaited
- **WHEN** a JavaScript solution entrypoint returns a Promise and the user runs `test <solution_path> <tests_dir> --lang javascript`
- **THEN** each selected test awaits the Promise before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: TypeScript promise result is awaited
- **WHEN** a TypeScript solution entrypoint returns a Promise and the user runs `test <solution_path> <tests_dir> --lang typescript`
- **THEN** each selected test awaits the Promise before applying comparisons, stream expectations, or raise expectation checks

#### Scenario: C++ future result is completed
- **WHEN** a C++ solution entrypoint returns a standard future-like result and the user runs `test <solution_path> <tests_dir> --lang cpp`
- **THEN** each selected test waits for the future result before applying comparisons, stream expectations, or exception expectation checks

#### Scenario: Rust future result is completed
- **WHEN** a Rust solution entrypoint returns a future and the user runs `test <solution_path> <tests_dir> --lang rust`
- **THEN** each selected test drives the future to completion before applying comparisons, stream expectations, or panic expectation checks

### Requirement: Test listing
The `test` command SHALL accept `--list-tests`. When discovery and tester payload revalidation succeed, `--list-tests` MUST output a pass result with every discovered test ID in `passed`, an empty `failed` array, and no solution entrypoint execution.

#### Scenario: List tests reports discovered IDs
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery succeeds for tests with IDs `tests.py:1` and `tests.py:2`
- **THEN** stdout contains exactly one JSON line with `status` set to `pass`, `passed` set to `["tests.py:1","tests.py:2"]`, and `failed` set to `[]`

#### Scenario: List tests does not execute solution
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript --list-tests` with a solution whose entrypoint would fail if called
- **THEN** the command reports discovered IDs as passing without invoking the solution entrypoint

#### Scenario: List tests preserves discovery errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery fails
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Single test selection
The `test` command SHALL accept `--run <test_id>`. When a discovered ID is selected, only that selected ID MUST appear in `passed` or `failed`; no unselected discovered IDs may appear in the result.

#### Scenario: Selected passing test is the only reported ID
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:1` and `tests.py:1` passes while other tests are discoverable
- **THEN** stdout contains exactly one JSON line with `status` set to `pass`, `passed` set to `["tests.py:1"]`, and `failed` set to `[]`

#### Scenario: Selected failing test is the only reported ID
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2` and `tests.py:2` fails while other tests are discoverable
- **THEN** stdout contains exactly one JSON line with `status` set to `fail`, `passed` set to `[]`, and `failed` set to `["tests.py:2"]`

#### Scenario: Unknown selected test is an error
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run missing.py:1` and no discovered test has ID `missing.py:1`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Test execution timeouts
The `test` command SHALL accept `--timeout-ms <int>` to bound each executed test and `--total-timeout-ms <int>` to bound the selected run. Timed-out tests and selected tests that are not executed before the total timeout expires MUST appear in `failed`.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 10` and one selected test does not complete within 10 milliseconds
- **THEN** that test ID appears in `failed` and the command reports `status` as `fail`

#### Scenario: Per-test timeout continues reporting completed tests
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang javascript --timeout-ms 50` and one selected test passes before the timeout while another selected test times out
- **THEN** the completed passing test ID appears in `passed` and the timed-out test ID appears in `failed`

#### Scenario: Total timeout fails not-executed selected tests
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --total-timeout-ms 50` and the total timeout expires before all selected tests execute
- **THEN** every selected test ID that did not execute before the timeout appears in `failed`

#### Scenario: Run selection limits timeout reporting
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2 --timeout-ms 10` and the selected test times out while other tests are discoverable
- **THEN** only `tests.py:2` appears in `failed`

#### Scenario: Timeout result preserves JSON contract
- **WHEN** a selected run times out after discovery succeeds
- **THEN** stdout contains exactly one JSON object with only the keys `status`, `passed`, and `failed`
