## Context

`babel_code_goat.py` currently owns CLI parsing, generated tester validation, test discovery verification, language-specific runner dispatch, timeout handling, and JSON result normalization in one file. The existing `test` command already has the right execution semantics for selection, tolerance, async handling, compiled targets, and timeout failure mapping; `profile` needs to reuse that behavior while adding repeated measured runs and aggregate statistics.

## Related Work

**`babel-code-goat-cli/add-babel-code-goat`**: Defines the root CLI, generated tester prerequisite, JSON result shape, and coverage rule — informs the decision to make `profile` a peer command that validates generated testers before execution because profiling should not silently regenerate or reinterpret tests.

**`babel-code-goat-cli/add-async-test-selection-timeouts`**: Defines async completion, selection, and timeout semantics — informs the decision to route profile executions through the same runner path as `test` because profiling must preserve pass/fail behavior while adding measurements.

**`compiled-language-targets/add-cpp-rust-targets`**: Defines compiled tester files and compile-before-run behavior — informs the decision to keep compiled target setup in the shared execution helper because `profile` must support the same language matrix.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]`.
- Reuse existing generated tester validation and test discovery verification. _(see `babel-code-goat-cli/add-babel-code-goat`)_
- Reuse `test` flags for listing, selection, timeout, and tolerance. _(see `babel-code-goat-cli/add-async-test-selection-timeouts`)_
- Run warmup trials before measured trials and exclude warmup samples from statistics.
- Emit runtime statistics for measured samples and optional memory statistics when requested.
- Preserve timeout failures in both `failed` and aggregate samples.

**Non-Goals:**

- Changing generated tester payload format beyond what is necessary for profiling.
- Adding per-test timing breakdowns or histogram output.
- Introducing external benchmarking dependencies.
- Guaranteeing cross-language memory measurements have identical precision.

## Decisions

### Share command preparation and runner execution

Factor the common body of `command_test` into helpers that validate the language, parse timeout flags, load and verify the tester payload, scope tests, prepare the runner environment, and execute one run. `command_test` will remain a thin wrapper that prints the normalized runner result, while `command_profile` will call the same helper for warmup and measured trials. This keeps profile flag parity coupled to the existing test behavior instead of duplicating parser and runner logic.

Alternative considered: implement `profile` by shelling out to the CLI `test` command. That would be simple but would make timeout sample handling, memory measurement, and repeated compiled target setup harder to control.

### Aggregate at the command layer

Measure each full scoped run with `time.perf_counter_ns()` around the runner invocation, then compute population mean and standard deviation from measured samples. Warmup invocations run through the same path but are not appended to the sample list. This keeps generated testers unaware of profiling and works consistently across Python, JavaScript, TypeScript, C++, and Rust.

Alternative considered: instrument generated testers to emit timing per test. That could produce richer data, but it would touch every generator and conflict with the current strict JSON result contract.

### Treat timeout samples as measured failures

When the subprocess times out, reuse `result_for_timeout(scope_ids)` to produce the failed result and record the elapsed sample anyway. If `--memory` is requested, record whatever memory sample is available at timeout completion. The final `passed` and `failed` sets should reflect the most recent measured result, normalized through the same coverage rules as `test`.

Alternative considered: drop timeout samples from aggregates. The checkpoint explicitly requires timeout results to be included in statistics, so the implementation should measure elapsed timeout paths.

### Keep memory profiling best-effort and dependency-free

Use standard-library process resource data where available, with a fallback that reports the current process or child process maximum resident set size after each measured run. The output contract requires numeric `memory_kb.mean` and `memory_kb.std`, not a specific sampling strategy. Document the implementation as peak resident memory per measured run and avoid adding platform-specific dependencies.

Alternative considered: add an external profiler dependency. That would increase setup burden and can be unreliable across the target languages and execution environments.

### Preserve JSON result compatibility

`profile` output extends the result object with `runtime_ns` and optional `memory_kb`. Existing tests for `test` currently assert the exact three-key result shape, so profile-specific tests should parse profile output separately and assert the additional fields. `--list-tests` should still include runtime statistics only if the command actually performs measured profiling; otherwise it can behave as a list-only command with no measured samples.

Alternative considered: make `--list-tests` profile and list at the same time. That would diverge from the current `test --list-tests` contract and surprise users who expect discovery only.

## Risks / Trade-offs

- [Risk] Refactoring `command_test` could regress existing pass/fail behavior -> Mitigation: add focused tests around existing `test` selection, timeouts, and compiled paths after extracting helpers.
- [Risk] Memory measurement differs by OS or language runtime -> Mitigation: assert numeric shape and non-negative values rather than exact numbers.
- [Risk] Compiled targets may be recompiled for each trial, inflating runtime -> Mitigation: compile once per profile invocation when possible and run the compiled binary for each trial.
- [Risk] Total timeout semantics across multiple profile trials can be ambiguous -> Mitigation: apply `--total-timeout-ms` per trial, matching the existing `test` command semantics for one execution.

## Migration Plan

No data migration is required. Add the command, keep `test` behavior unchanged, and verify with the existing test suite plus new profile-focused tests. Rollback is removing the parser entry, `command_profile`, and profile helpers while leaving the shared test helpers intact if they are still useful.

## Open Questions

- Should future profile output include per-test timing or per-trial samples, or remain aggregate-only?
- Should memory statistics represent peak resident set size or delta over baseline when the platform exposes both?
