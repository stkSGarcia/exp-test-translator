## Context

`babel_code_goat.py` has `generate` and `test` commands. The `test` command runs the pre-generated tester once and emits `{"status","passed","failed"}`. There is no way to measure how fast or memory-hungry a solution is across multiple runs. The `profile` command fills this gap.

The existing `cmd_test` function handles the full test lifecycle: resolving the tester file, optionally compiling (C++/Rust), spawning the subprocess, collecting results from a temp JSON file, and handling timeouts. `profile` extends this pattern with multiple iterations and timing/memory aggregation.

## Goals / Non-Goals

**Goals:**
- Add `profile` sub-command with flags matching `test` plus `-n`, `--warmup`, and `--memory`
- Measure wall-clock time per trial from the orchestrator side, reporting `runtime_ns` mean/std
- Optionally measure peak memory per trial using `tracemalloc` (Python-subprocess) or `/usr/bin/time -v` (compiled), reporting `memory_kb` mean/std
- Include timeout results in statistics (trial still counts; the test IDs appear in `failed`)
- Error if the tester file is missing (same guard as `test`)

**Non-Goals:**
- Modifying tester file emitters — timing happens at the orchestrator level, not inside generated testers
- Per-test-case timing breakdown (only aggregate across the full trial)
- Windows `memory_kb` support (best-effort only; omit rather than error if unavailable)

## Decisions

### Decision: Time at orchestrator granularity, not inside generated testers

**Options:**
1. Inject timing/memory instrumentation into each tester emitter (Python, JS, TS, C++, Rust)
2. Time and measure each subprocess invocation from the orchestrator in Python

**Choice: Option 2 (orchestrator-level measurement)**

Rationale: avoids changes to five emitters (and their test suites), keeps the change scoped to `cmd_profile`. Granularity per trial (not per-test-case) is exactly what the spec requires. Wall-clock time via `time.perf_counter_ns()` is accurate enough for benchmarking purposes.

### Decision: Memory tracking via `tracemalloc` wrapper for Python; `/usr/bin/time -v` for compiled targets

For Python testers, inject a thin wrapper script that uses `tracemalloc` around the normal subprocess invocation. The wrapper prints peak memory to a sidecar file that the orchestrator reads.

For JavaScript/TypeScript, use Node's `--max-old-space-size` and capture `process.memoryUsage().heapUsed` via a wrapper env-var protocol — or fall back to `resource.getrusage` on the orchestrator side after a subprocess finishes.

For simplicity: use `resource.getrusage(RUSAGE_CHILDREN)` on POSIX (available everywhere CPython runs on Linux/macOS) to measure `ru_maxrss` (max RSS in KB on Linux, in bytes on macOS). No changes to any tester subprocess needed.

**Simplification choice:** Use `resource.getrusage(RUSAGE_CHILDREN)` diff before/after each `subprocess.run` call. This measures the peak RSS of the child process without injecting anything into testers. On macOS `ru_maxrss` is bytes; divide by 1024. On Linux it's already KB.

### Decision: Warmup runs precede timed trials; both code paths are identical

Warmup runs are full tester subprocess invocations. Their results count toward pass/fail (they're real runs), but their timing and memory samples are discarded. The first `k` runs are warmup; the next `n` runs are timed. Total subprocess invocations = `k + n`.

### Decision: cmd_profile re-uses cmd_test's subprocess machinery via a shared helper

Extract the "run one trial and return (passed, failed, duration_ns, maybe memory_kb)" logic into `_run_one_trial(...)`. `cmd_test` and `cmd_profile` both call it. This avoids duplicating the compile / subprocess / timeout / results-file logic.

Actually, given that cmd_test also handles compilation (C++/Rust) which should only happen once before trials begin — the compilation step is done once up-front in `cmd_profile`, and then the binary/command is reused across trials. The shared helper accepts a pre-resolved `cmd: list[str]` and handles only the subprocess invocation.

### Decision: Output format extends test JSON with timing/memory keys

```json
{
  "status": "pass"|"fail"|"error",
  "passed": [...],
  "failed": [...],
  "runtime_ns": {"mean": 12345.0, "std": 678.0}
}
```
With `--memory`:
```json
{
  ...,
  "memory_kb": {"mean": 4096.0, "std": 128.0}
}
```

`passed`/`failed` are from the final timed trial (consistent view). `runtime_ns` and `memory_kb` are computed across all `n` timed trials.

## Risks / Trade-offs

- **`resource` module is Unix-only** → On Windows, `--memory` silently omits `memory_kb`. The `resource` module is not available; fall back to no memory reporting rather than crashing.
- **Wall-clock time includes subprocess startup** → For fast solutions this overhead dominates. This is inherent to per-trial subprocess invocation and is acceptable for a benchmarking command (users can warm up via `--warmup`).
- **`RUSAGE_CHILDREN` gives max-RSS of all children since last wait** → Reset baseline before each trial by reading the delta. This is imprecise if other children have run. Acceptable for this use case.
- **`--warmup k` constraint `k < n`** → Validated at CLI parse time; error and exit non-zero with a descriptive message before running anything.

## Migration Plan

1. Add `_run_one_trial(cmd, env_base, results_file, all_ids, run_id, timeout_ms, measure_memory)` helper returning `(passed, failed, duration_ns, memory_kb_or_None)`.
2. Refactor `cmd_test` to delegate one call through the same helper (or leave it as-is and keep the helper private to `cmd_profile` — minimal-diff approach).
3. Add `cmd_profile(args)` implementing the loop over `warmup + n` trials.
4. Wire up the `profile` subparser in `main()`.
5. No existing public interfaces change.
