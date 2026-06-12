## MODIFIED Requirements

### Requirement: CLI Commands and Language Validation
The system SHALL provide `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages.

#### Scenario: Generate accepts a supported language
- **WHEN** `generate` is invoked with an existing tests directory, a valid entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command validates the language and proceeds with generation for that target

#### Scenario: Generate rejects an unsupported language
- **WHEN** `generate` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero and does not create or modify `tester.py`, `tester.js`, `tester.ts`, `tester.cpp`, or `tester.rs`

#### Scenario: Test rejects an unsupported language
- **WHEN** `test` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile rejects an unsupported language
- **WHEN** `profile` is invoked with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

## ADDED Requirements

### Requirement: Profile Requires Existing Tester
The `profile` command MUST require the expected tester file to already exist before profiling. The expected tester filename MUST be `tester.py` for `python`, `tester.js` for `javascript`, `tester.ts` for `typescript`, `tester.cpp` for `cpp`, and `tester.rs` for `rust`. The `profile` command MUST NOT create or modify the tester file.

#### Scenario: Profile errors when tester is missing
- **WHEN** `profile <tests_dir> <solution_path> --lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust` is invoked and the expected tester file for that language is missing
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line, exits with code 2, and leaves the expected tester file absent

#### Scenario: Existing tester is preserved during profile
- **WHEN** `profile` is invoked and the expected tester file exists
- **THEN** the tester file content remains unchanged after the command exits

### Requirement: Profile Flags and Selection Parity
The `profile` command SHALL accept `-n <trials>`, `--warmup <k>`, `--memory`, `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, `--total-timeout-ms <int>`, and `--tol <float>` flags. The default trial count MUST be `1`, the default warmup count MUST be `0`, trial count MUST be a positive integer, warmup count MUST be a non-negative integer, and warmup count MUST satisfy `k < n`. The `--list-tests`, `--run`, `--timeout-ms`, `--total-timeout-ms`, and `--tol` flags MUST match the validation and selection semantics of `test`.

#### Scenario: Profile uses default trial settings
- **WHEN** `profile <tests_dir> <solution_path> --lang python` is invoked without `-n` or `--warmup`
- **THEN** the command profiles one measured trial with zero warmup trials

#### Scenario: Profile rejects invalid trial count
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 0` or `-n nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile rejects invalid warmup count
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3`, `--warmup -1`, or `--warmup nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile list tests reports discovered IDs
- **WHEN** `profile <tests_dir> <solution_path> --lang python --list-tests` is invoked and discovery succeeds
- **THEN** the command prints a single JSON line with `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` equal to `[]`, no runtime or memory statistics, and exits with code 0

#### Scenario: Profile list tests does not execute solution code
- **WHEN** `profile <tests_dir> <solution_path> --lang python --list-tests` is invoked for a solution that would fail or time out if executed and discovery succeeds
- **THEN** the command reports the discovered IDs as passing discovery without invoking the solution entrypoint

#### Scenario: Profile run selects one test
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run tests.py:2` is invoked and the discovered test with ID `tests.py:2` passes
- **THEN** the command profiles only `tests.py:2` and the JSON result includes `passed` equal to `["tests.py:2"]` and `failed` equal to `[]`

#### Scenario: Unknown profile selected test ID errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --run missing.py:1` is invoked and no discovered test has ID `missing.py:1`
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile list and run flags conflict
- **WHEN** `profile <tests_dir> <solution_path> --lang python --list-tests --run tests.py:1` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Profile tolerance flag applies
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol 0.01` runs a discovered assertion comparing `[1.0, {"x": 2.005}]` with `[1.0, {"x": 2.0}]`
- **THEN** the comparison passes because the nested float difference is within the default tolerance

#### Scenario: Invalid profile tolerance errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --tol nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

### Requirement: Profile JSON Output and Statistics
For normal profiling runs, the `profile` command MUST print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object with numeric `mean` and `std` fields computed over measured trials in nanoseconds. If `--memory` is provided, the JSON object MUST also include `memory_kb` with numeric `mean` and `std` fields computed over measured trials in kilobytes. Warmup trials MUST be excluded from `runtime_ns` and `memory_kb` statistics. Standard deviation MUST be the population standard deviation, and a single measured trial MUST have `std` equal to `0`.

#### Scenario: Profile reports runtime statistics for passing tests
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 1` runs one discovered passing test
- **THEN** the command prints a single JSON line with `status` set to `pass`, the test ID in `passed`, `failed` equal to `[]`, and `runtime_ns` containing numeric `mean` and `std` fields

#### Scenario: Profile reports failing tests
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 2` runs a discovered test that fails in at least one measured trial
- **THEN** the command prints a single JSON line with `status` set to `fail`, that test ID in `failed`, and `runtime_ns` containing numeric `mean` and `std` fields

#### Scenario: Profile excludes warmup trials from statistics
- **WHEN** `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 1` succeeds
- **THEN** `runtime_ns.mean` and `runtime_ns.std` are computed from the final two measured trials and exclude the first warmup trial

#### Scenario: Profile reports memory statistics when requested
- **WHEN** `profile <tests_dir> <solution_path> --lang python --memory` succeeds
- **THEN** the command prints a single JSON line that includes `memory_kb` with numeric `mean` and `std` fields

#### Scenario: Profile omits memory statistics by default
- **WHEN** `profile <tests_dir> <solution_path> --lang python` succeeds without `--memory`
- **THEN** the command output does not include `memory_kb`

### Requirement: Profile Timeout Statistics
The `profile` command SHALL apply `--timeout-ms <int>` to each selected executable test attempt and `--total-timeout-ms <int>` to each trial execution set. Timeout values MUST be positive integers. After discovery succeeds, timed-out tests and selected tests not executed because the total timeout elapsed MUST appear in `failed`, and measured timeout trial data MUST be included in `runtime_ns` and `memory_kb` statistics when those statistics are emitted.

#### Scenario: Profile per-test timeout fails and is measured
- **WHEN** `profile <tests_dir> <solution_path> --lang python --timeout-ms 10` runs a discovered test whose entrypoint invocation does not complete within 10 milliseconds
- **THEN** that discovered test ID appears in `failed`, the command exits with code 1, and the timeout trial contributes to `runtime_ns`

#### Scenario: Profile total timeout fails not-executed selected tests and is measured
- **WHEN** `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 10` discovers three selected tests and the total timeout elapses before all three tests are executed
- **THEN** every selected discovered test that was not executed because of the elapsed total timeout appears in `failed`, and the timeout trial contributes to `runtime_ns`

#### Scenario: Invalid profile per-test timeout errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --timeout-ms nope` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2

#### Scenario: Non-positive profile total timeout errors
- **WHEN** `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 0` is invoked
- **THEN** the command prints exactly `{"status":"error","passed":[],"failed":[]}` as one stdout line and exits with code 2
