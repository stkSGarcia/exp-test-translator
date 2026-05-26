## Why

Test authors need to write tests for in-place mutation functions (e.g., `sort_colors(a)` then `assert a == [...]`) and to organize tests across multiple files in a directory tree rather than a single flat `tests.py`. These two missing capabilities limit the harness to return-value-only functions and single-file test suites.

## What Changes

- **Mutation-style test parsing**: The parser recognises entrypoint calls used as statements or assignments (not just in `assert` expressions), where the immediately following assertions check variables that were passed to — or directly assigned from — the call. This allows testing in-place mutation functions.
- **Discovery error for out-of-constraint mutation**: If mutation-style usage appears outside these constraints (e.g., assertions referencing unrelated variables, or mutation call not immediately before its assertions), the generate command exits with a discovery error.
- **Directory-based test discovery**: The `generate` command now discovers tests from any `.py` file under `<tests_dir>` recursively, not only from a required `tests.py` at the root.
- **Test-like non-`.py` files are a discovery error**: Files matching test-like name patterns (`test*.ext`, `*_test.ext`, `tests.ext`, `*_tests.ext`) that are not `.py` files cause a discovery error.
- **Empty discovery is an error**: If no test cases are discovered across all `.py` files in `<tests_dir>`, this is a discovery error.
- **New test ID format**: Test IDs use the relative path from `<tests_dir>` with forward slashes, followed by `:` and line number. Multiple tests on the same line use `#k` suffix (0-indexed). Example: `subdir/tests.py:5` or `nested/test_foo.py:10#0`.

## Capabilities

### New Capabilities

- `mutation-tests`: Parsing and execution of mutation-style test patterns where the entrypoint is called as a statement or assignment immediately before assertions that check mutated arguments or assigned results.

### Modified Capabilities

- `test-harness-generate`: Generate command now discovers tests from any `.py` file in the `<tests_dir>` tree (not only `tests.py`), enforces test-like non-`.py` file detection, raises a discovery error when no tests are found, and uses the new path-prefixed test ID format.
- `test-parsing`: Parser now handles mutation call statements and assignments as test constructs, with constraint validation that the immediately following assertions reference variables from the mutation call.

## Impact

- `babel_code_goat.py`: `cmd_generate` — replace single `tests.py` lookup with recursive `.py` discovery; `parse_tests` — add mutation-call statement/assignment recognition and constraint checking; test ID generation — prefix IDs with relative file path.
- All three tester emitters (`emit_python`, `emit_javascript`, `emit_typescript`) receive test cases with the new ID format, but the emitter logic itself is unchanged.
- No changes to the `test` sub-command (`cmd_test`) or generated tester runtime logic.
