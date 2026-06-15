## Why

The checkpoint defines a complete behavior contract for a cross-language test-harness generator and runner. Capturing it as an OpenSpec change gives the implementation a precise CLI, file-generation, discovery, and reporting target before code is written.

## What Changes

- Add a `babel_code_goat.py` command-line tool with `generate` and `test` subcommands.
- Support `python`, `javascript`, and `typescript` as the only valid target languages.
- Generate language-specific tester files in a tests directory without modifying tester files on failure.
- Enforce a strict `generate` before `test` workflow by requiring the expected tester file to already exist.
- Run translated tests and emit exactly one JSON result line with prescribed status, passed, failed, and exit-code behavior.
- Discover allowed Python test constructs from `tests.py`, including assertions, raise-any expectation blocks, and raw stdout/stderr expectations.

## Capabilities

### New Capabilities

- `babel-code-goat-cli`: Defines the CLI, tester generation, test discovery, execution, and JSON reporting behavior for the Babel Code Goat test harness.

### Modified Capabilities

None.

## Impact

- Adds a new root-level `babel_code_goat.py` executable module.
- Produces `tester.py`, `tester.js`, or `tester.ts` inside user-supplied test directories during successful generation.
- Establishes language validation, tester-file preservation, test ID assignment, output schema, and exit-code contracts.
