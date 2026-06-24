## Why

Many Python coding challenge tests use mutation-style checks, where an entrypoint mutates an argument and later assertions inspect that same object instead of comparing a direct return value. Test suites also commonly organize cases across multiple files under a test directory, so requiring a single root `tests.py` file blocks otherwise valid suites.

## What Changes

- Discover constrained mutation-style tests when an entrypoint call appears as a standalone statement or assignment immediately followed by one or more related assertions.
- Require every assertion in a mutation-style group to reference a variable passed to the mutation call, or the variable directly assigned from the mutation call.
- Reject files that use mutation-style patterns outside the supported grouping and variable-reference constraints as discovery errors.
- Discover test definitions recursively from any `.py` file under `<tests_dir>` instead of requiring only `<tests_dir>/tests.py`.
- Treat non-Python files with test-like names under `<tests_dir>` as discovery errors.
- Treat an empty recursive discovery result as a discovery error.
- Change test IDs from root-file-only `tests.py:<line>` IDs to relative path IDs such as `subdir/tests.py:5`, preserving same-line suffixes where needed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Test discovery must support constrained mutation-style tests, recursive Python test file discovery, test-like non-Python file rejection, empty-suite errors, and relative-path test IDs.

## Impact

- Affects Python AST discovery, statement grouping, mutation-style traceability validation, and test ID generation in `babel_code_goat.py`.
- Affects generated tester payloads and runners so mutation assertions execute after a single mutating entrypoint call and report IDs based on the source file path.
- Adds coverage for valid mutation-style groups, invalid mutation patterns, recursive discovery, non-Python test-like files, no-test errors, and relative-path IDs across Python, JavaScript, and TypeScript targets.
