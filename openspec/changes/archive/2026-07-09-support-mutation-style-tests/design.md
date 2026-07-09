## Context

Checkpoint 5 expands Babel Code Goat discovery in two directions: mutation-style tests for functions that update values in place, and recursive discovery across `<tests_dir>`. The current implementation in `babel_code_goat.py` parses a single `tests.py`, discovers assertion and loop constructs with `discover_in_body`, and assigns IDs in `assign_ids`.

## Related Work

**`babel-code-goat-cli/support-single-call-test-traceability`**: Defines assertion discovery around exactly one configured entrypoint invocation -- informs the mutation grouping decision because mutation-style assertions must remain traceable to one entrypoint call even when the call is not inside the assert.

**`babel-code-goat-cli/add-babel-code-goat`**: Defines the CLI discovery surface, error JSON, and original `tests.py:<line>` IDs -- informs the recursive discovery and ID migration because the new behavior must preserve the same generate/test contract while widening the input set.

**`babel-code-goat-cli/support-loop-construct-tests`**: Defines constrained acceptance for loop constructs and discovery errors for unsupported variants -- informs mutation validation because mutation-style tests should be accepted only as an explicit, bounded construct.

## Goals / Non-Goals

**Goals:**
- Discover valid mutation-style statement and assignment groups without weakening single-call traceability.
- Reject mutation-like uses that cannot be tied to immediately following assertions.
- Traverse all recursive `.py` files under `<tests_dir>`.
- Preserve deterministic test ordering and stable line-based IDs using relative paths.
- Keep discovery failure behavior compatible with the existing error JSON contract.

**Non-Goals:**
- Supporting arbitrary Python mutation analysis or alias tracking.
- Supporting entrypoint calls embedded in unsupported statements.
- Changing target runner execution semantics beyond the test data produced by discovery.

## Decisions

1. Extend discovery with an explicit mutation group parser.

   `discover_in_body` should detect an entrypoint call used as `ast.Expr` or as the value of an assignment before falling through to unsupported-code errors. The parser should collect immediately following `ast.Assert` statements until the next non-assert statement, verify the group is non-empty, reject any assert with an entrypoint call, and require every assert to reference at least one mutated/assigned variable. This keeps mutation discovery separate from expression assertion parsing _(see `babel-code-goat-cli/support-single-call-test-traceability`)_.

   Alternative considered: teach `parse_assert` to look backward for a prior mutation call. That would spread stateful grouping into assertion parsing and make intervening-statement errors harder to report consistently.

2. Represent mutation assertions using the existing expression/expected machinery where possible.

   For each mutation assertion, discovery should record the entrypoint arguments from the mutation call and an expression or expected result derived from the assertion over the mutated value. This lets existing target generators consume the same `TestCase` shape where feasible, with narrowly scoped extensions only if an assertion cannot be represented today.

   Alternative considered: introduce a separate runner path for mutation tests. That would duplicate per-language evaluation logic and raise the chance that Python and JavaScript/TypeScript diverge.

3. Make file identity part of discovered test metadata.

   `TestCase` currently carries `line` and `in_loop`; it should also carry a relative source path. `discover_tests` should parse every recursive `.py` file, pass the relative path through discovery, and call ID assignment after all files are collected. `assign_ids` should key duplicate tracking by `(relative_path, line)` and format IDs as `<relative-path>:<line>` with forward slashes _(see `babel-code-goat-cli/add-babel-code-goat`)_.

   Alternative considered: keep a global line counter across files. That would produce unstable IDs and would not satisfy the path-relative contract.

4. Validate test-like non-Python files before or during traversal.

   Recursive discovery should reject names matching `test*.{ext}`, `*_test.{ext}`, `tests.{ext}`, or `*_tests.{ext}` when the suffix is not `.py`. The check should run during directory traversal so invalid files fail even if valid Python tests are also present _(see `babel-code-goat-cli/support-loop-construct-tests`)_.

   Alternative considered: ignore non-Python files. That would hide likely user mistakes and contradict checkpoint 5.

## Risks / Trade-offs

- Mutation assertion serialization may not map cleanly to every currently supported assertion shape -> Prefer the existing expression representation and add the smallest test-case field needed only if implementation proves necessary.
- Recursive ordering can change output IDs and pass/fail ordering -> Sort paths lexicographically by relative forward-slash path before parsing.
- Existing tests assume `tests.py:` IDs -> Update expectations carefully and keep root `tests.py` IDs unchanged as `tests.py:<line>`.
- Mutation grouping inside loops could interact with loop-expanded IDs -> Reuse existing loop context and duplicate-ID handling, adding focused tests for mutation groups both outside and inside loops if supported by the implementation.

## Migration Plan

1. Add failing tests for valid mutation groups, invalid mutation patterns, nested Python files, non-Python test-like files, empty recursive discovery, and relative path IDs.
2. Update `babel_code_goat.py` discovery in small steps: traversal, source-path metadata and IDs, then mutation grouping.
3. Run the existing and new pytest suite for Babel Code Goat.

Rollback is limited to reverting the discovery and test changes because no external data migration or dependency change is required.

## Open Questions

- Whether mutation-style assertions inside loop bodies should be supported in the first implementation pass or rejected as unsupported until there is explicit coverage.
