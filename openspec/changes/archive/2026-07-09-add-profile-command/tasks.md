## 1. Shared Execution Preparation

- [x] 1.1 In `babel_code_goat.py`, extract the common `command_test` setup into helpers for language validation, timeout parsing, tester file lookup, payload extraction, discovery verification, scoped test selection, and list-tests handling. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 1.2 In `babel_code_goat.py`, extract runner environment and one-run execution into a reusable helper that preserves Python, JavaScript, TypeScript, C++, and Rust behavior. [extends compiled-language-targets/add-cpp-rust-targets]
- [x] 1.3 Keep `command_test` behavior unchanged by routing it through the new helpers and preserving existing JSON output and exit codes. [extends babel-code-goat-cli/add-async-test-selection-timeouts]

## 2. Profile Command

- [x] 2.1 Add `profile <tests_dir> <solution_path> --lang <target_lang>` to `build_parser()` with `-n`, `--warmup`, `--memory`, `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol`.
- [x] 2.2 Implement `command_profile` in `babel_code_goat.py` so it errors on unsupported languages, missing generated tester files, invalid `--run`, invalid timeout flags, invalid `-n`, and `--warmup >= -n`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 2.3 Run warmup executions before measured executions and exclude warmup samples from runtime and memory aggregate statistics.
- [x] 2.4 Compute `runtime_ns.mean` and `runtime_ns.std` from measured trials using numeric values and include them in the profile JSON output.
- [x] 2.5 Implement `--memory` measurement without external dependencies and include `memory_kb.mean` and `memory_kb.std` only when requested.
- [x] 2.6 Include timeout samples from `--timeout-ms` and `--total-timeout-ms` in aggregate statistics while listing timed-out or not-executed tests in `failed`. [extends babel-code-goat-cli/add-async-test-selection-timeouts]

## 3. Verification

- [x] 3.1 Add tests in `tests/test_babel_code_goat.py` for profile success output, default single trial, `-n`, warmup exclusion shape, and optional memory fields.
- [x] 3.2 Add tests in `tests/test_babel_code_goat.py` for missing tester errors, unsupported language, invalid warmup/trial values, `--list-tests`, `--run`, and `--tol` parity with `test`. [extends babel-code-goat-cli/add-babel-code-goat]
- [x] 3.3 Add timeout profile tests proving per-test and total timeout failures appear in `failed` and still produce runtime statistics. [extends babel-code-goat-cli/add-async-test-selection-timeouts]
- [x] 3.4 Run `uv run pytest` and confirm the full suite passes.
