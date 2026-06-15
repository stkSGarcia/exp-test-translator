## 1. Discovery Environment

- [x] 1.1 Add a scoped discovery environment for supported parameter source assignments, loop variables, tuple/list unpacking, and simple index variables.
- [x] 1.2 Extend value and expression parsing so supported `Name`, subscript, unpacked, and starred argument references can resolve from the discovery environment.
- [x] 1.3 Validate unsupported assignments, imports, helper calls, mutation, and loop setup expressions with the existing discovery-error behavior unless the loop itself must become a failed loop test.

## 2. Loop Evaluation

- [x] 2.1 Implement `for ... in` loop evaluation over supported literals, constructor values, and environment references.
- [x] 2.2 Implement `enumerate(...)` and `range(len(...))` loop evaluation for the checkpoint parameterization forms.
- [x] 2.3 Implement finite `while` loop evaluation over supported comparison conditions and simple loop-state updates such as `i += 1`.
- [x] 2.4 Add nested-loop support that carries the active iteration path through recursive body discovery.
- [x] 2.5 Bound loop evaluation so zero-iteration, unsupported, or runaway loops produce failed loop tests without expanding body assertions.

## 3. Test Case Reporting

- [x] 3.1 Extend `PendingTest` and `TestCase` to represent loop tests with predetermined pass/fail outcomes and no entrypoint invocation.
- [x] 3.2 Update result aggregation for Python, JavaScript, and TypeScript test runs so loop tests are reported directly while assertion tests still execute through the existing runners.
- [x] 3.3 Ensure zero-iteration loop failures produce `status: "fail"`, exit code 1, and no reported assertion IDs from the unexecuted loop body.
- [x] 3.4 Preserve stdout/stderr expectations, tolerance metadata, typed exceptions, and single-call traceability for assertions discovered inside executed loop bodies.

## 4. ID Generation

- [x] 4.1 Update ID assignment to include active iteration paths for loop-body assertions, such as `tests.py:3:0` and `tests.py:3:1`.
- [x] 4.2 Generate nested loop IDs using outer iteration paths, such as `tests.py:3:0` for an inner loop and `tests.py:4:0:1` for its assertion.
- [x] 4.3 Preserve existing `#<n>` suffix behavior when multiple tests share the same source line and iteration path.
- [x] 4.4 Keep deterministic discovery and reporting order for loop tests, nested loop tests, and per-iteration assertion tests.

## 5. Verification

- [x] 5.1 Add discovery tests for `for ... in`, `enumerate`, `range(len(...))`, `while`, nested loops, and loop-body assertion ID generation.
- [x] 5.2 Add rejection tests proving multi-entrypoint assertions inside loops fail single-call traceability.
- [x] 5.3 Add CLI tests for zero-iteration loops, including exact JSON output and exit code 1.
- [x] 5.4 Add Python execution tests proving loop tests and per-iteration assertion tests report pass/fail correctly.
- [x] 5.5 Add JavaScript and TypeScript smoke coverage for loop-discovered assertions when Node is available.
- [x] 5.6 Run the repository test suite and `openspec status --change "add-loop-as-test-support"` to confirm the change is apply-ready.
