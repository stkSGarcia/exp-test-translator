## Context

`babel_code_goat.py` currently owns the full CLI surface, generated tester creation, tester payload validation, scoped execution, result parsing, timeout handling, and JSON output for `test`. The new `profile` command should sit beside `test` and reuse the same generated tester contract so users measure the same behavior they validate.

Profiling must run after `generate`, because tester files contain the discovered test payload and language-specific execution harness. The command needs repeated runs, optional warmup exclusion, optional memory measurements, and the same selection, tolerance, and timeout controls users already have on `test`.

## Goals / Non-Goals

**Goals:**

- Add `profile <tests_dir> <solution_path> --lang <target_lang>` without changing the existing `generate` or `test` contracts.
- Share validation and in-scope test selection behavior with `test`, including tester existence checks, discovery consistency checks, `--list-tests`, `--run`, `--tol`, and timeout validation.
- Produce deterministic JSON shape with `status`, `passed`, `failed`, `runtime_ns`, and optional `memory_kb`.
- Exclude warmup observations from aggregate statistics while still using warmup runs to exercise the same selected tests.
- Include timeout observations in the aggregate statistics and report timed-out tests as failed.

**Non-Goals:**

- Do not change generated tester file names or the `generate` command.
- Do not add per-test profiling detail to the public output; this change only requires aggregate mean/std values.
- Do not guarantee identical memory semantics across operating systems beyond reporting a best-effort kilobyte measurement for each measured run.
- Do not add new target languages.

## Decisions

1. Reuse the `test` command validation path before profiling.

   `profile` should extract the generated tester payload, rediscover tests, compare payload consistency, apply `--list-tests`/`--run`, and set the same environment values as `test`. This keeps correctness and profiling aligned. The alternative was to parse tester files and execute them directly without rediscovery, but that would weaken the existing stale-tester guard.

2. Add a shared execution result that can carry elapsed runtime and memory observations.

   The current `TesterRun` wrapper already reports process completion or timeout. Extend that execution boundary, or wrap it in a profiling helper, so every measured attempt records elapsed `perf_counter_ns()` duration. When `--memory` is requested, collect a best-effort peak-memory value in kilobytes for the tester process or scoped child process. The alternative was to instrument generated testers per language, but measuring at the command process boundary avoids changing every generated harness for this first profiling contract.

3. Use the same scoped execution strategy that `test` uses when timeout flags are present.

   For no timeout flags, `profile` can execute all in-scope tests through the generated tester just like `test`. With timeout flags, it should reuse the per-test scoped execution path so timeout failures and remaining not-executed tests are represented consistently. The alternative was to impose a single outer timeout around each trial, but that would diverge from `test --timeout-ms` and `--total-timeout-ms` semantics.

4. Compute aggregate statistics from measured, non-warmup observations.

   `-n` defines the number of measured trials, and `--warmup <k>` defines additional preliminary runs that are excluded from mean/std. `--warmup` must be lower than `n`, matching the requested validation rule. Use population standard deviation for deterministic behavior with one measured observation producing `0`. The alternative sample standard deviation would produce undefined or surprising output for the default `-n 1`.

5. Keep output status and exit code semantics parallel to `test`.

   A profile run exits `0` when all measured in-scope tests pass, `1` when any measured test fails or times out, and `2` for validation or harness errors. The JSON includes aggregate stats whenever profiling reaches measured execution. Errors that prevent profiling use the standard empty `passed`/`failed` shape plus zeroed stats only if the implementation needs a single output schema; otherwise validation errors may omit stats if the spec allows. For this change, the spec requires stats in normal profile output and keeps generated-tester/discovery errors on the standard error path.

## Risks / Trade-offs

- Memory measurement differs by platform and process model -> Report best-effort `memory_kb` only when requested and keep tests tolerant of exact values.
- Repeated compiled-language profiling may pay compile cost if each run recompiles -> Reuse existing compiled execution first for correctness, then optimize by separating compile and execute only if tests show unacceptable overhead.
- Timeout observations can dominate aggregate timing -> This is intentional because the requested behavior says timeout timing/memory data is included in statistics.
- Warmup semantics can be confused with total trial count -> Validate `--warmup < n` and document internally that `n` means measured trials, not total invocations.

## Migration Plan

1. Add the parser branch and `command_profile` behind the new subcommand.
2. Factor shared validation, environment setup, and selection helpers out of `command_test` only as needed.
3. Add profiling measurement and aggregation helpers.
4. Add focused tests for CLI parsing, generated-tester preconditions, JSON output shape, warmup exclusion, memory output presence, flag parity, and timeout inclusion.
5. Run the existing test suite to confirm `generate` and `test` behavior is unchanged.
