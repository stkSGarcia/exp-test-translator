## Context

`babel_code_goat.py` currently discovers tests from a single `<tests_dir>/tests.py` file. `discover_tests` parses that one file, `TestDiscoverer` stores pending tests without source-path context, and `test_id_base` hard-codes `tests.py` into every ID. The parser already has a constrained AST visitor, single-entrypoint traceability for assertion expressions, loop expansion, output expectation comments, and shared error handling for `generate` and `test`.

Checkpoint 5 keeps that constrained model but changes two foundations: discovery now walks the whole tests directory, and some entrypoints mutate arguments instead of returning assertion values directly.

## Goals / Non-Goals

**Goals:**

- Discover valid tests from all `.py` files below `<tests_dir>` in deterministic recursive order.
- Preserve existing assertion, loop, exception, output expectation, tolerance, and value-comparison semantics for each discovered Python file.
- Reject test-like non-Python files and empty recursive discovery results as discovery errors.
- Add constrained mutation-style groups where an entrypoint statement or assignment is immediately followed by assertions over the mutated or assigned variables.
- Produce stable test IDs using each file's forward-slash relative path, line number, loop iteration path, and same-line suffixes.

**Non-Goals:**

- Supporting arbitrary pytest/unittest conventions, fixtures, decorators, or test function invocation.
- Inferring mutation assertions across unrelated statements, helper calls, or non-immediate control-flow boundaries.
- Changing tester metadata format, CLI arguments, language support, or JSON result shape.

## Decisions

1. Walk files before parsing individual ASTs.

   `discover_tests` should collect candidate files with `Path.rglob("*")`, reject non-`.py` paths whose basename looks test-like, and parse `.py` files in sorted relative-path order. This keeps directory behavior centralized and preserves `TestDiscoverer` as the per-file parser.

   Alternative considered: let `TestDiscoverer` recurse into directories. That would mix filesystem validation with AST parsing and make the visitor carry concerns it does not need.

2. Carry source path on pending and finalized tests.

   Add a relative source path string to `PendingTest` and `TestCase`, and pass the current file path into `TestDiscoverer`. `assign_test_ids` and `test_id_base` can then build IDs from `<relative-path>:<line>` while preserving loop iteration and `#k` suffix logic.

   Alternative considered: prefix IDs after each file's `TestCase` list is created. That would duplicate same-line collision handling across files and make loop ID construction harder to reason about.

3. Detect mutation groups during sequential statement visitation.

   Extend `visit_body` to recognize an entrypoint call used as an expression statement or a single-target assignment before falling back to existing statement handling. A valid mutation group consumes that call plus one or more immediately following `assert` statements. The group fails discovery if the next statement is not an assertion, if a following assertion calls the entrypoint again, or if an assertion does not reference a variable passed directly to the call or assigned directly from it.

   Alternative considered: reinterpret any later assertion over a previously mutated variable. The checkpoint explicitly requires immediate assertions, and keeping the group local avoids accidental coupling across helper setup, loops, or unrelated statements.

4. Represent mutation assertions as normal executable tests with pre-call setup.

   Existing `TestCase` values mostly assume the entrypoint result is the assertion subject. Mutation tests need the generated tester to call the entrypoint first and then evaluate the assertion expression against mutated arguments or the assigned result. The smallest model change is to add mutation metadata to cases, including the call arguments, optional assignment target, and an encoded assertion expression that references those bound values.

   Alternative considered: execute mutation assertions at discovery time. That would require running user solutions during discovery and would break the current separation between discovery and execution.

## Risks / Trade-offs

- Relative-path IDs may require broad expectation updates in existing tests -> Keep root `tests.py` IDs unchanged except for using the same path prefix, and add focused regression tests for nested files.
- Recursive discovery could accidentally parse generated tester files -> Exclude `tester.py`, `tester.js`, and `tester.ts` from discovery candidates while still rejecting other test-like non-Python files.
- Mutation assertions add a second execution shape to generated testers -> Keep the metadata explicit and route mutation cases through a separate execution branch, leaving existing assertion cases untouched.
- Variable-reference validation can be too permissive if it only scans names -> Require direct name references from call arguments or assignment target, and reject entrypoint calls inside mutation assertions.
