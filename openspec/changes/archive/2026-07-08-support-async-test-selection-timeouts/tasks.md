## 1. CLI Discovery And Selection

- [x] 1.1 Add regression tests in `tests/test_babel_code_goat.py` for `test --list-tests` returning `status="pass"`, all discovered IDs in `passed`, and `failed=[]`. [extends `python-test-discovery/add-mutation-style-test-discovery`]
- [x] 1.2 Add regression tests in `tests/test_babel_code_goat.py` for `test --run <test_id>` reporting only the selected passing or failing ID. [extends `python-test-discovery/add-mutation-style-test-discovery`]
- [x] 1.3 Update `babel_code_goat.py` `build_parser` to accept `--list-tests`, `--run`, `--timeout-ms`, and `--total-timeout-ms` on the `test` subcommand.
- [x] 1.4 Update `babel_code_goat.py` `command_test` to validate tester payloads, return list-only results before runner execution, and filter in-scope tests for `--run`.
- [x] 1.5 Add `tests/test_babel_code_goat.py` coverage for unknown `--run <test_id>` returning the existing error result contract.

## 2. Async Target Execution

- [x] 2.1 Add Python async solution coverage in `tests/test_babel_code_goat.py` showing an awaited result passes and an async failure appears in `failed`. [extends `babel-code-goat-cli/support-rich-python-test-comparisons`]
- [x] 2.2 Update `babel_code_goat.py` `execute_python_tests` or `python_tester_source` so awaitable Python entrypoint results are driven to completion before assertions.
- [x] 2.3 Add JavaScript and TypeScript async solution coverage in `tests/test_babel_code_goat.py` confirming promise-returning entrypoints complete before result reporting. [extends `babel-code-goat-cli/support-rich-python-test-comparisons`]
- [x] 2.4 Verify `babel_code_goat.py` `javascript_tester_source` continues awaiting promise-like actual values for selected and full runs.

## 3. Timeout Accounting

- [x] 3.1 Add per-test timeout coverage in `tests/test_babel_code_goat.py` where a long-running selected test appears in `failed`.
- [x] 3.2 Add total-timeout coverage in `tests/test_babel_code_goat.py` where timed-out or not-executed in-scope test IDs appear in `failed`. [extends `babel-code-goat-cli/add-babel-code-goat`]
- [x] 3.3 Update `babel_code_goat.py` `command_test` subprocess execution to honor `--total-timeout-ms` and synthesize coverage-preserving failure results on timeout.
- [x] 3.4 Update Python and JavaScript/TypeScript generated runner logic in `babel_code_goat.py` to honor `--timeout-ms` per executable test where runtime support is available.
- [x] 3.5 Update compiled target execution in `babel_code_goat.py` to apply host-level timeout handling for C++ and Rust runner processes. [extends `compiled-targets/add-cpp-rust-targets`]

## 4. Verification

- [ ] 4.1 Run targeted pytest cases for CLI list, selection, async, and timeout behavior in `tests/test_babel_code_goat.py`.
- [ ] 4.2 Run the full `tests/test_babel_code_goat.py` suite, allowing existing compiler-dependent skips for unavailable C++ or Rust toolchains.
- [x] 4.3 Run `openspec status --change support-async-test-selection-timeouts` and confirm the proposal is complete and ready to apply.
