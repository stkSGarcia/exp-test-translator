## Why

Users need more than pass/fail results when benchmarking solutions — they need runtime and memory statistics across multiple trials so they can compare implementations. The `profile` command fills this gap by running a solution repeatedly and reporting mean/std metrics in structured JSON.

## What Changes

- **New `profile` sub-command**: `profile <tests_dir> <solution_path> --lang <target_lang>` runs the pre-generated tester file N times and emits JSON performance statistics.
- `-n <trials>` flag (default `1`): number of timed trials to run.
- `--warmup <k>` flag (default `0`): number of warm-up runs excluded from statistics; requires `k < n`.
- `--memory` flag: additionally collect and report memory usage statistics.
- `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, `--tol` flags: same semantics as the `test` command.
- JSON output includes `status`, `passed`, `failed`, and `runtime_ns` (`mean`/`std`); adds `memory_kb` (`mean`/`std`) when `--memory` is specified.
- `profile` errors if the tester file for the requested language is missing (same precondition as `test`).
- Timeout results are included in aggregated statistics; timed-out tests appear in `failed`.

## Capabilities

### New Capabilities

- `profile-command`: The `profile` sub-command — repeated execution of the tester, trial/warmup management, runtime and memory aggregation, and structured JSON output.

### Modified Capabilities

## Impact

- `babel_code_goat.py`: add `profile` subparser and implementation alongside the existing `test` command logic.
- No new dependencies expected (memory tracking via `resource` module on POSIX / `tracemalloc` as fallback).
