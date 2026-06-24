# babel-code-goat-cli Specification

## Purpose
TBD - created by archiving change add-babel-code-goat. Update Purpose after archive.
## Requirements
### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable. The `test` command MUST accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`. The `profile` command MUST accept `-n <trials>`, `--warmup <k>`, `--memory`, `--tol <float>`, `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate`, `test`, or `profile` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Test accepts discovery listing
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests`
- **THEN** the command uses discovery-listing behavior instead of executing the solution

#### Scenario: Test accepts single test selection
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2`
- **THEN** the command limits execution and reporting to the discovered test with ID `tests.py:2`

#### Scenario: Test accepts timeout controls
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 100 --total-timeout-ms 500`
- **THEN** the command applies the requested per-test and total-run timeout limits

#### Scenario: Profile accepts supported language
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command profiles the selected solution with the generated tester for that language

#### Scenario: Profile accepts default tolerance
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Profile accepts discovery listing
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests`
- **THEN** the command uses discovery-listing behavior instead of executing the solution for profiling

#### Scenario: Profile accepts single test selection
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:2`
- **THEN** the command limits profiling and reporting to the discovered test with ID `tests.py:2`

#### Scenario: Profile accepts timeout controls
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 100 --total-timeout-ms 500`
- **THEN** the command applies the requested per-test and total-run timeout limits during profiling

#### Scenario: Profile accepts trial and warmup controls
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 5 --warmup 2`
- **THEN** the command executes warmup runs and measured trials using those counts

#### Scenario: Profile accepts memory measurement
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory`
- **THEN** the command includes memory measurement in the profiling result

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
The system SHALL discover tests from any `.py` file under `<tests_dir>` recursively. Discovery MUST reject non-`.py` files under `<tests_dir>` whose file names match test-like patterns `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called. If recursive discovery finds no tests, discovery MUST fail.

#### Scenario: Root tests file is discovered
- **WHEN** `<tests_dir>/tests.py` contains an allowed assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Nested Python test file is discovered
- **WHEN** `<tests_dir>/nested/test_cases.py` contains an allowed assertion
- **THEN** the assertion is discovered as a test

#### Scenario: Multiple Python files are discovered recursively
- **WHEN** `<tests_dir>/tests.py` and `<tests_dir>/nested/more_tests.py` both contain allowed tests
- **THEN** discovery includes tests from both files

#### Scenario: Test-like non-Python file is a discovery error
- **WHEN** `<tests_dir>/nested/test_cases.txt` exists
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: No recursive tests is a discovery error
- **WHEN** no tests are discovered from any `.py` file under `<tests_dir>`
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** a discovered Python test file contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

### Requirement: Allowed test constructs
The system SHALL support comments, simple literal assignments used by supported parameterization constructs, allowed import statements, `def ...:` blocks at any scope, supported `for` and `while` loop statements, allowed assertion forms, and supported raise expectation blocks as non-comment code in `tests.py`. Each allowed assertion, each supported raise expectation block, and each supported loop statement MUST count as one test. Allowed imports MUST be limited to imports needed for `collections.Counter`, `collections.deque`, `collections.defaultdict`, `decimal.Decimal`, `math.isclose`, and `re.search`.

#### Scenario: Equality assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...) == expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Inequality assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...) != expected`
- **THEN** the assertion is discovered as one test

