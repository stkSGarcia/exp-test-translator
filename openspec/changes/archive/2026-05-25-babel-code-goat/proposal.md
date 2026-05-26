## Why

There is no standard tool for translating a language-agnostic Python test harness into runnable test files for Python, JavaScript, and TypeScript solutions. This change introduces `babel_code_goat.py`, a CLI that generates language-specific tester files from a canonical `tests.py` spec and runs them against a solution, enabling consistent cross-language test evaluation.

## What Changes

- **New CLI** `babel_code_goat.py` with two sub-commands:
  - `generate <tests_dir> --entrypoint <name> --lang <python|javascript|typescript>` — parses `tests.py` and writes a tester file (`tester.py`, `tester.js`, or `tester.ts`) into `<tests_dir>`
  - `test <solution_path> <tests_dir> --lang <python|javascript|typescript>` — runs the pre-generated tester against the solution and prints a single JSON result line
- Test IDs are line-based (`tests.py:<line>`, with `#N` suffix for multiple tests on the same line)
- Supported test constructs: `assert` equality/truthiness calls, raise-any `try/except` blocks, and `# expect_stdout:`/`# expect_stderr:` comment annotations
- `test` exits `0` (pass), `1` (fail), or `2` (error) and never creates or modifies tester files

## Capabilities

### New Capabilities

- `test-harness-generate`: Parsing `tests.py` and generating a tester file in the target language
- `test-harness-run`: Running a tester file against a solution and producing structured JSON output

### Modified Capabilities

*(none)*

## Impact

- New standalone Python script `babel_code_goat.py` (no new dependencies beyond the standard library and a language runtime for JS/TS)
- Invokes `node`/`npx ts-node` (or equivalent) as a subprocess for JavaScript/TypeScript test execution
- No changes to existing files; no external package requirements for the Python path
