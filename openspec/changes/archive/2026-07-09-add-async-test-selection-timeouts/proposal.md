## Why

The `test` command currently treats generated target runners as a single synchronous batch, which leaves async/await-style solutions under-specified and can hang indefinitely when a target never completes. It also lacks first-class test discovery, single-test selection, and timeout controls needed to debug generated harnesses predictably.

## What Changes

- Extend generated runners for every supported target language so async/await entrypoint calls are driven to completion before comparison.
- Add `test --list-tests` to report discovered test IDs without executing a solution.
- Add `test --run <test_id>` to execute and report only the selected test.
- Add `test --timeout-ms <int>` to bound each test invocation and report timed-out or not-executed tests as failed.
- Add `test --total-timeout-ms <int>` to bound the whole test command and preserve coverage by failing tests that did not run.
- Preserve the existing result shape, with `status`, `passed`, and `failed`, for normal execution, listing, selection, and timeout outcomes.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `babel-code-goat-cli`: Extend the `test` command contract and generated target runner behavior for async completion, discovery listing, single-test selection, and timeout coverage.

## Related Work

### Related Changes

- `add-babel-code-goat`: Established the generate-then-test CLI flow and supported target language matrix; this change extends that `test` surface rather than adding a new command.
- `support-loop-construct-tests`: Added compact parameterized discovery where generated IDs must remain stable; this change reuses those IDs for `--list-tests` and `--run`.
- `support-mutation-style-tests`: Broadened execution beyond simple expression assertions; this change keeps timeout and selection behavior independent of assertion style.
- `support-rich-python-test-comparisons`: Expanded realistic expected values and exception checks; this change keeps those comparisons intact after async completion.

### Related Specs

- `babel-code-goat-cli/add-babel-code-goat`: Defines the root CLI, supported languages, generated tester files, and result envelope; this change modifies the existing `test` command behavior.
- `babel-code-goat-cli/support-loop-construct-tests`: Defines loop-expanded and zero-iteration test IDs; this change uses that discovery contract for listing and selection.
- `babel-code-goat-cli/support-mutation-style-tests`: Defines mutation-style discovery and execution; this change applies the same selection and timeout guarantees to mutation tests.
- `babel-code-goat-cli/support-single-call-test-traceability`: Defines traceable single-call assertions; this change preserves per-test traceability when running one selected ID.
- `compiled-language-targets/add-cpp-rust-targets`: Extends command support to compiled targets; this change includes those targets in timeout and selection behavior while keeping compile failures as errors.

## Impact

- Affected CLI: `babel_code_goat.py test`.
- Affected generated runner paths: `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, and `tester.rs`.
- Affected tests: `tests/test_babel_code_goat.py`.
- No breaking change to the JSON result shape or existing `generate` command.