#### Scenario: Truthy assertion is discovered
- **WHEN** `tests.py` contains `assert ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Falsy assertion is discovered
- **WHEN** `tests.py` contains `assert not ENTRYPOINT(args...)`
- **THEN** the assertion is discovered as one test

#### Scenario: Raise-any block is discovered
- **WHEN** `tests.py` contains a `try` block that calls the entrypoint, then asserts `False`, and catches `Exception` with `pass`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception

#### Scenario: Typed raise block is discovered
- **WHEN** `tests.py` contains a `try` block that calls the entrypoint, then asserts `False`, and catches a specific exception type such as `ValueError`
- **THEN** the block is discovered as one test that passes only when the entrypoint raises an exception matching that type

#### Scenario: Typed raise block with substring message check is discovered
- **WHEN** `tests.py` contains a typed exception handler that asserts a string literal is contained in `str(e)`
- **THEN** the block is discovered as one test that also requires the raised exception message to contain that substring

#### Scenario: Typed raise block with regex message check is discovered
- **WHEN** `tests.py` contains a typed exception handler that asserts `re.search(<pattern>, str(e))`
- **THEN** the block is discovered as one test that also requires the raised exception message to match that regex pattern

#### Scenario: Math isclose assertion is discovered
- **WHEN** `tests.py` contains `assert math.isclose(ENTRYPOINT(args...), expected, abs_tol=abs_tol, rel_tol=rel_tol)`
- **THEN** the assertion is discovered as one test with per-assert absolute and relative tolerance metadata

#### Scenario: Absolute difference tolerance assertion is discovered
- **WHEN** `tests.py` contains `assert abs(ENTRYPOINT(args...) - expected) < tol` or `assert abs(ENTRYPOINT(args...) - expected) <= tol`
- **THEN** the assertion is discovered as one test with a per-assert absolute tolerance and strictness metadata

#### Scenario: Literal assignment for parameterization is accepted
- **WHEN** `tests.py` contains a simple assignment such as `cases = [((1, 2), 3)]` used by a supported loop
- **THEN** discovery accepts the assignment as parameterization data and does not report the assignment itself as a test

#### Scenario: For loop is discovered
- **WHEN** `tests.py` contains a supported `for ... in ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: While loop is discovered
- **WHEN** `tests.py` contains a supported `while ...:` loop
- **THEN** the loop statement is discovered as one loop test

#### Scenario: Unsupported code fails discovery
- **WHEN** `tests.py` contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Single-call traceable assertions
The system SHALL discover supported assertion expressions only when each test is traceable to exactly one invocation of the configured entrypoint. The system MUST reject assertion expressions that contain zero configured entrypoint invocations, more than one configured entrypoint invocation, or unsupported non-primitive function calls.

#### Scenario: Entrypoint call on right side is discovered
- **WHEN** `tests.py` contains `assert 3 == ENTRYPOINT(1, 2)`
- **THEN** the assertion is discovered as one test traceable to the single `ENTRYPOINT(1, 2)` invocation

#### Scenario: Multiple entrypoint calls fail discovery
- **WHEN** `tests.py` contains `assert ENTRYPOINT(1) == ENTRYPOINT(2)`
- **THEN** discovery fails

#### Scenario: Unsupported helper call fails discovery
- **WHEN** `tests.py` contains `assert normalize(ENTRYPOINT(1)) == 1`
- **THEN** discovery fails

#### Scenario: Tolerance helper remains traceable
- **WHEN** `tests.py` contains `assert math.isclose(ENTRYPOINT("near"), 1.0, abs_tol=0.01)`
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
The system SHALL assign each discovered non-loop test a line-based ID in the form `<relative-path>:<line>` using the source file path relative to `<tests_dir>` with forward slashes and 1-based source lines. If multiple non-loop tests originate from the same line outside loop expansion in the same file, the system MUST suffix them as `<relative-path>:<line>#0`, `<relative-path>:<line>#1`, and so on. The system SHALL assign each supported loop statement an ID in the form `<relative-path>:<line>`. The system MUST assign assertions executed from loop bodies IDs in the form `<relative-path>:<line>:<iteration-index>`, where `<iteration-index>` is assigned in execution order for that assertion line within that file.

#### Scenario: Root test ID uses line
- **WHEN** one non-loop test originates on line 12 of `<tests_dir>/tests.py`
- **THEN** its ID is `tests.py:12`

#### Scenario: Nested test ID uses relative path and line
- **WHEN** one non-loop test originates on line 5 of `<tests_dir>/nested/test_cases.py`
- **THEN** its ID is `nested/test_cases.py:5`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two non-loop tests originate on line 12 of the same file outside loop expansion
- **THEN** their IDs are `<relative-path>:12#0` and `<relative-path>:12#1`

#### Scenario: Same line in different files keeps separate IDs
- **WHEN** one test originates on line 3 of `<tests_dir>/a/tests.py` and another test originates on line 3 of `<tests_dir>/b/tests.py`
- **THEN** their IDs are `a/tests.py:3` and `b/tests.py:3`

