## MODIFIED Requirements

> Extends: babel-code-goat-cli

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, and `typescript` as target languages.

#### Scenario: Generate accepts a supported language
- **WHEN** `generate` is invoked with an existing tests directory, a valid entrypoint, and `--lang python`, `--lang javascript`, or `--lang typescript`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, or `tester.ts`

#### Scenario: Test rejects an unsupported language
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile accepts a supported language
- **WHEN** `profile <tests_dir> <solution_path> --lang python`, `--lang javascript`, or `--lang typescript` is invoked with a valid generated tester
- **THEN** the command validates the language and proceeds with profiling for that target

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile` is invoked with any `--lang` value other than `python`, `javascript`, or `typescript`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

## ADDED Requirements

> Extends: babel-code-goat-cli

### Requirement: Profile Requires Existing Tester
The system MUST require the expected tester file to already exist before running `profile`. The `profile` command MUST NOT create or modify the tester file. (adapts babel-code-goat-cli/add-babel-code-goat/test-requires-existing-tester)

#### Scenario: Python tester is missing
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is invoked and `<tests_dir>/tester.py` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: JavaScript tester is missing
- **WHEN** `profile <tests_dir> <solution_path> --lang javascript` is invoked and `<tests_dir>/tester.js` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: TypeScript tester is missing
- **WHEN** `profile <tests_dir> <solution_path> --lang typescript` is invoked and `<tests_dir>/tester.ts` is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Existing tester is preserved during profile
- **WHEN** `profile` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Profile Flags and Trial Selection
The `profile` command SHALL accept `-n <trials>`, `--warmup <k>`, and `--memory` flags. The default trial count MUST be `1`. Warmup count MUST default to `0` and MUST satisfy `k < n`. The `profile` command SHALL also accept the same selection, timeout, and tolerance flags as `test`: `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>`.

#### Scenario: Defaults run one measured trial
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is invoked without `-n` or `--warmup`
- **THEN** the command runs one measured profiling trial and no warmup trials

#### Scenario: Warmup count must be less than trials
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile lists tests without executing solution
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --list-tests` is invoked and discovery succeeds
- **THEN** the command reports all discovered test IDs in `passed`, reports an empty `failed` array, and does not include profiling statistics

#### Scenario: Profile runs one selected test
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --run <test_id>` is invoked and discovery succeeds
- **THEN** only the selected discovered test ID appears in `passed` or `failed` for each measured trial's active execution scope

#### Scenario: Profile tolerance matches test tolerance
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol 0.01` runs a discovered assertion comparing nested numeric values
- **THEN** the comparison uses the same effective numeric tolerance as `test --tol 0.01`

### Requirement: Profile JSON Output and Statistics
The `profile` command MUST print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object containing numeric `mean` and `std` fields computed from measured trials only. When `--memory` is provided, the JSON object MUST also include `memory_kb` with numeric `mean` and `std` fields computed from measured trials only. Warmup runs MUST be excluded from all aggregate statistics.

#### Scenario: All measured trials pass
- **WHEN** all active tests pass across all measured trials
- **THEN** `profile` prints `status` as `pass`, includes passing test IDs in `passed`, includes an empty `failed` array, includes `runtime_ns.mean` and `runtime_ns.std`, and exits with code 0

#### Scenario: At least one measured trial fails
- **WHEN** at least one active test fails during a measured trial
- **THEN** `profile` prints `status` as `fail`, includes failed test IDs in `failed`, includes passing test IDs in `passed`, includes `runtime_ns.mean` and `runtime_ns.std`, and exits with code 1

#### Scenario: Memory statistics are requested
- **WHEN** `profile <tests_dir> <solution_path> --lang <target_lang> --memory` completes measured trials
- **THEN** the output includes `memory_kb.mean` and `memory_kb.std` as numeric values

#### Scenario: Warmup samples are excluded
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 5 --warmup 2` completes
- **THEN** runtime and memory statistics are computed from the three measured trials after the two warmup trials

### Requirement: Profile Timeout Aggregation
The `profile` command SHALL apply `--timeout-ms <int>` as a per-test execution timeout and `--total-timeout-ms <int>` as a total timeout for each trial's active execution scope. Timed-out tests and discovered tests not executed because the total timeout is exhausted MUST appear in `failed`, and their timing and memory samples MUST be included in aggregate statistics.

#### Scenario: Per-test timeout is included in statistics
- **WHEN** an active test exceeds `--timeout-ms <int>` during a measured profile trial
- **THEN** the test ID appears in `failed` and that timed-out execution contributes to `runtime_ns` and, when requested, `memory_kb`

#### Scenario: Total timeout is included in statistics
- **WHEN** `--total-timeout-ms <int>` is exhausted before all active tests complete during a measured profile trial
- **THEN** the current and remaining active test IDs appear in `failed` and the timed-out trial contributes to `runtime_ns` and, when requested, `memory_kb`

#### Scenario: Warmup timeout does not affect statistics
- **WHEN** a timeout occurs during a warmup run before measured trials begin
- **THEN** the timed-out warmup run is excluded from `runtime_ns` and, when requested, `memory_kb`
