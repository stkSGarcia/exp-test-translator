## Why

The CLI can already translate tests and run pass/fail checks, but it cannot measure solution performance in the same harness. A `profile` command gives users repeatable runtime and optional memory measurements while preserving the existing `generate -> test` workflow constraints.

## What Changes

- Add a root-level `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `generate` to have run first by erroring when the target language tester file is missing.
- Support repeated profiling with `-n <trials>`, `--warmup <k>`, and validation that `k < n`.
- Support optional memory profiling with `--memory`.
- Reuse `test` selection, timeout, and tolerance flags: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Emit one JSON object containing `status`, `passed`, `failed`, and `runtime_ns` mean/std statistics, plus `memory_kb` mean/std when requested.
- Exclude warmup runs from statistics while including timeout samples in the aggregate statistics and failed test list.

## Related Work

### Related Changes

- No related intent nodes were returned by the shallow KG search.

### Related Specs

- `babel-code-goat-cli/add-babel-code-goat`: Defines the root `babel_code_goat.py` CLI, the `generate -> test` workflow, language-specific tester file prerequisites, JSON result shape, and pass/fail coverage rule. This change reuses those contracts for `profile` so profiling behaves like another execution mode over generated testers.
- `babel-code-goat-cli/add-async-test-selection-timeouts`: Extends the test command with async execution, `--list-tests`, `--run`, per-test timeout, and total timeout behavior. This change adapts those flags and timeout semantics for profiling, with the added requirement that timed-out samples still contribute to statistics.
- `compiled-language-targets/add-cpp-rust-targets`: Adds C++ and Rust tester generation and execution support by extending the same CLI shape. This change keeps `profile` language handling aligned with all target languages supported by `generate` and `test`.

## Capabilities

### New Capabilities

- `profile-command`: Profiling command behavior, repeated trials, warmup handling, optional memory statistics, test flag parity, and aggregate JSON output.

### Modified Capabilities

- None.

## Impact

- Affected CLI surface: `babel_code_goat.py` argument parsing and command dispatch.
- Affected execution paths: language-specific tester execution used by `test`, including timeout, selection, tolerance, and compiled target handling.
- Affected output contracts: JSON result payloads for profiling include aggregate runtime and optional memory statistics.
- Affected tests: CLI coverage should add profile command success, validation, missing tester, selection, warmup, memory, and timeout aggregation cases.