#### Scenario: Loop statement ID uses relative path and loop line
- **WHEN** a loop statement originates on line 2 of `<tests_dir>/nested/test_cases.py`
- **THEN** the loop test ID is `nested/test_cases.py:2`

#### Scenario: Loop body assertion IDs use iteration suffixes
- **WHEN** an assertion on line 3 of `<tests_dir>/nested/test_cases.py` executes for two loop iterations
- **THEN** the assertion test IDs are `nested/test_cases.py:3:0` and `nested/test_cases.py:3:1`

#### Scenario: Nested loop body assertion IDs use execution order
- **WHEN** an assertion inside nested loops executes four times from line 5 of `<tests_dir>/nested/test_cases.py`
- **THEN** the assertion test IDs are `nested/test_cases.py:5:0`, `nested/test_cases.py:5:1`, `nested/test_cases.py:5:2`, and `nested/test_cases.py:5:3`

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
When tests are discoverable, the system SHALL place every in-scope discovered test ID exactly once in either `passed` or `failed`. For a normal full run, every discovered test is in scope. For `--run <test_id>`, only the selected discovered test is in scope. Any in-scope discovered test that is not executed for any reason, including timeout exhaustion, MUST be listed in `failed`.

#### Scenario: Unexecuted discovered test is failed
- **WHEN** discovery succeeds but an in-scope discovered test cannot be executed
- **THEN** that test ID appears in `failed`

#### Scenario: Every discovered ID is reported once
- **WHEN** discovery succeeds and a full run completes
- **THEN** each discovered test ID appears exactly once across the `passed` and `failed` arrays

#### Scenario: Selected run reports only selected ID
- **WHEN** discovery succeeds and the user runs `test` with `--run tests.py:2`
- **THEN** only `tests.py:2` appears across the `passed` and `failed` arrays

#### Scenario: Timed-out test is failed
- **WHEN** discovery succeeds but an in-scope test exceeds a configured timeout
- **THEN** that test ID appears in `failed`

### Requirement: Discovery failure output
If test discovery fails, the system SHALL output exactly `{"status":"error","passed":[],"failed":[]}` and exit with status code `2`.

#### Scenario: Malformed tests produce discovery error
- **WHEN** `tests.py` cannot be parsed or contains unsupported constructs
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
The system SHALL discover mutation-style tests only when an entrypoint call appears as a standalone statement or as the value of a direct assignment, and that statement is immediately followed by one or more asserts without another entrypoint call before those asserts. Each mutation-style assert MUST reference at least one variable passed to the mutation call or the variable directly assigned from the mutation call result. Files that use mutation patterns outside these constraints MUST fail discovery.

#### Scenario: Statement mutation call is discovered
- **WHEN** a discovered Python test file contains `a = [2, 0, 2, 1, 1, 0]`, then `sort_colors(a)`, then `assert a == [0, 0, 1, 1, 2, 2]`
- **THEN** discovery succeeds and reports the assertion as a test that invokes `sort_colors(a)` once before checking the mutated value of `a`

#### Scenario: Assignment mutation call is discovered
- **WHEN** a discovered Python test file contains `result = mutate(a)` immediately followed by `assert result == expected`
- **THEN** discovery succeeds and reports the assertion as a test that invokes `mutate(a)` once before checking `result`

#### Scenario: Multiple adjacent mutation asserts are discovered
- **WHEN** an entrypoint call statement is immediately followed by two asserts and each assert references a variable passed to that call
- **THEN** discovery succeeds and reports both asserts as tests associated with that single mutation call

#### Scenario: Mutation call without following assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement that is not immediately followed by an assert
- **THEN** discovery fails

#### Scenario: Non-adjacent mutation assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement, then another non-assert statement, then an assert that depends on the mutation call
- **THEN** discovery fails

#### Scenario: Unrelated mutation assert fails discovery
- **WHEN** a discovered Python test file contains an entrypoint call statement followed by an assert that references no variable passed to the call and no variable assigned from the call
- **THEN** discovery fails

