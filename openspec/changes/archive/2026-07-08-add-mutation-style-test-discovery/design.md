## Context

Discovery currently reads only `<tests_dir>/tests.py`, parses supported top-level and nested Python constructs, and assigns IDs with a hard-coded `tests.py` prefix in `assign_ids`. `discover_in_body` walks statements in order and accepts asserts, try/except raise checks, loops, assignments, imports, function bodies, and pass statements. This change needs to broaden the discovery surface without loosening the existing traceability rule that each discovered test maps to exactly one entrypoint invocation.

## Related Work

> **`babel-code-goat-cli/support-loop-construct-tests`**: Defines allowed constructs, unsupported-code discovery failures, and line-based test IDs for loop and non-loop tests - informs the decision to keep unsupported mutation patterns as discovery errors and to extend the ID prefix from `tests.py` to the tests-directory-relative path because the prior intent was to support compact Python tests while preserving deterministic discovery behavior.

## Goals / Non-Goals

**Goals:**
- Discover supported tests from every `.py` file under the configured tests directory in deterministic path order.
- Reject test-like non-Python files before generation or execution.
- Support mutation-style entrypoint statement and assignment calls followed by assert groups.
- Preserve strict traceability by requiring each mutation assert to reference a passed or directly assigned variable.
- Generate path-qualified IDs while preserving existing same-line suffix behavior.

**Non-Goals:**
- No new language targets or runner dependencies.
- No support for arbitrary helper calls in mutation assertions.
- No broad Python test framework compatibility such as pytest function collection.
- No change to generated tester payload fields beyond the already string-valued `id`.

## Decisions

### Recursive discovery owns file ordering and validation

`discover_tests` will collect files below `tests_dir` with a sorted relative-path traversal. It will fail fast on non-Python paths whose names match the test-like patterns, then parse each `.py` file with its relative path as the AST filename. Empty files, helper-only files, and files without supported tests are allowed as long as at least one test is discovered somewhere in the tree; if the total result set is empty, discovery fails. This keeps per-file parsing errors local while satisfying the directory-level "no tests" error.

Alternative considered: keep requiring `tests.py` and add optional nested files only when present. That would leave root `tests.py` as an accidental contract, which the checkpoint explicitly removes.

### IDs become path-aware, with loop behavior preserved

`assign_ids` will accept a relative path prefix, or `TestCase` will carry an internal source path until IDs are assigned. Non-loop IDs use `<relative-path>:<line>` plus existing `#k` suffixes for same-line duplicates. Existing loop iteration suffixes should keep their current form after the path prefix, e.g. `nested/test_foo.py:5:0`, so loop tests remain stable while path qualification changes. _(see `babel-code-goat-cli/support-loop-construct-tests`)_

Alternative considered: include source path as a separate JSON field. The runners and payload comparison already key off `id`, and the checkpoint defines the full identity string, so a new field would add migration surface without a requirement.

### Mutation-style parsing is a statement-group parser

`discover_in_body` will switch from a simple `for` loop over statements to index-based traversal so it can recognize an entrypoint statement or assignment and consume the immediately following assert group. A mutation group starts only when the current statement is either:
- `entrypoint(...)` as an expression statement, or
- `target = entrypoint(...)` as a simple assignment.

The parser records variables passed as direct `ast.Name` call arguments and variables assigned by the call. It then consumes one or more immediately following `ast.Assert` statements. Every consumed assert must reference at least one recorded variable and must not include another entrypoint call. If the call has no following assert, an assert fails the variable-reference check, or a later assertion would require crossing another entrypoint call, discovery fails for the file. _(see `babel-code-goat-cli/support-loop-construct-tests`)_

Alternative considered: parse mutation assertions by extending `parse_assert`. That parser is expression-oriented and expects the entrypoint call to appear inside the assertion; mutation-style grouping depends on neighboring statements, so keeping it in statement traversal is clearer.

### Reuse existing expression/value support where practical

The entrypoint call in a mutation group should use the existing `parse_entrypoint_call` and `value_from_node` behavior for argument values. Assertion validation can initially store mutation cases as expression-style tests that replay the call and evaluate the assertion expression against the mutated or assigned variable, or introduce a focused `kind` if runner execution needs a distinct path. The important contract is that runner generation receives enough information to invoke the entrypoint and evaluate the post-call assertion deterministically.

Alternative considered: treat mutation assertions as normal equality/truthiness assertions. That loses the sequencing requirement and cannot represent in-place mutation without first-class post-call assertion evaluation.

## Risks / Trade-offs

- [Risk] Recursive discovery may pick up generated tester files if their names look test-like or contain supported asserts -> Mitigation: only discover source `.py` files but explicitly exclude known generated tester filenames from candidate test sources if needed.
- [Risk] Adding internal source path metadata to `TestCase` could affect equality or JSON payload comparisons -> Mitigation: keep any source path out of `to_jsonable`, or assign IDs before serialization without storing the path.
- [Risk] Mutation assertion evaluation may require runner changes in each supported target -> Mitigation: add focused tests across Python, JavaScript, and TypeScript generation paths before changing runner payload shape.
- [Risk] Path ordering differs across platforms -> Mitigation: normalize relative paths to forward slashes before sorting and ID assignment.

## Migration Plan

1. Extend tests around discovery first, covering recursive `.py` discovery, test-like non-Python rejection, empty discovery errors, path IDs, and valid/invalid mutation groups.
2. Update discovery and ID assignment in `babel_code_goat.py`.
3. Update runner generation only if mutation-style cases require a new payload representation.
4. Run the existing pytest suite and targeted CLI generate/test checks.

## Open Questions

- Should generated tester files such as `tester.py` be explicitly excluded from recursive discovery even though they do not match the checkpoint's test-like filename patterns?
