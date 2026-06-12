## 1. Shared CLI Preparation

- [x] 1.1 Add a `profile` subcommand with positional arguments in the required order: `<tests_dir> <solution_path>`.
- [x] 1.2 Add `profile` arguments for `--lang`, `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- [x] 1.3 Extract shared validation helpers from `command_test` for language validation, tester metadata loading, tolerance parsing, timeout parsing, discovery, `--list-tests`, and `--run` selection.
- [x] 1.4 Add trial and warmup parsing that enforces `n > 0`, `k >= 0`, and `k < n`, returning the standard error JSON for invalid values.

## 2. Profile Execution and Statistics

- [x] 2.1 Implement `command_profile` using the shared validation/discovery path and preserving `test` behavior unchanged.
- [x] 2.2 Implement a profile trial loop that runs `n` total trials, treats the first `warmup` trials as discarded warmups, and measures the remaining selected execution sets with `time.perf_counter_ns()`.
- [x] 2.3 Merge measured trial results so any measured failure places the test ID in `failed`, and IDs that never fail remain in `passed`.
- [x] 2.4 Add mean and population-standard-deviation helpers for `runtime_ns` with `std` equal to `0` for one measured sample.
- [x] 2.5 Implement optional `--memory` sampling with standard-library facilities and emit `memory_kb.mean` and `memory_kb.std` only when requested.
- [x] 2.6 Ensure per-test and total timeout failures from measured trials are included in `failed` and in emitted runtime and memory statistics.
- [x] 2.7 Return exit codes matching result status: 0 for `pass`, 1 for `fail`, and 2 for command errors.

## 3. Contract Tests

- [x] 3.1 Add CLI tests for unsupported `profile --lang`, missing tester files, and preserving existing tester contents.
- [x] 3.2 Add CLI tests for default trial settings and invalid `-n` / `--warmup` combinations.
- [x] 3.3 Add CLI tests for `profile --list-tests`, discovery-only behavior, `--run`, unknown selected IDs, and `--list-tests` plus `--run` conflict.
- [x] 3.4 Add CLI tests proving `profile --tol` uses the same default tolerance semantics as `test` and invalid tolerance values error.
- [x] 3.5 Add CLI tests for runtime JSON shape, one-sample `std` equal to `0`, measured-trial failure aggregation, warmup exclusion, memory output with `--memory`, and memory omission without `--memory`.
- [x] 3.6 Add CLI tests for `--timeout-ms` and `--total-timeout-ms` profile failures contributing to failed IDs and runtime statistics.
- [x] 3.7 Add regression coverage that existing `test` command output and exit codes remain unchanged.

## 4. Verification

- [x] 4.1 Run the focused unittest suite for `tests/test_babel_code_goat.py`.
- [x] 4.2 Run `openspec status --change "add-profile-command"` and confirm all proposal artifacts are complete.
