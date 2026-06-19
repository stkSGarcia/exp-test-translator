## Context

`babel_code_goat.py` currently discovers tests with an AST-only `TestDiscoverer` over a single `<tests_dir>/tests.py` source file. Discovered tests are represented as `PendingTest` and `TestCase` instances, then assigned IDs by `assign_test_ids()` using a hardcoded `tests.py:<line>` base. Generated testers store only metadata, so both `generate` and `test` re-run discovery and must agree on discovery errors, test ordering, and IDs.

Checkpoint 5 expands the discovery surface in two ways: tests can live in any Python file under the test directory, and some tests express mutation-style behavior where the configured entrypoint is called for side effects before follow-up assertions inspect mutated variables.

## Goals / Non-Goals

**Goals:**
- Recursively discover supported tests from all `.py` files under `<tests_dir>`.
- Reject test-like files that are not Python files before generation or execution.
- Preserve deterministic discovery order and stable relative-path test IDs across platforms.
- Add a constrained mutation-style test shape without allowing arbitrary executable Python.
- Keep existing direct assertion, loop, expectation, value, and cross-language execution behavior intact.

**Non-Goals:**
- Supporting arbitrary pytest/unittest conventions or executing test files during discovery.
- Adding mutation assertions that call the entrypoint inside the assert.
- Supporting mutation assertions that inspect unrelated globals or values not tied to the mutation call.
- Changing tester filenames, CLI arguments, language validation, or output JSON shape.

## Decisions

1. Carry source-relative paths on discovered test records.
   - Rationale: IDs now need `relative/path.py:<line>` rather than one global `tests.py:<line>`, including loop iteration suffixes and duplicate-line suffixes.
   - Approach: Add a `source_id` or relative-path field to `PendingTest` and `TestCase`, pass it from each file-specific `TestDiscoverer`, and update `assign_test_ids()`/`test_id_base()` to include it.
   - Alternative considered: Prefix IDs after assignment per file. That makes duplicate-line suffixing harder because uniqueness must be scoped by full source path, line, and iteration path.

2. Add a deterministic recursive test source collector.
   - Rationale: `discover_tests()` is the shared validation point for both `generate` and `test`, so file discovery rules belong there.
   - Approach: Walk `<tests_dir>` recursively, normalize relative paths with forward slashes, sort paths lexicographically, reject test-like non-`.py` files, parse every `.py` file, and concatenate discovered cases in sorted file order. After all files are processed, raise `DiscoveryError` if no tests were discovered.
   - Alternative considered: Only scan `test*.py` files. The checkpoint says tests may exist in any `.py` file, so all Python files under the directory must be eligible.

3. Parse mutation-style blocks as an explicit statement sequence.
   - Rationale: Mutation tests are valid only when an entrypoint call statement or assignment is immediately followed by one or more asserts with no entrypoint call, and each assert references a mutated variable.
   - Approach: Extend `visit_body()` to recognize an entrypoint call in an `ast.Expr` or an `ast.Assign` whose value is the entrypoint call. Collect the named variables passed as call arguments and any variable directly assigned from the call, consume the immediately following consecutive `ast.Assert` statements, and materialize mutation tests for those asserts. Reject any entrypoint expression statement or assignment that does not form a valid mutation block.
   - Alternative considered: Treat mutation calls as ordinary assignments and let later asserts discover normally. That would silently accept invalid spacing and unrelated follow-up assertions, which conflicts with the checkpoint constraints.

4. Represent mutation assertions as normal executable cases with pre-call state.
   - Rationale: Existing runners execute one case at a time and evaluate an expression plan against the entrypoint result. Mutation tests need to call the entrypoint, then evaluate an assertion over the post-call argument or assignment variables.
   - Approach: Extend the case JSON with a mutation mode that includes the pre-call args and an assertion expression plan evaluated after the entrypoint call. For Python, JavaScript, and TypeScript runners, decode supported mutable values, call the solution with those arguments, bind the relevant post-call variable snapshots, and evaluate the assertion expression without invoking the entrypoint again.
   - Alternative considered: Compare mutated arguments in discovery only. Discovery cannot know solution behavior, so the assertion must be evaluated at execution time.

## Risks / Trade-offs

- Existing tests with helper `.py` files under `<tests_dir>` that contain unsupported top-level code will become discovery errors -> This follows the new "any `.py` files" contract and should be covered by tests that clarify valid helper declarations.
- Mutation identity across translated languages can be tricky for nested mutable values -> Reuse the existing tagged-value encoder/decoder and add focused cases for lists and nested containers before broadening further.
- Recursive discovery can expose generated tester files if they are Python -> Exclude the generated tester filename for the active language or ensure generated `tester.py` has no discoverable unsupported test constructs.
- Path separators differ by OS -> Convert every discovered path to POSIX-style relative paths before assigning IDs.

## Migration Plan

No user-facing migration is required. Existing `<tests_dir>/tests.py` suites remain valid and keep the same IDs because their relative path is still `tests.py`. New recursive suites and mutation-style tests are additive, while invalid test-like files and empty recursive discovery now consistently fail discovery.

Rollback is limited to reverting the discovery collector, path-aware IDs, and mutation-case support; generated tester metadata does not require a version change because tests are rediscovered at runtime.

## Open Questions

None.
