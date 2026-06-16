## Context

Test discovery currently parses only `<tests_dir>/tests.py`, formats every test ID with the hard-coded `tests.py` prefix, and treats entrypoint calls as valid only when they appear inside supported assertions or exception blocks. The existing implementation centralizes discovery in `babel_code_goat.py` through `discover_tests`, `TestDiscoverer`, `PendingTest`, `assign_test_ids`, and `test_id_base`, with broad regression coverage in `tests/test_babel_code_goat.py`.

## Related Work

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines loop-based test parameterization and line-based IDs for `tests.py` -- informs carrying source identity into every pending test because recursive discovery must preserve the loop ID conventions while changing the path prefix. _(see `babel-code-goat-cli/add-loop-as-test-support`)_

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines that every discovered test maps to exactly one configured entrypoint invocation -- informs mutation validation because statement/assignment calls need the same unambiguous execution source. _(see `babel-code-goat-cli/support-single-call-traceability`)_

> **`babel-code-goat-cli/support-rich-test-comparisons`**: Defines supported assertion expressions and values -- informs mutation assertion handling because post-mutation asserts should reuse the existing expression evaluator instead of introducing a second assertion language. _(see `babel-code-goat-cli/support-rich-test-comparisons`)_

## Goals / Non-Goals

**Goals:**

- Discover supported tests from every `.py` file under `<tests_dir>` recursively.
- Report discovery errors for test-like non-Python files and for directories with no discovered tests.
- Generate test IDs from relative file paths with forward slashes while preserving line, loop-iteration, and same-line suffix behavior.
- Support mutation-style entrypoint statements and assignments followed immediately by dependent assertions.
- Keep generated tester metadata and execution result JSON unchanged.

**Non-Goals:**

- Supporting arbitrary pytest collection, fixtures, decorators, or test functions by name.
- Supporting mutation assertions separated by setup or helper statements after the entrypoint call.
- Supporting multiple entrypoint calls in a single mutation-style assertion.
- Adding dependencies or changing CLI arguments.

## Decisions

1. Discover files before parsing and fail on invalid candidates.

   `discover_tests` will walk `<tests_dir>` recursively, sort paths for deterministic output, reject non-Python files whose basenames match `test*`, `*_test`, `tests`, or `*_tests`, parse every `.py` file, and raise `DiscoveryError` when no tests are collected. The alternative was to only recurse through `test*.py` files, but that would miss existing supported layouts where `tests.py` or domain-named Python files contain assertions.

2. Carry `source_path` through pending and final test records.

   `PendingTest` and `TestCase` will include the path relative to `<tests_dir>`, normalized with forward slashes. `assign_test_ids` and `test_id_base` will use that path with the existing line, loop path, and duplicate suffix logic. The alternative was to post-process IDs after discovery per file, but that would duplicate suffix accounting and make loop IDs easier to break.

3. Reuse `TestDiscoverer` per source file.

   Each Python file will be parsed by a fresh discoverer with its own import aliases and assignment environment, then all pending tests will be combined and ID-assigned once. The alternative was to parse all modules into one synthetic AST, but that would leak variables and imports between files in a way Python modules do not.

4. Recognize mutation-style runs as adjacent statement groups.

   `visit_body` will detect an entrypoint call statement or direct assignment from an entrypoint call, require one or more immediately following asserts, and require each of those asserts to reference a mutation source variable or assigned target. Those asserts can then be converted through the existing assertion-expression machinery with the call arguments supplied from the preceding mutation run. The alternative was to simulate the mutation at discovery time, but discovery cannot know the solution behavior and should only describe execution.

5. Keep generation and execution contracts stable.

   `generate` and `test` will continue to read the entrypoint from tester metadata and return the same JSON shapes and exit codes. Discovery changes are internal to the metadata-to-cases phase. The alternative was to encode discovered cases in tester files, but the current design intentionally keeps tester files lightweight and regeneratable.

## Risks / Trade-offs

- Mutation assertions may look similar to plain assertions that do not call the entrypoint -> require explicit variable-reference checks and focused tests for invalid adjacency and independent asserts.
- Recursive discovery can change output ordering -> sort relative paths and preserve in-file source order.
- Hidden non-Python files may unexpectedly become discovery errors -> limit rejection to the specified test-like basename patterns.
- Adding `source_path` to data classes may require updates in runner code that constructs or serializes `TestCase` -> provide defaults or update all construction sites in one pass.

## Migration Plan

1. Add regression tests for recursive discovery, relative IDs, non-Python test-like file errors, no-test errors, valid mutation-style tests, and invalid mutation-style patterns.
2. Update discovery data structures and ID formatting.
3. Replace single-file `tests.py` parsing with recursive discovery.
4. Add mutation-style statement-group parsing and execution-plan reuse.
5. Run the unit test suite and OpenSpec validation for the change.

Rollback is limited to reverting the discovery and test updates; generated tester file format does not change.

## Open Questions

- None.
