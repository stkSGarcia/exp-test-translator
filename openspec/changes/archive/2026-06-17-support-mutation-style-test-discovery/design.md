## Context

`babel_code_goat.py` currently treats `<tests_dir>/tests.py` as the only discovery source. `discover_tests` parses that file once, `TestDiscoverer` emits pending tests keyed by source line, and `assign_test_ids` formats every ID with a hard-coded `tests.py:` prefix. Mutation-style tests are not represented because `visit_body` treats a bare entrypoint call as an unsupported statement and `visit_assign` expects assignments to parse as static values.

## Related Work

> **`babel-code-goat-cli/support-single-call-traceability`**: requires every discovered test to map to one configured entrypoint invocation — informs the mutation group validation because each accepted group must be anchored to one immediately preceding statement or assignment call.

> **`babel-code-goat-cli/add-loop-as-test-support`**: defines line-based IDs, loop statement tests, and iteration suffixes — informs the ID design because relative file paths should replace only the fixed `tests.py` prefix while preserving iteration and duplicate suffix rules.

> **`babel-code-goat-cli/add-babel-code-goat`**: defines base CLI discovery, error output, and tester generation behavior — informs error handling because recursive and mutation discovery failures should continue to surface through the existing `DiscoveryError` path.

## Goals / Non-Goals

**Goals:**
- Discover supported tests from every `.py` file under `<tests_dir>` recursively.
- Reject non-Python files with test-like names before generation or execution proceeds.
- Add mutation-style statement and assignment groups while preserving the single-entrypoint traceability rule.
- Produce stable forward-slash relative-path test IDs for root and nested files.
- Keep existing command output, tester metadata, value comparison, and loop execution contracts intact.

**Non-Goals:**
- Support arbitrary pytest conventions, fixtures, classes, decorators, or test discovery by function name.
- Execute Python test files directly during discovery.
- Add new external dependencies.
- Change generated tester file names or command-line arguments.

## Decisions

1. Treat each Python file as an independent discovery unit.

   `discover_tests` should gather candidate `.py` files recursively, sort them by POSIX-style relative path for deterministic output, parse each file with its relative path as the AST filename, and run a `TestDiscoverer` per file. This keeps existing per-file environment behavior and avoids accidental variable sharing between files. It also preserves current function and loop semantics with the smallest change surface _(see `babel-code-goat-cli/add-babel-code-goat`)_.

   Alternative considered: concatenate all files into one synthetic module. That would complicate line numbers, imports, and file-relative IDs without adding useful behavior.

2. Carry source file identity through pending tests.

   Extend `PendingTest` and `TestCase` with a `path` or `source_path` field, update `add_test` and `add_loop_test` to record the current relative path, and change `assign_test_ids`/`test_id_base` to format `<relative/path.py>:<line>` before existing iteration and duplicate suffixes. The loop iteration suffix rules stay unchanged _(see `babel-code-goat-cli/add-loop-as-test-support`)_.

   Alternative considered: post-process `tests.py:` prefixes after ID assignment. That would be fragile once multiple files contain tests on the same line number.

3. Parse mutation-style groups in `visit_body` with statement lookahead.

   `visit_body` should recognize an entrypoint call used as an expression statement and an assignment whose value is the entrypoint call. After such a call, it should consume the immediately following contiguous `assert` statements as one mutation-style group. The group is valid only if at least one assertion is present, no entrypoint call appears before the group closes, and every assertion references a name that was passed to the call or assigned from the call. Accepted groups should become one pending test whose execution plan invokes the entrypoint once and validates all associated assertions after mutation.

   Alternative considered: translate each post-mutation assertion as its own test. That would re-run the mutation call for each assertion and weaken traceability.

4. Represent mutation expectations explicitly.

   Add a mutation test kind or comparison mode that stores the entrypoint args plus serialized assertion checks over mutated variables. The existing direct result expression model can remain unchanged for normal assertions. Execution should run the entrypoint once, then evaluate the stored checks against the same mutated objects and report one pass/fail result for the group _(see `babel-code-goat-cli/support-single-call-traceability`)_.

   Alternative considered: pretend the mutated variable is the entrypoint return value. That fails for in-place functions that return `None` and obscures which state is being validated.

5. Fail discovery for invalid recursive inputs.

   Before parsing tests, scan `<tests_dir>` for test-like non-`.py` files using the specified patterns. After scanning and parsing all Python files, raise `DiscoveryError` if no tests were emitted. This keeps `generate` preservation behavior and `test` error JSON unchanged through existing error handling _(see `babel-code-goat-cli/add-babel-code-goat`)_.

## Risks / Trade-offs

- Mutation assertion evaluation can accidentally grow into a second expression language -> Limit accepted mutation assertions to the same supported value and primitive expression surface used by existing assertions.
- Recursive discovery changes output ordering when multiple files exist -> Sort by forward-slash relative path and then preserve AST order within each file.
- Adding source paths to test metadata may affect generated testers -> Keep serialized fields backward-compatible where possible and update all language runners together.
- Non-Python test-like detection may reject helper fixtures with test-like names -> This is required by the checkpoint, and the error should happen before partial discovery succeeds.

## Migration Plan

No data migration is required. Implement the parser and ID changes, update the unit tests, and verify the existing CLI contract still passes for `tests.py` root-only projects.

## Open Questions

- None.
