## 1. CLI Plumbing

- [x] 1.1 Add `profile` subparser in `main()` with positional args `tests_dir` and `solution_path`, and flags `--lang`, `--tol`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, `-n`, `--warmup`, `--memory`
- [x] 1.2 Validate `--warmup < n` at parse time; exit non-zero with a descriptive stderr message if violated

## 2. Single-Trial Helper

- [x] 2.1 Add `_run_one_trial(cmd, env, results_file, all_ids, run_id, total_timeout_ms, measure_memory)` that runs the subprocess, reads the results JSON, handles timeout, and returns `(passed, failed, duration_ns, memory_kb_or_None)`
- [x] 2.2 Implement wall-clock timing using `time.perf_counter_ns()` around the subprocess call
- [x] 2.3 Implement memory measurement using `resource.getrusage(resource.RUSAGE_CHILDREN)` delta (POSIX only); return `None` on platforms where `resource` is unavailable

## 3. cmd_profile Implementation

- [x] 3.1 Add `cmd_profile(args)` that validates tester file existence, handles `--list-tests` early exit (return `runtime_ns: {mean:0.0, std:0.0}`), and resolves/compiles the command once before trials
- [x] 3.2 Run `warmup` un-timed trials (discard timing/memory, still record final pass/fail)
- [x] 3.3 Run `n` timed trials collecting `(passed, failed, duration_ns, memory_kb_or_None)` per trial
- [x] 3.4 Compute mean and population std-dev for `runtime_ns` over all `n` duration samples
- [x] 3.5 Compute mean and population std-dev for `memory_kb` over all `n` samples when `--memory` is set; include `memory_kb` in output only if `--memory` was passed
- [x] 3.6 Set `passed`/`failed` from the last timed trial; derive `status` as `"pass"`, `"fail"`, or `"error"`; emit JSON and return appropriate exit code

## 4. Tests

- [x] 4.1 Add test cases in `test_checkpoint7.py` (or a new file) covering: missing tester → error JSON; basic profile with `-n 1`; `-n 3` produces `runtime_ns` with three samples; `--warmup` rejection when `k >= n`; `--memory` adds `memory_kb` to output; `--list-tests` returns all IDs with zero runtime; `--run` filters to single test
