## Context

`babel_code_goat.py` currently centralizes CLI parsing in `build_parser()`, tester validation and discovery in `command_test()`, and execution result aggregation in `aggregate_results()`. The new `profile` command needs to reuse that path while adding repeated trials, warmup exclusion, runtime statistics, and optional memory statistics.

## Related Work

> **`babel-code-goat-cli/add-babel-code-goat`**: Defines the base CLI command contract, tester file prerequisites, JSON result shape, and generated tester metadata flow - informs the decision to share tester validation and error JSON between `test` and `profile` because profiling must not create or modify tester files _(see `babel-code-goat-cli/add-babel-code-goat`)_.

> **`babel-code-goat-cli/add-async-test-selection-timeouts`**: Defines selected execution, discovery-only listing, and timeout behavior for active test scopes - informs the decision to reuse `ExecutionOptions` and `aggregate_results()` for each profile trial because profile must preserve the same selected and timed-out IDs _(see `babel-code-goat-cli/add-async-test-selection-timeouts`)_.

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines loop-derived test IDs and coverage expectations - informs the decision to compute profile `passed` and `failed` from the same discovered case list because loop statement and per-iteration IDs must remain stable _(see `babel-code-goat-cli/add-loop-as-test-support`)_.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` with the argument order required by the checkpoint.
- Reuse `test` language validation, tester metadata validation, discovery, selection, tolerance, and timeout semantics.
- Add `-n`, `--warmup`, and `--memory` validation with standard error JSON on invalid inputs.
- Emit compact JSON containing `status`, `passed`, `failed`, `runtime_ns`, and optional `memory_kb`.
- Exclude warmup runs from mean/std calculations while still allowing warmup failures to exercise the same execution path.

**Non-Goals:**

- Do not change generated tester file contents solely for profiling.
- Do not add new external dependencies.
- Do not add per-test timing breakdowns or diagnostic messages beyond the required aggregate fields.
- Do not broaden supported target languages beyond the active CLI contract for this change.

## Decisions

1. Share the command setup between `test` and `profile`.

   Extract common validation from `command_test()` into helpers that parse tolerance/timeouts, verify the expected tester file, read metadata, discover cases, and apply `--list-tests`/`--run`. `command_profile()` should call those helpers and then execute trials. Alternative considered: copy `command_test()` and add profiling logic. That would make future flag changes drift across commands.

2. Profile whole active execution scopes per trial.

   A trial should execute the full active case list once through `aggregate_results()`, measuring elapsed time with `time.perf_counter_ns()`. The `passed` and `failed` arrays should come from the measured trials' aggregate outcomes, using stable ordering from the existing result arrays. Alternative considered: measure each individual test case independently. That would require changing the aggregation contract and would make total-timeout behavior harder to preserve.

3. Keep warmup behavior simple and explicit.

   Run `--warmup <k>` trials before measured trials through the same execution path, but do not add their timing or memory samples to the statistics arrays. Invalid `k >= n`, negative counts, and non-integer counts should return the standard error JSON with exit code 2. Alternative considered: treat warmup as extra trials on top of `-n`; this conflicts with the checkpoint wording that `k < n` and that warmups are excluded from statistics.

4. Compute population statistics over measured samples.

   Add a small helper for `mean` and `std`; for one measured sample, `std` should be `0`. This keeps JSON deterministic and avoids introducing a statistics dependency. Alternative considered: sample standard deviation. The checkpoint does not specify sample semantics, and population std is simpler for complete measured trial sets.

5. Implement memory sampling with standard-library best effort.

   When `--memory` is set, record one memory sample per measured trial around the same active execution scope. Prefer `resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss` where available because solutions run in child subprocesses; normalize values to kilobytes for `memory_kb`. If child peak memory cannot be observed on a platform, return a numeric `0` sample rather than failing a successful profile. Alternative considered: shelling out to `/usr/bin/time`; that would add platform-specific command dependencies and complicate Node/Python parity.

## Risks / Trade-offs

- Whole-trial timing hides per-test variance -> Keep the JSON aggregate focused on mean/std as requested and leave per-test timing for a future capability.
- Memory samples from child-process resource counters can be coarse or platform-dependent -> Normalize to kilobytes and add tests that assert numeric shape rather than exact memory values.
- Re-running tests can repeat side effects in user solutions -> Document through behavior by reusing the existing execution model and keep `--list-tests` as the non-executing mode.
- Timeout tests are timing-sensitive -> Use generous thresholds for passing tests and small controlled sleeps only for deliberate timeout coverage.

## Migration Plan

1. Refactor shared `test` setup helpers without changing existing `test` output.
2. Add the `profile` parser and command implementation.
3. Add profiling statistics helpers and memory sampling.
4. Add regression tests for the new command and rerun the existing suite.

Rollback is straightforward: remove the `profile` parser branch and helper usages if the new command must be backed out; existing `test` behavior should remain covered by current tests.

## Open Questions

- None.
