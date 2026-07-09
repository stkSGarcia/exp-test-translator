## 1. CLI Scope And Validation

- [x] 1.1 Extend `build_parser()` in `babel_code_goat.py` with `test --list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>` [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 1.2 Add validation in `command_test()` in `babel_code_goat.py` for positive timeout values and incompatible flag combinations, preserving the existing error result for invalid test scopes [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 1.3 Derive ordered in-scope test IDs from `discover_tests()` and the generated payload in `command_test()`, using existing loop-expanded and mutation-style IDs as the selection source [extends babel-code-goat-cli/support-loop-construct-tests] [extends babel-code-goat-cli/support-mutation-style-tests].
- [x] 1.4 Implement `--list-tests` in `command_test()` so it returns `status: "pass"`, all discovered IDs in `passed`, and `failed: []` without executing the solution [extends babel-code-goat-cli/add-babel-code-goat].

## 2. Generated Runner Controls

- [x] 2.1 Update Python tester generation in `babel_code_goat.py` to accept selected IDs, per-test timeout, total deadline, and to await awaitable entrypoint results before comparisons [extends babel-code-goat-cli/support-single-call-test-traceability].
- [x] 2.2 Update JavaScript and TypeScript tester generation in `babel_code_goat.py` to run tests through async functions, await promises/rejections, and enforce selected IDs and timeout controls [extends babel-code-goat-cli/support-single-call-test-traceability].
- [x] 2.3 Update C++ tester generation in `babel_code_goat.py` so selected IDs and timeout coverage are represented consistently for compiled execution [extends compiled-language-targets/add-cpp-rust-targets].
- [x] 2.4 Update Rust tester generation in `babel_code_goat.py` so selected IDs and timeout coverage are represented consistently for compiled execution [extends compiled-language-targets/add-cpp-rust-targets].

## 3. Timeout And Result Accounting

- [x] 3.1 Add shared result-accounting helpers in `babel_code_goat.py` that ensure every in-scope test appears exactly once in `passed` or `failed` after normal completion, per-test timeout, or total timeout [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 3.2 Enforce per-test timeouts so timed-out tests are failed while later in-scope tests may still run when the total deadline permits [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 3.3 Enforce total timeouts after discovery and tester validation, returning a valid result with timed-out or not-executed in-scope IDs in `failed` [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 3.4 Preserve compile failures, stale testers, malformed result JSON, and discovery failures as `status: "error"` cases in `command_test()` [extends compiled-language-targets/add-cpp-rust-targets].

## 4. Test Coverage

- [x] 4.1 Add `tests/test_babel_code_goat.py` coverage for `--list-tests`, unknown `--run`, and selected test execution across stable discovered IDs [extends babel-code-goat-cli/support-loop-construct-tests].
- [x] 4.2 Add `tests/test_babel_code_goat.py` coverage for async Python and JavaScript/TypeScript entrypoint values and asynchronous exceptions.
- [x] 4.3 Add `tests/test_babel_code_goat.py` coverage for `--timeout-ms` marking slow tests failed while preserving later test outcomes.
- [x] 4.4 Add `tests/test_babel_code_goat.py` coverage for `--total-timeout-ms` failing timed-out or not-executed tests per the result coverage rule [extends babel-code-goat-cli/add-babel-code-goat].
- [x] 4.5 Run `uv run pytest tests/test_babel_code_goat.py` and fix regressions.
