# babel-code-goat-cli Specification

## Purpose
TBD - created by archiving change add-babel-code-goat. Update Purpose after archive.
## Requirements
### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, and `typescript` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, or `--lang typescript`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate` or `test` with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

### Requirement: Tester generation
The system SHALL generate exactly one tester file in `<tests_dir>` for the requested language: `tester.py` for Python, `tester.js` for JavaScript, and `tester.ts` for TypeScript. On successful generation the command MUST exit `0`.

#### Scenario: Python tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang python` and generation succeeds
- **THEN** `<tests_dir>/tester.py` exists and the command exits `0`

#### Scenario: JavaScript tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang javascript` and generation succeeds
- **THEN** `<tests_dir>/tester.js` exists and the command exits `0`

#### Scenario: TypeScript tester is generated
- **WHEN** the user runs `generate <tests_dir> --entrypoint solve --lang typescript` and generation succeeds
- **THEN** `<tests_dir>/tester.ts` exists and the command exits `0`

#### Scenario: Failed generation preserves tester files
- **WHEN** the user runs `generate` and generation fails
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, or `tester.ts`

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
The system SHALL recursively discover tests from every `.py` file under `<tests_dir>` using paths relative to `<tests_dir>`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. Discovery MUST fail when recursive scanning finds no tests. Discovery MUST also fail when `<tests_dir>` contains a non-`.py` file whose relative basename matches `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`.

#### Scenario: Root Python test file is discovered
- **WHEN** `<tests_dir>/tests.py` contains a supported test
- **THEN** discovery includes that test

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_sort.py` contains a supported test
- **THEN** discovery includes that test

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

#### Scenario: Test-like non-Python file is a discovery error
- **WHEN** `<tests_dir>` contains `nested/test_sort.txt`
- **THEN** discovery fails

#### Scenario: No recursive tests is a discovery error
- **WHEN** recursive scanning under `<tests_dir>` finds no supported tests
- **THEN** discovery fails

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed assertion forms, supported mutation-style entrypoint call statements and assignments, and supported raise expectation blocks as non-comment code in discovered Python test files. Each allowed assertion, each supported raise expectation block, each supported loop statement, and each mutation follow-up assertion MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

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

#### Scenario: Mutation-style entrypoint statement is accepted
- **WHEN** a discovered Python test file contains `ENTRYPOINT(args...)` immediately followed by a supported mutation follow-up assertion
- **THEN** discovery accepts the entrypoint statement as mutation setup and reports the follow-up assertion as a test

#### Scenario: Mutation-style entrypoint assignment is accepted
- **WHEN** a discovered Python test file contains `result = ENTRYPOINT(args...)` immediately followed by a supported mutation follow-up assertion that references `result`
- **THEN** discovery accepts the assignment as mutation setup and reports the follow-up assertion as a test

#### Scenario: Unsupported code fails discovery
- **WHEN** a discovered Python test file contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Single-call traceable assertions
The system SHALL discover supported non-mutation assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject non-mutation assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls. Mutation follow-up assertions MUST instead satisfy the mutation-style test discovery requirements.

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

#### Scenario: Standalone zero-call assertion fails discovery
- **WHEN** a discovered Python test file contains `assert expected == 3` outside a mutation-style assertion group
- **THEN** discovery fails

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
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-python-path>:<line>` using the Python file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same line outside loop expansion, the system MUST suffix them as `<relative-python-path>:<line>#0`, `<relative-python-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-python-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-python-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that relative Python file.

#### Scenario: Single test ID uses relative file and line
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/nested/test_sort.py`
- **THEN** its ID is `nested/test_sort.py:12`

#### Scenario: Root file ID remains path based
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of `<tests_dir>/nested/test_sort.py` outside loop expansion
- **THEN** their IDs are `nested/test_sort.py:12#0` and `nested/test_sort.py:12#1`

