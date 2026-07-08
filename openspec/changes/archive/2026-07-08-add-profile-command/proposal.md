## Why

Users can currently run generated test harnesses, but they do not have a first-class way to measure solution performance across repeated executions. A dedicated `profile` command gives the CLI a repeatable JSON profiling surface for runtime and optional memory measurements while preserving the existing test selection and timeout behavior.

## What Changes

- Add a root-level `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` command.
- Require `generate` output to exist before profiling by erroring when the tester file for the requested language is missing.
- Support repeated trials with `-n <trials>`, warmup exclusion with `--warmup <k>`, and optional memory aggregation with `--memory`.
- Reuse the `test` command selection, timeout, and tolerance flags: `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- Print JSON containing `status`, `passed`, `failed`, and `runtime_ns` mean/std, plus `memory_kb` mean/std when requested.
- Include timed-out test results in failed-test reporting and in aggregate runtime and memory statistics.

## Capabilities

### New Capabilities
- `profile-command`: Covers the CLI profiling command, trial and warmup handling, statistics output, memory profiling, generated tester validation, and parity with existing test selection and timeout flags.

### Modified Capabilities
- None.

## Related Work

### Related Changes
- None surfaced by the shallow KG search.

### Related Specs
- `babel-code-goat-cli/support-rich-python-test-comparisons`: Describes the root-level CLI command surface and rich test comparison behavior. This change extends that command surface with profiling while preserving JSON-style command results and language-aware tester execution.
- `async-test-execution-controls/support-async-test-selection-timeouts`: Defines selected test execution, per-test and total timeout controls, and timeout result reporting. This change reuses those execution controls so profiling can select the same tests and aggregate timed-out runs consistently.

## Impact

- Affects the root CLI parser and command dispatch for `babel_code_goat.py`.
- Affects generated tester discovery and test execution flow used by the existing `test` command.
- Adds runtime statistics aggregation and optional memory measurement to the command output contract.
- Requires tests for profiling validation, repeated trial aggregation, warmup exclusion, memory output, flag parity, and timeout inclusion.
