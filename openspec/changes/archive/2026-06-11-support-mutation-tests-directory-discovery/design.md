## Context

`babel_code_goat.py` currently reads exactly `<tests_dir>/tests.py`, parses one module with `TestDiscoverer`, and assigns IDs with a hard-coded `tests.py:<line>` prefix. `PendingTest` and `TestCase` carry line and loop iteration data, but not source paths. Assertions are currently modeled around exactly one entrypoint call inside the assertion expression, so in-place mutation tests such as `sort_colors(a); assert a == [...]` are rejected even though they are common for algorithms that mutate lists or dictionaries.

The change expands discovery without changing the CLI shape, tester-file preservation rules, one-line JSON output contract, or language set. Discovery still runs from Python ASTs and must not execute test files.

## Goals / Non-Goals

**Goals:**

- Discover tests from all `.py` files under `<tests_dir>` recursively in deterministic order.
- Reject non-`.py` files whose filenames look like test files.
- Report discovery error when recursive scanning finds no tests.
- Support mutation-style tests where a statement or assignment entrypoint call is immediately followed by assert statements about mutated arguments or the assigned result.
- Preserve existing assertion, loop, exception, output expectation, and comparison behavior for root `tests.py`.
- Generate test IDs from relative source paths, line numbers, loop iteration paths, and existing same-line suffix rules.

**Non-Goals:**

- Supporting pytest, unittest, fixtures, cross-file imports, arbitrary helper modules, or executable setup beyond the existing constrained AST subset.
- Treating arbitrary `.py` helper files under `<tests_dir>` as ignorable; recursive `.py` files are test sources and must satisfy the supported subset.
- Supporting mutation assertions that depend on variables unrelated to the mutation call.
- Preserving shared in-process state between tests or across files.

## Decisions

1. Add a file-aware discovery wrapper around `TestDiscoverer`.
   - Rationale: The current per-module visitor already owns allowed syntax, loops, expectations, and expression parsing. Keeping it per file limits the change to source enumeration, parse error handling, and ID metadata.
   - Approach: Walk `<tests_dir>` recursively, sort files by POSIX relative path, reject matching non-`.py` test-like filenames except known generated tester artifacts, parse every `.py` file, and combine discovered cases. If the combined list is empty, raise `DiscoveryError`.
   - Alternative considered: Keep requiring `tests.py` and add optional include patterns. That would not meet the checkpoint's "no required `tests.py` root" requirement.

2. Store relative source paths on pending and finalized test cases.
   - Rationale: Line numbers alone are ambiguous once multiple files are discovered.
   - Approach: Add `source_path` to `PendingTest` and `TestCase`, pass each file's forward-slash relative path into `TestDiscoverer`, and update `assign_test_ids` / `test_id_base` to emit `<relative-path>:<line>` before loop iteration and `#k` suffixes.
   - Alternative considered: Prefix IDs only when the file is not `tests.py`. That creates two ID schemes; using the relative path everywhere keeps the rule simple while preserving existing root `tests.py` IDs.

3. Recognize mutation-style groups during statement-body traversal.
   - Rationale: Mutation tests are defined by statement adjacency, so they are easier to validate before dispatching each statement to the existing visitor methods.
   - Approach: Make `visit_body` iterate with an index. When it sees an entrypoint call expression statement or single-target assignment from the entrypoint, collect the immediately following contiguous `assert` statements. If none exist, or any collected assert calls the entrypoint or fails to reference a tracked variable, raise `DiscoveryError`.
   - Alternative considered: Add broad support for assignment from entrypoint calls in the existing expression parser. That would blur mutation semantics and make invalid detached entrypoint assignments harder to reject.

4. Evaluate mutation assertions against post-call dynamic references.
   - Rationale: The runner must inspect mutated arguments after invoking the solution, not just the returned value.
   - Approach: Track direct argument variable names from the mutation call and map them to argument indexes. For assignment form, map the assignment target to the call result. Parse each following assert as an expression over those dynamic references plus existing static environment values, then create one test case per assert that invokes the entrypoint and evaluates the assert expression after the call.
   - Alternative considered: Execute a mutation group once and report all following asserts from a single subprocess run. That would require a separate grouping model and would complicate result aggregation while providing little value for the checkpoint scope.

5. Preserve current subprocess execution boundaries.
   - Rationale: Python, JavaScript, and TypeScript runners already decode arguments, call the entrypoint, and evaluate expression metadata inside the target runtime.
   - Approach: Extend the expression metadata with dynamic argument references, and optionally a result reference for assignment-form mutation tests. Each runner evaluates those references after the entrypoint call using the same mutated argument objects passed to the function.
   - Alternative considered: Compare mutated values in the parent Python process after serializing actual values back from the runner. That would be lossy for JavaScript objects and would duplicate existing runner comparison logic.

## Risks / Trade-offs

- Recursive discovery may surface unsupported helper `.py` files that were previously ignored -> Document that all `.py` files under `<tests_dir>` are test sources and add focused error tests.
- Generated `tester.js` and `tester.ts` match the broad `test*` filename shape -> Exempt only the known generated tester artifact names from non-Python test-like rejection.
- Re-running a mutation call once per assert may differ from a literal Python file that executes one call followed by several asserts if the solution is nondeterministic -> Keep tests isolated like existing assertion execution and document mutation support as state-after-one-call validation.
- Tracking only direct variable arguments may reject creative but ambiguous patterns such as `sort_colors(cases[0])` -> Favor explicit variable-based mutation tests to keep validation and cross-language execution predictable.
- File ordering can affect result list ordering -> Sort by forward-slash relative path and preserve in-file AST order.

## Migration Plan

No migration is required for existing root `tests.py` suites. Existing IDs such as `tests.py:12` remain unchanged. Suites with non-Python files named like tests must rename or move those files before discovery will succeed.

## Open Questions

None for the checkpoint scope.