#### Scenario: Loop statement ID uses loop line
- **WHEN** a loop statement originates on line 2 of `<tests_dir>/nested/test_sort.py`
- **THEN** the loop test ID is `nested/test_sort.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `<tests_dir>/nested/test_sort.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_sort.py:3:0` and `nested/test_sort.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `<tests_dir>/nested/test_sort.py`
- **THEN** the assertion test IDs are `nested/test_sort.py:5:0`, `nested/test_sort.py:5:1`, `nested/test_sort.py:5:2`, and `nested/test_sort.py:5:3`

### Requirement: Allowed values and equality
The system SHALL support `None`, booleans, integers, floats, strings, lists, tuples, dictionaries with any supported key type, sets, frozensets, `collections.Counter`, `collections.deque`, `collections.defaultdict`, and `decimal.Decimal` as allowed argument and expected values. Nested allowed values MUST be supported. Equality and inequality checks MUST use deep structural comparison for nested containers according to each container's meaning.

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
- **WHEN** a discovered Python test file cannot be parsed or contains unsupported constructs
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Test-like non-Python file produces discovery error
- **WHEN** `<tests_dir>` contains a non-`.py` file with a test-like basename
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: No discovered tests produces discovery error
- **WHEN** recursive discovery finds no tests under `<tests_dir>`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Solution callable forms
The system SHALL test code written in the same language as the selected tester. The callable under test MUST be accepted when it is either a callable named by the inferred entrypoint or a no-argument constructible class with a callable method or static method of that name.

#### Scenario: Top-level callable is used
- **WHEN** the solution exposes a callable with the inferred entrypoint name
- **THEN** the tester invokes that callable for discovered tests

#### Scenario: No-argument class method is used
- **WHEN** the solution exposes a no-argument constructible class with a callable method matching the inferred entrypoint name
- **THEN** the tester constructs the class and invokes that method for discovered tests

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

### Requirement: Mutation-style test discovery
The system SHALL support mutation-style tests where a configured entrypoint call appears as either a standalone expression statement or an assignment statement and is immediately followed by one or more assertions that do not call the entrypoint. The system MUST execute the mutation call once before evaluating each associated follow-up assertion group. Each mutation follow-up assertion MUST reference at least one variable passed to the mutation call or one variable directly assigned from the mutation call. Discovery MUST fail when a mutation-style pattern is separated from its follow-up assertions by any non-assert statement, when a follow-up assertion calls the entrypoint, or when a follow-up assertion does not reference a mutation-related variable.

#### Scenario: Standalone mutation call is discovered
- **WHEN** a discovered Python test file contains `a = [2, 0, 1]`, then `sort_colors(a)`, then `assert a == [0, 1, 2]`
- **THEN** discovery creates a mutation-style test that invokes `sort_colors(a)` once and evaluates the assertion against the mutated `a`

#### Scenario: Assignment mutation result is discovered
- **WHEN** a discovered Python test file contains `result = normalize(items)` followed immediately by `assert result == expected`
- **THEN** discovery creates a mutation-style test that invokes `normalize(items)` once and evaluates the assertion against `result`

#### Scenario: Multiple immediate mutation assertions are discovered
- **WHEN** a mutation call is immediately followed by two assertions and both assertions reference a mutation-related variable
- **THEN** each follow-up assertion is discovered as a separate test associated with the same mutation call

#### Scenario: Separated mutation assertion fails discovery
- **WHEN** an entrypoint call statement is followed by a non-assert statement before an assertion that inspects the mutated variable
- **THEN** discovery fails

#### Scenario: Mutation follow-up entrypoint call fails discovery
- **WHEN** a mutation follow-up assertion calls the configured entrypoint again
- **THEN** discovery fails

#### Scenario: Unrelated mutation follow-up assertion fails discovery
- **WHEN** a mutation follow-up assertion does not reference any variable passed to the mutation call or directly assigned from it
- **THEN** discovery fails