#### Scenario: Mutation assert with entrypoint call fails discovery
- **WHEN** a mutation-style assert contains another configured entrypoint invocation
- **THEN** discovery fails

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

### Requirement: Async entrypoint completion
The system SHALL run async or awaitable entrypoint invocations to completion before evaluating the discovered test result for every supported target language. If an async or awaitable invocation does not complete before an applicable timeout, the corresponding test MUST fail through normal timeout result semantics.

#### Scenario: Python async entrypoint is awaited
- **WHEN** a Python solution entrypoint returns an awaitable result for a discovered test
- **THEN** the harness awaits the result before applying that test's assertion semantics

#### Scenario: JavaScript async entrypoint is awaited
- **WHEN** a JavaScript solution entrypoint returns a Promise for a discovered test
- **THEN** the harness awaits the Promise before applying that test's assertion semantics

#### Scenario: TypeScript async entrypoint is awaited
- **WHEN** a TypeScript solution entrypoint returns a Promise for a discovered test
- **THEN** the harness awaits the Promise before applying that test's assertion semantics

#### Scenario: C++ async-like entrypoint is completed
- **WHEN** a C++ solution entrypoint returns a supported future-like result for a discovered test
- **THEN** the harness waits for the result before applying that test's assertion semantics

#### Scenario: Rust async entrypoint is completed
- **WHEN** a Rust solution entrypoint returns a supported future for a discovered test
- **THEN** the harness drives the future to completion before applying that test's assertion semantics

### Requirement: Test discovery listing
The `test --list-tests` command SHALL perform discovery and generated-tester consistency validation without executing the supplied solution. If discovery succeeds, the command MUST output `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, and `failed` as an empty array. If discovery fails or generated-tester consistency validation fails, the command MUST use the standard error result.

#### Scenario: Discovery list succeeds
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery succeeds
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered IDs, and `failed` set to `[]`

#### Scenario: Discovery list fails
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests` and discovery fails
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Single test selection
The `test --run <test_id>` command SHALL execute only the discovered test whose ID exactly matches `<test_id>`. The result MUST include only that selected test ID in `passed` or `failed`. If `<test_id>` is not discovered, the command MUST output the standard error result and exit `2`.

#### Scenario: Selected passing test reports only itself
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2` and `tests.py:2` passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` set to `["tests.py:2"]`, and `failed` set to `[]`

#### Scenario: Selected failing test reports only itself
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:3` and `tests.py:3` fails
- **THEN** stdout contains one JSON line with `status` set to `fail`, `passed` set to `[]`, and `failed` set to `["tests.py:3"]`

#### Scenario: Unknown selected test errors
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:999` and no discovered test has that ID
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Test execution timeouts
The `test --timeout-ms <int>` option SHALL bound each in-scope test's execution time. The `test --total-timeout-ms <int>` option SHALL bound the total execution time for all in-scope tests in a single `test` command invocation. Timed-out tests and in-scope tests that are not executed because the total timeout has been exhausted MUST appear in `failed`. Completed passing tests before timeout exhaustion MUST remain in `passed`.

#### Scenario: Per-test timeout fails timed-out test
- **WHEN** the user runs `test` with `--timeout-ms 50` and one in-scope test exceeds 50 milliseconds
- **THEN** that test ID appears in `failed`

#### Scenario: Total timeout fails remaining tests
- **WHEN** the user runs `test` with `--total-timeout-ms 100` and total execution time is exhausted before all in-scope tests execute
- **THEN** each not-executed in-scope test ID appears in `failed`

#### Scenario: Completed tests remain reported after timeout
- **WHEN** some in-scope tests pass before a later test exceeds a configured timeout
- **THEN** the earlier passing test IDs appear in `passed` and the timed-out or not-executed test IDs appear in `failed`

### Requirement: Profile command requires generated tester
The `profile` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `profile` command MUST NOT create or modify any tester file.

