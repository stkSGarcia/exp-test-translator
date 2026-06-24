## Context

`babel_code_goat.py` currently keeps discovery, payload validation, CLI parsing, and generated tester source in one module. The `test` command revalidates the generated tester payload against rediscovered Python tests, launches the selected language tester, validates that the tester prints exactly one JSON result line, and then reprints that result using the stable `status`/`passed`/`failed` contract.

Checkpoint 7 adds execution controls that cut across this flow: async entrypoints must settle before assertions are evaluated, users must be able to list or select discovered IDs, and timeout outcomes must still satisfy result coverage accounting.

## Goals / Non-Goals

**Goals:**

- Run awaitable entrypoint results to completion for every supported target language before evaluating assertions, mutation postconditions, stream expectations, or raise/panic expectations.
- Add `test --list-tests` and `test --run <test_id>` using the same rediscovered and payload-validated test IDs already used in result reporting.
- Add `test --timeout-ms <int>` and `test --total-timeout-ms <int>` while keeping output as exactly one JSON line with only `status`, `passed`, and `failed`.
- Ensure timed-out and not-executed discovered tests are reported in `failed`, preserving the existing coverage rule.
- Keep tester files immutable during `test` and continue using temporary build/run artifacts for compiled targets.

**Non-Goals:**

- Adding arbitrary async test syntax to the Python source discovery language.
- Supporting multi-file projects, package managers, third-party async runtimes, or external crates.
- Changing test ID formats, generated tester filenames, supported language names, or the existing `--tol` behavior.
- Reporting timeout durations, diagnostics, or extra JSON fields.

## Decisions

1. Keep selection and listing anchored in the CLI revalidation step.

   `command_test` should extract the tester payload, rediscover tests, compare the payload to discovery, and then derive the selected ID list. `--list-tests` can return `{"status":"pass","passed":[...],"failed":[]}` immediately after successful revalidation without loading or executing solution code. `--run <test_id>` should validate that the ID exists before launching a tester.

   Alternative considered: have generated testers implement discovery listing. That would duplicate payload parsing and make `--list-tests` unnecessarily dependent on target-language runtime behavior.

2. Pass execution controls to testers through a small stable runtime contract.

   Use environment variables or equivalent generated-tester arguments for selected IDs, per-test timeout, total timeout/deadline, and tolerance. Keeping this contract explicit lets Python, JavaScript, TypeScript, C++, and Rust testers filter the embedded payload consistently while preserving the existing command syntax and tester file format.

   Alternative considered: rewrite the embedded payload during `test`. That would violate the requirement that `test` does not create or modify tester files.

3. Prefer target-side async settlement with CLI-side process deadlines.

   Generated testers should normalize entrypoint invocation through helper functions that return the completed value: Python awaits coroutine/awaitable results, JavaScript/TypeScript await Promises, C++ waits on `std::future`/`std::shared_future`-style results, and Rust polls futures to completion with standard-library-only support. The CLI should also enforce the total timeout around launched tester processes so a stalled target cannot prevent a well-formed result.

   Alternative considered: rely only on subprocess timeouts. That can kill a hung run, but it does not allow normal async values to complete and be compared in successful cases.

4. Treat timeouts as failing test outcomes, not harness errors, once discovery succeeds.

   If an individual selected test times out, its ID goes to `failed`. If the total timeout expires before all selected tests can execute, every remaining selected ID goes to `failed`. The overall status is `fail` unless an existing precondition or harness error prevents discovery or result construction, in which case the existing `error` behavior still applies.

   Alternative considered: report timeout as `error`. That would conflict with the coverage rule requiring timed-out or not-executed discovered tests to appear in `failed`.

5. Preserve mutation group semantics while supporting selection.

   Full runs should continue to execute adjacent mutation assertions from the same group with one entrypoint invocation. A selected mutation assertion may execute the group setup needed for that assertion, but only the selected test ID may appear in the result when `--run` is used.

   Alternative considered: disallow `--run` for mutation-style tests. That would make selection surprising because mutation tests already have stable IDs.

## Risks / Trade-offs

- [Risk] Some async forms in C++ and Rust are difficult to detect generically without dependencies. -> Mitigation: support standard-library awaitable/future shapes first and keep unsupported forms as normal compile/runtime failures.
- [Risk] Per-test timeout handling can duplicate startup or compilation work if implemented by launching one tester process per execution unit. -> Mitigation: compile compiled testers once per `test` invocation and reuse the temporary executable where possible.
- [Risk] Killing a timed-out subprocess can lose target-side partial results. -> Mitigation: synthesize the final JSON from the CLI using the selected ID list and any completed test IDs known before the timeout.
- [Risk] `--run` can interact awkwardly with mutation groups that normally batch assertions. -> Mitigation: filter reporting to the selected ID while preserving the minimum execution context needed to evaluate that assertion.
- [Risk] Existing JavaScript/TypeScript promise handling may not cover timeout rejection paths. -> Mitigation: add explicit tests for resolving, rejecting, and never-settling async results.
