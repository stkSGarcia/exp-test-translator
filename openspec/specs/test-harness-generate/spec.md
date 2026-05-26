# Spec: test-harness-generate

## Purpose

The `generate` sub-command parses a `tests.py` file and produces a language-specific tester file that can later be executed by the `test` command.

## Requirements

### Requirement: Generate command produces a tester file
The `generate` sub-command SHALL parse `tests.py` in `<tests_dir>`, resolve the target language from `--lang`, and write a single tester file into `<tests_dir>`. The written file SHALL be `tester.py` for `--lang python`, `tester.js` for `--lang javascript`, and `tester.ts` for `--lang typescript`.

#### Scenario: Python tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.py` is created and the process exits `0`

#### Scenario: JavaScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang javascript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.js` is created and the process exits `0`

#### Scenario: TypeScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang typescript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.ts` is created and the process exits `0`

### Requirement: Unsupported language is an error
The `generate` command SHALL reject any `--lang` value that is not `python`, `javascript`, or `typescript`.

#### Scenario: Invalid lang rejected
- **WHEN** `generate <tests_dir> --entrypoint solve --lang ruby` is run
- **THEN** the process exits non-zero and no tester file is created or modified

### Requirement: Generate failure leaves no tester file
If `generate` fails for any reason (missing `tests.py`, parse error, I/O error), it SHALL NOT create or modify `tester.py`, `tester.js`, or `tester.ts` in `<tests_dir>`.

#### Scenario: Missing tests.py
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and `<tests_dir>/tests.py` does not exist
- **THEN** the process exits non-zero and `<tests_dir>/tester.py` is not created

#### Scenario: Partial write rolled back on error
- **WHEN** `generate` begins writing the tester file but encounters an error mid-write
- **THEN** no partial tester file remains in `<tests_dir>`

### Requirement: Test discovery parses tests.py constructs
The generator SHALL discover and emit a tester case for each of the following constructs in `tests.py`:
- `assert ENTRYPOINT(args) == expected`
- `assert ENTRYPOINT(args) != expected`
- `assert ENTRYPOINT(args)`
- `assert not ENTRYPOINT(args)`
- Raise-any block: `try: ENTRYPOINT(args); assert False\nexcept Exception: pass`
- Lines preceded by `# expect_stdout: "<literal>"` or `# expect_stderr: "<literal>"`

Assertions inside function bodies SHALL be discovered even if the function is never called.

#### Scenario: Equality assertion discovered
- **WHEN** `tests.py` contains `assert solve(1, 2) == 3`
- **THEN** the generated tester contains a test case that calls the entrypoint with `(1, 2)` and asserts the result equals `3`

#### Scenario: Raises assertion discovered
- **WHEN** `tests.py` contains the raise-any block pattern
- **THEN** the generated tester contains a test case that asserts the entrypoint raises any exception

#### Scenario: Assertions inside functions discovered
- **WHEN** `tests.py` contains `def test_foo(): assert solve(0) == 0` but `test_foo` is never called
- **THEN** the generated tester still includes a test case for that assertion

#### Scenario: expect_stdout annotation applied
- **WHEN** `tests.py` has `# expect_stdout: "hello\n"` on the line immediately before an assertion
- **THEN** the generated tester captures stdout during that call and asserts it equals `hello\n`

### Requirement: Test IDs are line-based
Each test case in the generated tester SHALL be identified as `tests.py:<line>` (1-based line number of the assertion or raise-any block). When multiple tests originate from the same line, they SHALL be disambiguated as `tests.py:<line>#0`, `tests.py:<line>#1`, etc.

#### Scenario: Single test on a line
- **WHEN** an assertion is the only test on line 5 of `tests.py`
- **THEN** its ID in the tester output is `tests.py:5`

#### Scenario: Multiple tests on same line
- **WHEN** two tests originate from line 7
- **THEN** their IDs are `tests.py:7#0` and `tests.py:7#1`

### Requirement: Allowed argument and expected value types
The generator SHALL support the following value types in assertion arguments and expected values: `None`, `bool`, `int`, `float`, `str`, `list`, `tuple`, `dict` (with string keys). Nested combinations SHALL be supported. Equality SHALL be deep/structural.

#### Scenario: Nested dict/list round-trips
- **WHEN** `tests.py` contains `assert solve({"a": [1, 2]}) == {"b": (3,)}`
- **THEN** the generated tester encodes and compares these values with deep equality in the target language

### Requirement: Solution callable forms
The generated tester SHALL support two forms of entrypoint resolution:
1. A module-level callable named exactly as `--entrypoint`
2. A class with the same name as `--entrypoint`, constructible with zero arguments, with an instance method or static method of that name

#### Scenario: Module-level function used
- **WHEN** the solution exports a function named `solve`
- **THEN** the tester calls `solve(args...)` directly

#### Scenario: Class method used
- **WHEN** the solution exports a class named `solve` with a method `solve`
- **THEN** the tester instantiates `solve()` and calls `.solve(args...)`
