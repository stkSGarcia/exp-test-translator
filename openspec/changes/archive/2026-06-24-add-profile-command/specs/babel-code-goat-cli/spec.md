## MODIFIED Requirements

### Requirement: Supported command interface
The system SHALL provide a root-level `babel_code_goat.py` CLI with `generate <tests_dir> --entrypoint <entrypoint> --lang <target_lang> [flags...]`, `test <solution_path> <tests_dir> --lang <target_lang> [flags...]`, and `profile <tests_dir> <solution_path> --lang <target_lang> [flags...]` commands. The system MUST accept only `python`, `javascript`, `typescript`, `cpp`, and `rust` as target languages. The `test` command MUST accept `--tol <float>` to set the default numeric tolerance for comparisons where tolerance is applicable. The `test` command MUST accept `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`. The `profile` command MUST accept `-n <trials>`, `--warmup <k>`, `--memory`, `--tol <float>`, `--list-tests`, `--run <test_id>`, `--timeout-ms <int>`, and `--total-timeout-ms <int>`.

#### Scenario: Generate accepts supported language
- **WHEN** the user runs `generate` with an existing tests directory, an entrypoint, and `--lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command succeeds if the tests can be discovered and the tester file can be written

#### Scenario: Unsupported language is rejected
- **WHEN** the user runs `generate`, `test`, or `profile` with any `--lang` value other than `python`, `javascript`, `typescript`, `cpp`, or `rust`
- **THEN** the command exits non-zero

#### Scenario: Test accepts default tolerance
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Test accepts discovery listing
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --list-tests`
- **THEN** the command uses discovery-listing behavior instead of executing the solution

#### Scenario: Test accepts single test selection
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --run tests.py:2`
- **THEN** the command limits execution and reporting to the discovered test with ID `tests.py:2`

#### Scenario: Test accepts timeout controls
- **WHEN** the user runs `test <solution_path> <tests_dir> --lang python --timeout-ms 100 --total-timeout-ms 500`
- **THEN** the command applies the requested per-test and total-run timeout limits

#### Scenario: Profile accepts supported language
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python`, `--lang javascript`, `--lang typescript`, `--lang cpp`, or `--lang rust`
- **THEN** the command profiles the selected solution with the generated tester for that language

#### Scenario: Profile accepts default tolerance
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --tol 0.001`
- **THEN** the command uses `0.001` as the default tolerance for applicable numeric comparisons in discovered tests

#### Scenario: Profile accepts discovery listing
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests`
- **THEN** the command uses discovery-listing behavior instead of executing the solution for profiling

#### Scenario: Profile accepts single test selection
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:2`
- **THEN** the command limits profiling and reporting to the discovered test with ID `tests.py:2`

#### Scenario: Profile accepts timeout controls
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 100 --total-timeout-ms 500`
- **THEN** the command applies the requested per-test and total-run timeout limits during profiling

#### Scenario: Profile accepts trial and warmup controls
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 5 --warmup 2`
- **THEN** the command executes warmup runs and measured trials using those counts

#### Scenario: Profile accepts memory measurement
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory`
- **THEN** the command includes memory measurement in the profiling result

## ADDED Requirements

### Requirement: Profile command requires generated tester
The `profile` command SHALL require the expected tester file for the selected language to already exist in `<tests_dir>`. The `profile` command MUST NOT create or modify any tester file.

#### Scenario: Missing Python tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` and `<tests_dir>/tester.py` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing JavaScript tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang javascript` and `<tests_dir>/tester.js` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing TypeScript tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang typescript` and `<tests_dir>/tester.ts` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing C++ tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang cpp` and `<tests_dir>/tester.cpp` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Missing Rust tester errors for profile
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang rust` and `<tests_dir>/tester.rs` is missing
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile trial validation
The `profile` command SHALL default to one measured trial when `-n` is omitted. The `profile` command MUST reject `-n <trials>` values less than `1`. The `profile` command MUST default to zero warmup runs when `--warmup` is omitted. The `profile` command MUST reject `--warmup <k>` values less than `0` and values where `k >= n`.

#### Scenario: Profile defaults to one measured trial
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` without `-n`
- **THEN** the command records statistics from one measured trial