#### Scenario: Missing Python tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` and `<tests_dir>/tester.py` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing JavaScript tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang javascript` and `<tests_dir>/tester.js` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing TypeScript tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang typescript` and `<tests_dir>/tester.ts` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing C++ tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang cpp` and `<tests_dir>/tester.cpp` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing Rust tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang rust` and `<tests_dir>/tester.rs` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile trial validation
The `profile` command SHALL default to one measured trial when `-n` is omitted. The `profile` command MUST reject `-n <trials>` values less than `1`. The `profile` command MUST default to zero warmup runs when `--warmup` is omitted. The `profile` command MUST reject `--warmup <k>` values less than `0` and values where `k >= n`.

#### Scenario: Profile defaults to one measured trial
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` without `-n`
- **THEN** the command records statistics from one measured trial

#### Scenario: Profile rejects zero trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 0`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile rejects warmup equal to trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile rejects warmup greater than trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 4`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile output statistics
The `profile` command SHALL print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object with numeric `mean` and `std` keys computed from measured trial runtimes. When `--memory` is provided, the output MUST also include `memory_kb` as an object with numeric `mean` and `std` keys computed from measured trial memory observations. Warmup runs MUST be excluded from `runtime_ns` and `memory_kb` statistics.

#### Scenario: Passing profile reports runtime statistics
- **WHEN** every in-scope measured trial passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, all in-scope test IDs in `passed`, no test IDs in `failed`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Failing profile reports runtime statistics
- **WHEN** at least one in-scope measured trial fails and no harness error prevents reporting
- **THEN** stdout contains one JSON line with `status` set to `fail`, passing test IDs in `passed`, failing test IDs in `failed`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Memory profile reports memory statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory`
- **THEN** stdout contains one JSON line with `memory_kb.mean` and `memory_kb.std` as numbers

#### Scenario: Profile without memory omits memory statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` without `--memory`
- **THEN** stdout contains one JSON line without a `memory_kb` key

#### Scenario: Warmup runs are excluded from statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 2 --warmup 1`
- **THEN** `runtime_ns.mean` and `runtime_ns.std` are computed from the two measured trials and not from the warmup run

### Requirement: Profile selection behavior
The `profile --list-tests` command SHALL perform discovery and generated-tester consistency validation without executing the supplied solution. If discovery succeeds, the command MUST output `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` as an empty array, and `runtime_ns` aggregate statistics with numeric `mean` and `std` values. If discovery fails or generated-tester consistency validation fails, the command MUST use the standard error result. The `profile --run <test_id>` command SHALL profile only the discovered test whose ID exactly matches `<test_id>`. If `<test_id>` is not discovered, the command MUST output the standard error result and exit `2`.

#### Scenario: Profile list-tests reports discovered IDs without solution execution
- **WHEN** the user runs `profile <tests_dir> <missing_solution_path> --lang python --list-tests`
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered IDs, `failed` set to `[]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile list-tests reports discovery error
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests` and discovery fails
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile run selects one passing test
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:2` and that selected test passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` set to `["tests.py:2"]`, `failed` set to `[]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile run selects one failing test
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:3` and that selected test fails
- **THEN** stdout contains one JSON line with `status` set to `fail`, `passed` set to `[]`, `failed` set to `["tests.py:3"]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile run rejects unknown test ID
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:999`
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile timeout statistics
The `profile --timeout-ms <int>` option SHALL bound each in-scope test's execution time during each profile run. The `profile --total-timeout-ms <int>` option SHALL bound the total execution time for all in-scope tests during each profile run. Timed-out tests and in-scope tests that are not executed because the total timeout has been exhausted MUST appear in `failed`. Timeout observations from measured trials MUST be included in the `runtime_ns` statistics and, when `--memory` is provided, in the `memory_kb` statistics.

#### Scenario: Per-test timeout is included in profile statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 50` and one in-scope test exceeds 50 milliseconds during a measured trial
- **THEN** that test ID appears in `failed` and the timed-out run contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Total timeout marks remaining profile tests failed
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 100` and total execution time is exhausted before all in-scope tests execute during a measured trial
- **THEN** each not-executed in-scope test ID appears in `failed` and the measured run contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Timeout memory observation is included
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 50 --memory` and one in-scope test times out during a measured trial
- **THEN** the timed-out run contributes to `memory_kb.mean` and `memory_kb.std`

