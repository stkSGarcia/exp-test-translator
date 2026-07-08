## Why

The project needs a concrete test-harness translation engine that can turn a Python test description into runner files for supported target languages and enforce a predictable generate-then-test workflow. Defining this up front gives implementation a clear CLI contract, strict failure behavior, and machine-readable results for later automation.

## What Changes

- Add `babel_code_goat.py` as a CLI with `generate` and `test` commands.
- Support `python`, `javascript`, and `typescript` as the only accepted target languages.
- Generate the expected tester file in the provided tests directory for each supported language.
- Require `test` to use an already-generated tester file and never create or modify it.
- Discover supported assertions and raise-any expectation blocks from `tests.py`.
- Execute or translate every discoverable test into pass/fail/error JSON with exact exit-code semantics.
- Treat unsupported languages, missing test inputs, discovery failures, and missing tester files as errors.

## Capabilities

### New Capabilities
- `babel-code-goat-cli`: Defines the `babel_code_goat.py` command-line interface, tester generation contract, test discovery rules, generated-runner preconditions, JSON output shape, and exit-code behavior.

### Modified Capabilities

None.

## Impact

- Adds a root-level `babel_code_goat.py` implementation.
- Adds or updates tests for CLI parsing, tester generation, strict non-modification behavior, discovery, reporting, and exit codes.
- No external services or persistent system dependencies are required.