#### Scenario: Profile rejects zero trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 0`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile rejects warmup equal to trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 3`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile rejects warmup greater than trials
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 3 --warmup 4`
- **THEN** stdout is exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile output statistics
The `profile` command SHALL print exactly one line to stdout containing a JSON object with at least the keys `status`, `passed`, `failed`, and `runtime_ns`. The `runtime_ns` value MUST be an object with numeric `mean` and `std` keys computed from measured trial runtimes. When `--memory` is provided, the output MUST also include `memory_kb` as an object with numeric `mean` and `std` keys computed from measured trial memory observations. Warmup runs MUST be excluded from `runtime_ns` and `memory_kb` statistics.

#### Scenario: Passing profile reports runtime statistics
- **WHEN** every in-scope measured trial passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, all in-scope test IDs in `passed`, no test IDs in `failed`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Failing profile reports runtime statistics
- **WHEN** at least one in-scope measured trial fails and no harness error prevents reporting
- **THEN** stdout contains one JSON line with `status` set to `fail`, passing test IDs in `passed`, failing test IDs in `failed`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Memory profile reports memory statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --memory`
- **THEN** stdout contains one JSON line with `memory_kb.mean` and `memory_kb.std` as numbers

#### Scenario: Profile without memory omits memory statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python` without `--memory`
- **THEN** stdout contains one JSON line without a `memory_kb` key

#### Scenario: Warmup runs are excluded from statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python -n 2 --warmup 1`
- **THEN** `runtime_ns.mean` and `runtime_ns.std` are computed from the two measured trials and not from the warmup run

### Requirement: Profile selection behavior
The `profile --list-tests` command SHALL perform discovery and generated-tester consistency validation without executing the supplied solution. If discovery succeeds, the command MUST output `status` set to `pass`, `passed` containing all discovered test IDs in discovery order, `failed` as an empty array, and `runtime_ns` aggregate statistics with numeric `mean` and `std` values. If discovery fails or generated-tester consistency validation fails, the command MUST use the standard error result. The `profile --run <test_id>` command SHALL profile only the discovered test whose ID exactly matches `<test_id>`. If `<test_id>` is not discovered, the command MUST output the standard error result and exit `2`.

#### Scenario: Profile list-tests reports discovered IDs without solution execution
- **WHEN** the user runs `profile <tests_dir> <missing_solution_path> --lang python --list-tests`
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` containing all discovered IDs, `failed` set to `[]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile list-tests reports discovery error
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --list-tests` and discovery fails
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

#### Scenario: Profile run selects one passing test
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:2` and that selected test passes
- **THEN** stdout contains one JSON line with `status` set to `pass`, `passed` set to `["tests.py:2"]`, `failed` set to `[]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile run selects one failing test
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:3` and that selected test fails
- **THEN** stdout contains one JSON line with `status` set to `fail`, `passed` set to `[]`, `failed` set to `["tests.py:3"]`, and `runtime_ns.mean` and `runtime_ns.std` as numbers

#### Scenario: Profile run rejects unknown test ID
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --run tests.py:999`
- **THEN** stdout contains exactly `{"status":"error","passed":[],"failed":[]}` followed by a newline and the command exits `2`

### Requirement: Profile timeout statistics
The `profile --timeout-ms <int>` option SHALL bound each in-scope test's execution time during each profile run. The `profile --total-timeout-ms <int>` option SHALL bound the total execution time for all in-scope tests during each profile run. Timed-out tests and in-scope tests that are not executed because the total timeout has been exhausted MUST appear in `failed`. Timeout observations from measured trials MUST be included in the `runtime_ns` statistics and, when `--memory` is provided, in the `memory_kb` statistics.

#### Scenario: Per-test timeout is included in profile statistics
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 50` and one in-scope test exceeds 50 milliseconds during a measured trial
- **THEN** that test ID appears in `failed` and the timed-out run contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Total timeout marks remaining profile tests failed
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --total-timeout-ms 100` and total execution time is exhausted before all in-scope tests execute during a measured trial
- **THEN** each not-executed in-scope test ID appears in `failed` and the measured run contributes to `runtime_ns.mean` and `runtime_ns.std`

#### Scenario: Timeout memory observation is included
- **WHEN** the user runs `profile <tests_dir> <solution_path> --lang python --timeout-ms 50 --memory` and one in-scope test times out during a measured trial
- **THEN** the timed-out run contributes to `memory_kb.mean` and `memory_kb.std`
