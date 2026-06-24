## Context

`babel_code_goat.py` already has a generated tester workflow: `generate` writes a language-specific tester, and `test` validates that tester payload before executing selected tests. The new `profile` command should behave like `test` for discovery, tester validation, selection, tolerance, and timeout semantics, while adding repeated measurement and aggregate JSON fields.

The implementation is contained in the root CLI and its tests. No external service, persistent storage, or generated-test format migration is required.

## Goals / Non-Goals

**Goals:**
- Add `profile <tests_dir> <solution_path> --lang <target_lang>` with the argument order requested by the checkpoint.
- Reuse the same generated tester validation and selected test execution semantics as `test`.
- Produce deterministic JSON shape for profiling results: core status lists plus runtime aggregate fields, and memory aggregate fields only when requested.
- Exclude warmup runs from statistics while validating that `--warmup < -n`.
- Include timeout measurements in aggregate statistics and failed test reporting.

**Non-Goals:**
- Changing the generated tester payload schema.
- Adding per-test timing breakdowns or trace output.
- Implementing platform-perfect peak memory accounting for every runtime. The initial implementation can use a portable process-level approximation, with tests asserting shape and numeric behavior rather than OS-specific exact values.
- Changing the existing `test` command JSON shape.

## Decisions

1. Share validation and selection helpers between `test` and `profile`.

   The existing `command_test` performs language validation, generated tester existence checks, payload extraction, discovery comparison, `--run` validation, and `--list-tests` behavior. Extracting these steps into helpers keeps `profile` aligned with `test` and avoids two subtly different preflight paths.

   Alternative considered: copy the `command_test` preflight into `command_profile`. That is faster to type but increases the chance that future tester validation behavior diverges.

2. Measure around tester process executions, not inside generated testers.

   Runtime can be measured in the CLI with `time.perf_counter_ns()` before and after each tester process invocation. This avoids regenerating all language testers for a measurement-only feature and gives uniform behavior for Python, JavaScript, TypeScript, C++, and Rust.

   Alternative considered: inject timing into each generated tester. That could enable finer per-test measurements but would require broad generator changes and would make this checkpoint larger than necessary.

3. Treat one measured sample as one selected-run execution.

   A profiling trial should execute the same selected test set that `test` would execute for the given flags. `-n` controls the number of measured selected-run executions; `--warmup` controls the number of unmeasured selected-run executions performed first.

   Alternative considered: collect one sample per individual test. That would complicate aggregation and make behavior differ depending on whether `--timeout-ms` forces per-test subprocess execution.

4. Use population standard deviation for reported `std`.

   The command reports an aggregate over the requested measured trials, not an estimate of a larger sample distribution. For a single measured trial, `std` is `0`.

   Alternative considered: sample standard deviation. It is common statistically, but produces undefined or special-case behavior for one trial and is less convenient for a CLI JSON contract.

5. Keep timeout measurements reportable.

   If a tester subprocess times out, the elapsed timeout duration is recorded for that measured trial, the timed-out selected IDs are merged into `failed`, and profiling continues when possible. Harness-level errors, invalid tester output, invalid flags, or discovery mismatches still return the existing error JSON without aggregate fields.

   Alternative considered: abort profiling on the first timeout. That would lose the checkpoint's requested behavior that timeout results are included in aggregate statistics.

## Risks / Trade-offs

- Memory measurement portability -> Use a lightweight standard-library or process-resource based approach and keep the output contract to numeric aggregate `memory_kb` values rather than exact per-runtime semantics.
- Repeated compiled-language trials can spend time rebuilding compiled testers -> Reuse the existing compiled execution path initially for correctness; optimize compile caching later only if profiling becomes too slow.
- Timeout continuation can produce partial pass/fail observations across trials -> Merge pass/fail lists by test ID, with any failure in a measured trial causing the final status to be `fail`.
- Warmup failures blur "excluded from statistics" semantics -> Treat harness errors during warmup as errors, and ordinary test failures during warmup as pass/fail observations that do not contribute timing or memory samples.

## Migration Plan

1. Add shared preflight and selected-run helpers while preserving `test` behavior.
2. Add `profile` parser arguments and command dispatch.
3. Add runtime aggregation, warmup handling, memory aggregation, and timeout inclusion.
4. Add regression tests for existing `test` behavior and new `profile` scenarios.
5. Roll back by removing the `profile` parser/command and shared helper changes if regressions appear.

## Open Questions

- None.
