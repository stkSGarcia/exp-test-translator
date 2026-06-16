## 1. CLI and Generation

- [x] 1.1 Add root-level `babel_code_goat.py` with `argparse` subcommands for `generate` and `test`.
- [x] 1.2 Implement target language validation for `python`, `javascript`, and `typescript`.
- [x] 1.3 Implement expected tester filename mapping for `tester.py`, `tester.js`, and `tester.ts`.
- [x] 1.4 Define generated tester metadata that records the entrypoint and target language for later `test` runs.
- [x] 1.5 Implement `generate` so it validates inputs, renders tester content in memory, writes only on success, and exits non-zero without creating or modifying tester files on failure.

## 2. Test Discovery

- [x] 2.1 Implement `tests.py` loading and AST parsing without executing the file.
- [x] 2.2 Validate allowed non-comment constructs at any scope, including nested `def ...:` blocks.
- [x] 2.3 Discover supported assertion forms for equality, inequality, truthiness, and negated truthiness.
- [x] 2.4 Discover raise-any expectation blocks using `try: ENTRYPOINT(args...); assert False` plus `except Exception: pass`.
- [x] 2.5 Parse allowed literal values and reject unsupported values or dictionaries with non-string keys.
- [x] 2.6 Bind immediately preceding `expect_stdout` and `expect_stderr` comments to discovered tests with exact raw string-literal values.
- [x] 2.7 Assign deterministic line-based test IDs, including `#0`, `#1`, and later suffixes for multiple tests on the same line.

## 3. Test Execution and Reporting

- [x] 3.1 Implement `test` preflight checks for the expected tester file and ensure the tester file is never created or modified.
- [x] 3.2 Read and validate generated tester metadata so `test` can infer the entrypoint from a prior `generate` run.
- [x] 3.3 Implement Python solution callable resolution for direct functions, zero-argument instance methods, and static methods.
- [x] 3.4 Implement JavaScript and TypeScript solution callable resolution with captured stdout and stderr.
- [x] 3.5 Execute discovered tests in subprocess-isolated harnesses and evaluate assertion, exception, and raw output expectations.
- [x] 3.6 Aggregate results so every discovered test ID appears exactly once in `passed` or `failed`, with unexecuted tests listed in `failed`.
- [x] 3.7 Emit exactly one JSON stdout line with only `status`, `passed`, and `failed`, and map statuses to exit codes 0, 1, and 2.

## 4. Verification

- [x] 4.1 Add tests for CLI parsing, language validation, tester filename selection, and missing tester errors.
- [x] 4.2 Add tests proving `generate` preserves existing tester files on failure and writes the correct tester file on success.
- [x] 4.3 Add tests for discovery of assertions, nested functions, raise-any blocks, output expectation comments, literal values, and duplicate-line IDs.
- [x] 4.4 Add tests for pass, fail, and error JSON output schemas and exit codes.
- [x] 4.5 Add target-language smoke tests for Python, JavaScript, and TypeScript solution execution.
- [x] 4.6 Run the repository verification commands and record any environment limitations.
