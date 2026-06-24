## 1. CLI and Structure

- [x] 1.1 Create root-level `babel_code_goat.py` with `argparse` command routing for `generate` and `test`.
- [x] 1.2 Validate `--lang` against `python`, `javascript`, and `typescript` for both commands.
- [x] 1.3 Map each supported language to its tester filename and runtime behavior.
- [x] 1.4 Add shared helpers for strict JSON result output and exit-code selection.

## 2. Test Discovery

- [x] 2.1 Implement `tests.py` loading and parse failures as discovery errors.
- [x] 2.2 Implement AST validation for comments, `def` blocks, allowed assertions, and raise-any expectation blocks.
- [x] 2.3 Implement allowed literal conversion for `None`, booleans, numbers, strings, lists, tuples, and dictionaries with string keys.
- [x] 2.4 Implement line-based test ID assignment, including same-line `#0`, `#1`, and later suffixes.
- [x] 2.5 Capture immediately preceding `expect_stdout` and `expect_stderr` comments as raw string expectations.

## 3. Tester Generation

- [x] 3.1 Generate a Python tester that can load Python solutions and execute the normalized discovered tests.
- [x] 3.2 Generate a JavaScript tester that can load JavaScript solutions and execute the normalized discovered tests.
- [x] 3.3 Generate a TypeScript tester that can load TypeScript solutions and execute the normalized discovered tests.
- [x] 3.4 Write tester files through temporary files and atomic replacement only after successful generation.
- [x] 3.5 Ensure failed `generate` runs do not create or modify `tester.py`, `tester.js`, or `tester.ts`.

## 4. Test Execution

- [x] 4.1 Make `test` error when the expected tester file is missing and avoid creating or modifying tester files.
- [x] 4.2 Implement solution callable resolution for top-level callables and no-argument constructible class methods or static methods.
- [x] 4.3 Execute equality, inequality, truthy, falsy, and raise-any tests with deep structural comparison.
- [x] 4.4 Capture per-test stdout and stderr and compare them exactly against expectations.
- [x] 4.5 Report every discovered test ID exactly once in either `passed` or `failed`, marking unexecuted discovered tests as failed.
- [x] 4.6 Emit exactly one stdout JSON line with only `status`, `passed`, and `failed`, and return `0`, `1`, or `2` by status.

## 5. Verification

- [x] 5.1 Add CLI tests for supported and unsupported language handling.
- [x] 5.2 Add generation tests for the three tester filenames and failure non-modification behavior.
- [x] 5.3 Add strict `generate -> test` tests for missing tester errors and tester non-modification during `test`.
- [x] 5.4 Add discovery tests for allowed assertions, nested functions, raise-any blocks, unsupported constructs, literals, and duplicate line IDs.
- [x] 5.5 Add execution/reporting tests for pass, fail, error, exact JSON keys, exit codes, stdout/stderr expectations, and coverage accounting.
