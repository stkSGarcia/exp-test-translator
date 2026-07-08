## Why

Checkpoint 7 requires the test harness to behave predictably for async tests and long-running cases across every supported target language. The current contract does not explicitly require async entrypoint completion, test selection, discovery listing, or timeout accounting, which leaves cross-language test execution ambiguous.

## What Changes

- Run async/await-style entrypoint invocations to completion in every supported target language.
- Add `test` command flags for discovery and execution control:
  - `--list-tests`
  - `--run <test_id>`
  - `--timeout-ms <int>`
  - `--total-timeout-ms <int>`
- Require `--list-tests` to report discovery success with `status="pass"`, all discovered IDs in `passed`, and `failed=[]`.
- Require `--run <test_id>` to report only the selected test ID in `passed` or `failed`.
- Require timed-out and not-executed tests to appear in `failed` so result coverage remains complete.

## Capabilities

### New Capabilities
- `async-test-execution-controls`: Async target execution, test discovery listing, selected test execution, and timeout result accounting for the harness `test` command.

### Modified Capabilities
- None.

## Related Work

### Related Changes
- `support-loop-construct-tests`: Motivated broader test discovery from compact Python loop constructs; this change complements that work by adding execution controls and result guarantees after tests are discovered.
- `add-mutation-style-test-discovery`: Motivated accepting common mutation-based test patterns while preserving entrypoint traceability; this change relies on that discovery coverage and constrains how discovered IDs are listed or selectively run.
- `support-rich-python-test-comparisons`: Motivated realistic Python assertions and exception checks in translation harness tests; this change extends the harness behavior expected when those richer tests contain async entrypoints or require timeout protection.
- `add-babel-code-goat`: Established the concrete generate-then-test CLI workflow; this change extends the `test` side of that workflow with discovery, selection, async completion, and timeout flags.
- `support-single-call-test-traceability`: Motivated broader entrypoint expression support while preserving traceability; this change builds on traceable test IDs so `--run <test_id>` and timeout reporting remain precise.

### Related Specs
- `babel-code-goat-cli/support-rich-python-test-comparisons`: Captures the current root-level CLI and richer comparison support; this change adds execution-control requirements to the same CLI family.
- `compiled-targets/add-cpp-rust-targets`: Extends target language coverage to compiled targets; this change applies async execution and timeout semantics across all supported targets, including compiled ones.
- `python-test-discovery/add-mutation-style-test-discovery`: Extends discovery to mutation-style Python tests; this change uses discovered test IDs as the basis for `--list-tests` and `--run`.
- `babel-code-goat-cli/support-loop-construct-tests`: Extends allowed discovery constructs for parameterized tests; this change preserves discovered IDs in listing and selection output.
- `babel-code-goat-cli/add-babel-code-goat`: Establishes the root CLI contract and generated runner workflow; this change adds required `test` flags and reporting behavior.

## Impact

- Affects `babel_code_goat.py` CLI parsing and `test` command behavior.
- Affects test discovery ID reporting and result serialization.
- Affects target-language runner generation or adapters wherever async entrypoints and timeout enforcement must be handled.
- May require runtime-specific timeout support for Python, JavaScript/TypeScript, Java, C++, Rust, or any other supported target language.
