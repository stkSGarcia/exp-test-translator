## ADDED Requirements

> Extends: python-test-discovery/add-mutation-style-test-discovery

### Requirement: Compiled target language selection
The CLI SHALL support `--lang cpp` and `--lang rust` anywhere a supported language is accepted by `generate` and `test`.

#### Scenario: Generate accepts compiled languages
- **GIVEN** a Python test directory with at least one discoverable test case
- **WHEN** the user runs `generate` with `--lang cpp` or `--lang rust`
- **THEN** the command succeeds and writes the corresponding compiled-target tester file

#### Scenario: Test accepts compiled languages
- **GIVEN** a solution file, a Python test directory, and the corresponding generated compiled-target tester file
- **WHEN** the user runs `test` with `--lang cpp` or `--lang rust`
- **THEN** the command treats the language as supported and attempts the compiled-target test workflow

### Requirement: Compiled tester files
The generator SHALL write `tester.cpp` for C++ targets and `tester.rs` for Rust targets, and each file SHALL contain the discovered test cases needed to execute the requested entrypoint from a single-file solution.

#### Scenario: C++ tester is generated
- **GIVEN** discovered Python tests for an entrypoint
- **WHEN** the user runs `generate` with `--lang cpp`
- **THEN** `tester.cpp` is created in the test directory

#### Scenario: Rust tester is generated
- **GIVEN** discovered Python tests for an entrypoint
- **WHEN** the user runs `generate` with `--lang rust`
- **THEN** `tester.rs` is created in the test directory

### Requirement: Compiled generate-to-test workflow
The `test` command SHALL compile and execute C++17-or-newer C++ solutions through `tester.cpp` and Rust 1.70-or-newer Rust solutions through `tester.rs`, returning the same JSON result envelope used by existing targets.

#### Scenario: C++ solution executes after generation
- **GIVEN** `tester.cpp` exists for the selected tests and a compatible single-file C++ solution is provided
- **WHEN** the user runs `test --lang cpp`
- **THEN** the command compiles and runs the C++ harness and reports passed and failed test ids in the standard JSON result

#### Scenario: Rust solution executes after generation
- **GIVEN** `tester.rs` exists for the selected tests and a compatible single-file Rust solution is provided
- **WHEN** the user runs `test --lang rust`
- **THEN** the command compiles and runs the Rust harness and reports passed and failed test ids in the standard JSON result

### Requirement: Compiled value model parity
The generated C++ and Rust testers SHALL support all value types and comparison behaviors accepted by Python test discovery, including `None`/`null` values anywhere in supported nested structures.

#### Scenario: Nested null values compare correctly
- **GIVEN** a discovered test case whose arguments or expected value contain `None` inside a list, map, set-like value, counter-like value, or nested combination
- **WHEN** the user generates and runs C++ or Rust tests
- **THEN** the generated tester represents the nullable position idiomatically and compares the result without losing the null value

#### Scenario: Collections map to target types
- **GIVEN** discovered Python tests containing lists or tuples, dictionaries, sets, counters, defaultdict-style mappings, strings, booleans, integers, floats, and decimals
- **WHEN** the user generates C++ or Rust tests
- **THEN** the generated tester maps those values to target-language constructs that can be passed to the solution and compared against expected results

#### Scenario: Exception-style tests are preserved
- **GIVEN** a discovered test case that expects the entrypoint to raise an exception
- **WHEN** the user runs the generated C++ or Rust tester
- **THEN** the tester treats a C++ exception or Rust panic as satisfying the expected exception case

### Requirement: Missing compiled tester errors
The `test` command SHALL fail with the standard error JSON result and exit code `2` when `tester.cpp` or `tester.rs` is missing for the selected compiled target, and it SHALL NOT generate a tester as part of `test`.

#### Scenario: Missing C++ tester fails
- **GIVEN** a test directory without `tester.cpp`
- **WHEN** the user runs `test --lang cpp`
- **THEN** the command outputs `{"status":"error","passed":[],"failed":[]}` and exits with code `2`

#### Scenario: Missing Rust tester fails
- **GIVEN** a test directory without `tester.rs`
- **WHEN** the user runs `test --lang rust`
- **THEN** the command outputs `{"status":"error","passed":[],"failed":[]}` and exits with code `2`

### Requirement: Rust deque test handling
The Rust target SHALL skip discovered cases that require Python `collections.deque` behavior when no direct generated Rust mapping is available, and the skip SHALL NOT cause unrelated Rust cases to fail.

#### Scenario: Rust skips deque cases
- **GIVEN** discovered tests include both deque-dependent cases and non-deque cases
- **WHEN** the user generates and runs Rust tests
- **THEN** deque-dependent cases are omitted or marked skipped while non-deque cases still execute normally
