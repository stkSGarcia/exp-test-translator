# babel-code-goat-cli Specification

## Purpose
TBD - created by archiving change add-babel-code-goat. Update Purpose after archive.
## Requirements
### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]` and `test <solution_path> <tests_dir> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, and `typescript` as target languages.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, or `--lang typescript`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate` or `test` with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command exits non-zero

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
The system SHALL discover tests from a file named `tests.py` inside `<tests_dir>`. Assertions inside functions, including nested functions, MUST count as tests even if the function is not called.

#### Scenario: Missing tests file is a discovery error
- **WHEN** `tests.py` is absent from `<tests_dir>`
- **THEN** discovery fails and `test` outputs `{"status":"error","passed":[],"failed":[]}`

#### Scenario: Assertion inside uncalled function is discovered
- **WHEN** `tests.py` contains a function with an allowed assertion that is never called
- **THEN** the assertion is discovered as a test

### Requirement: Allowed test constructs
The system SHALL support only comments, `def ...:` blocks at any scope, allowed assertion forms, and raise-any expectation blocks as non-comment code in `tests.py`. Each allowed assertion and each raise-any expectation block MUST count as one test.

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

#### Scenario: Unsupported code fails discovery
- **WHEN** `tests.py` contains non-comment code outside the allowed constructs
- **THEN** discovery fails

### Requirement: Test IDs
The system SHALL assign each discovered test a line-based ID in the form `tests.py:<line>` using 1-based source lines. If multiple tests originate from the same line, the system MUST suffix them as `tests.py:<line>#0`, `tests.py:<line>#1`, and so on.

#### Scenario: Single test ID uses line
- **WHEN** one test originates on line 12
- **THEN** its ID is `tests.py:12`

#### Scenario: Multiple same-line IDs use suffixes
- **WHEN** two tests originate on line 12
- **THEN** their IDs are `tests.py:12#0` and `tests.py:12#1`

### Requirement: Allowed values and equality
The system SHALL support `None`, booleans, integers, floats, strings, lists, tuples, and dictionaries with string keys as allowed argument and expected values. Nested allowed values MUST be supported. Equality and inequality checks MUST use deep structural comparison for nested containers.

#### Scenario: Nested values compare structurally
- **WHEN** a discovered assertion compares nested allowed containers returned by the entrypoint
- **THEN** the test result is based on deep structural equality

#### Scenario: Unsupported literal fails discovery
- **WHEN** an argument or expected value is outside the allowed value set
- **THEN** discovery fails

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
The system SHALL test code written in the same language as the selected tester. The callable under test MUST be accepted when it is either a callable named by the inferred entrypoint or a no-argument constructible class with a callable method or static method of that name.

#### Scenario: Top-level callable is used
- **WHEN** the solution exposes a callable with the inferred entrypoint name
- **THEN** the tester invokes that callable for discovered tests

#### Scenario: No-argument class method is used
- **WHEN** the solution exposes a no-argument constructible class with a callable method matching the inferred entrypoint name
- **THEN** the tester constructs the class and invokes that method for discovered tests

