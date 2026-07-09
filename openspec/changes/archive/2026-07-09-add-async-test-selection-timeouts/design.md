## Context

`babel_code_goat.py` generates per-language testers and the `test` command validates the generated payload before executing the tester as a subprocess. The result contract is already centralized around a single JSON object containing `status`, `passed`, and `failed`, with discovery failures returning the existing error envelope.

This change extends that existing flow: discovery still comes from `discover_tests`, generated testers still own per-test assertion logic, and `command_test` remains responsible for CLI flags, payload validation, subprocess execution, and result validation.

## Related Work

**`babel-code-goat-cli/add-babel-code-goat`**: Defines the root CLI, supported languages, generated tester files, and result envelope - informs keeping `--list-tests`, `--run`, and timeout behavior on `test` because `add-babel-code-goat` established the generate-then-test workflow as the public surface. _(see `babel-code-goat-cli/add-babel-code-goat`)_

**`babel-code-goat-cli/support-loop-construct-tests`**: Defines loop-expanded and zero-iteration test IDs - informs using discovered IDs as the stable selection/listing unit because loop tests made multiple runtime cases share compact source constructs. _(see `babel-code-goat-cli/support-loop-construct-tests`)_

**`babel-code-goat-cli/support-mutation-style-tests`**: Defines mutation-style discovery and execution - informs applying selection and timeout handling around whole tests instead of only expression comparisons because mutation tests may validate post-call state. _(see `babel-code-goat-cli/support-mutation-style-tests`)_

**`babel-code-goat-cli/support-single-call-test-traceability`**: Defines traceable single-call assertions - informs keeping `--run` scoped to exactly one discovered ID because traceability depends on a stable mapping from assertion to entrypoint invocation. _(see `babel-code-goat-cli/support-single-call-test-traceability`)_

**`compiled-language-targets/add-cpp-rust-targets`**: Extends command support to compiled targets - informs separating compile failure from runtime timeout because compiled targets have a build phase before test execution. _(see `compiled-language-targets/add-cpp-rust-targets`)_

## Goals / Non-Goals

**Goals:**

- Add parser support for `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.
- Preserve the existing JSON result shape and exit-code behavior for pass, fail, and error cases.
- Let generated testers execute only the in-scope tests and fail timed-out or skipped in-scope IDs for coverage.
- Await async entrypoint values or asynchronous exceptions before assertion evaluation in targets where async/await is meaningful.
- Cover all supported target languages, including compiled targets after successful compilation.

**Non-Goals:**

- Adding a new test definition language or changing discovery syntax.
- Changing generated test IDs.
- Adding external scheduler, sandbox, or process supervision dependencies.
- Guaranteeing interruption of arbitrary CPU-bound code inside every target runtime after the exact millisecond boundary; the contract is result coverage and bounded harness behavior.

## Decisions

### Keep selection and listing in `command_test`

`command_test` should validate discovery against the tester payload, derive the ordered in-scope test IDs, and short-circuit `--list-tests` without executing the solution. This keeps listing independent of language runtimes and preserves the discovery-failure envelope before any target-specific work. Alternative considered: add a separate `list-tests` command. Keeping this on `test` matches the requested flags and the existing command interface. _(see `babel-code-goat-cli/add-babel-code-goat`)_

### Pass execution controls through generated tester payload or argv

Generated testers should receive the selected ID, per-test timeout, total-timeout deadline, and complete in-scope ID list from the Python CLI wrapper. This lets each language runner enforce the same contract while still using native async and timing primitives. Alternative considered: run one subprocess per test from `command_test`. That would simplify timeout supervision but would repeatedly load compiled or interpreted solutions and would bypass current generated-runner batching.

### Treat timeouts as failed tests, not harness errors

Timeouts after successful discovery should produce `status: "fail"` with timed-out or not-executed IDs in `failed`. Reserve `status: "error"` for unsupported languages, missing/stale testers, discovery failures, malformed result JSON, and compile failures. This follows the existing coverage rule that unexecuted discovered tests are failed rather than dropped. _(see `babel-code-goat-cli/add-babel-code-goat`)_

### Use target-native async completion

Python generated testers should detect awaitable results and drive them through an event loop before comparison. JavaScript and TypeScript generated testers should make test execution async and `await` promises. C++ and Rust generated testers should preserve synchronous behavior unless generated code has an explicit async integration point available in the target harness; timeout handling still applies at the test-command level for compiled binaries. Alternative considered: only enforce async in JavaScript/TypeScript. The checkpoint requires every target to run async/await semantics to completion or timeout, so the design keeps the language-specific runner as the abstraction point.

### Apply total timeout after discovery and validation

The total timeout should bound runtime execution after discovery and tester validation, not parsing itself. If the total deadline expires mid-run, the runner returns a valid JSON result with remaining in-scope IDs failed. Alternative considered: wrap the entire `command_test` in a subprocess timeout. That would be simpler but would lose the required coverage-preserving result.

## Risks / Trade-offs

- [Risk] Native timeout APIs differ across languages -> Mitigation: keep the result contract language-neutral and add focused tests for Python, JavaScript/TypeScript, C++, and Rust behavior.
- [Risk] CPU-bound async or compiled code may resist precise cancellation -> Mitigation: enforce subprocess-level bounds from the Python CLI when a target runner cannot cancel internally, then synthesize failed IDs for the in-scope tests.
- [Risk] `--run` can drift from generated payload order if discovery changes -> Mitigation: validate current discovery against the payload before selection, preserving the existing stale-tester error behavior.
- [Risk] `--list-tests` accepts a `solution_path` it does not use -> Mitigation: retain the existing command signature and document through behavior that no entrypoint executes.

## Migration Plan

1. Extend parser flags and argument validation in `babel_code_goat.py`.
2. Update generated tester code for each supported language to accept selection and timeout controls.
3. Add tests for listing, selection, async completion, per-test timeouts, and total-timeout coverage.
4. Preserve rollback by reverting the generated-runner and parser changes; no persisted data migration is required.

## Open Questions

- Should non-positive timeout values be rejected as CLI errors or treated as immediate expiration?
- Should `--list-tests --run <id>` be rejected, or should `--list-tests` ignore execution selection and report all discovered IDs?
