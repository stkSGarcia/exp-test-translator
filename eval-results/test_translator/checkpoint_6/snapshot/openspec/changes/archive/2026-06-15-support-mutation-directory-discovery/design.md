## Context

`babel_code_goat.py` currently discovers tests from a single `<tests_dir>/tests.py` file, records `PendingTest` objects with source lines, and assigns IDs through `test_id_base()` using the hard-coded `tests.py:<line>` prefix. Assertion parsing already enforces single-entrypoint traceability and produces language-neutral assertion plans consumed by the Python and Node runners.

The checkpoint extends that discovery surface in two directions: recursive test files and mutation-style tests where the entrypoint call is a statement or direct assignment followed by dependent assertions.

## Related Work

> **`babel-code-goat-cli/support-single-call-traceability`**: Defines strict discovery of supported constructs and one-entrypoint traceability — informs the mutation validation design because mutation calls must still map to one configured entrypoint invocation.

> **`babel-code-goat-cli/support-rich-test-comparisons`**: Defines language-neutral assertion comparison plans — informs reuse of the existing comparison encoder/runner path for post-mutation assertions because mutation checks need to work for Python, JavaScript, and TypeScript solutions.

> **`babel-code-goat-cli/add-loop-as-test-support`**: Defines loop expansion and line-based IDs with `#<k>` suffixes — informs path-based IDs and deterministic multi-test suffix assignment because recursive files add a path component but should keep the same suffix semantics.

## Goals / Non-Goals

**Goals:**

- Discover supported tests from all `.py` files below `<tests_dir>` in deterministic path order.
- Preserve existing assertion, loop, exception, tolerance, and output-expectation behavior for root and nested Python test files.
- Validate non-Python test-like files before discovery completes.
- Add mutation-style test parsing without weakening single-entrypoint traceability _(see `babel-code-goat-cli/support-single-call-traceability`)_.
- Keep mutation postconditions language-neutral so generated harnesses can execute them across supported target languages _(see `babel-code-goat-cli/support-rich-test-comparisons`)_.

**Non-Goals:**

- Supporting arbitrary Python test frameworks or pytest collection.
- Supporting mutation assertions that require executing Python helper code at test runtime.
- Changing CLI arguments, tester file names, or solution entrypoint resolution.

## Decisions

### Recursive discovery layer

Add a helper that walks `<tests_dir>` recursively, validates test-like non-Python names, and returns `.py` files in stable relative-path order. `discover_tests()` will parse each file independently and combine discovered `PendingTest` records before final ID assignment.

Alternative considered: recursively search only files matching `test*.py` and `*_test.py`. That would miss valid checkpoint files because the requirement says tests may exist in any `.py` file.

### File path carried in pending tests

Extend `PendingTest` and `TestCase` with a relative POSIX path, and update ID assignment to build `<relative-path>:<line>` before applying existing loop iteration suffixes and `#<k>` duplicate suffixes _(see `babel-code-goat-cli/add-loop-as-test-support`)_.

Alternative considered: prefix IDs after `TestCase` creation. Carrying the path earlier keeps loop tests, regular tests, and future test kinds on one ID path and avoids special cases.

### Mutation tests as post-call assertion plans

Add a mutation parser in `TestDiscoverer.visit_body()` that recognizes a standalone entrypoint call or direct single-name assignment from the entrypoint, then consumes the immediately following assert statements as postconditions. The parser will reject the sequence if no assert follows, an intervening non-assert appears, an assert contains any entrypoint call, or an assert does not reference an allowed mutated variable.

Postconditions should reuse the existing comparison plan shape where possible, with a small expression extension for runtime references such as the entrypoint result or a post-call argument by index. Runners then call the entrypoint once and evaluate all postconditions against the mutated argument values and/or assigned result.

Alternative considered: translate mutation asserts by evaluating Python expressions during discovery. That cannot observe mutations performed by JavaScript or TypeScript solutions, so it would break cross-language execution.

### Existing statement handling remains strict

Unsupported statement errors should remain the default. The only newly supported expression statement is the mutation-style entrypoint call, and the only newly supported assignment value that calls the entrypoint is a direct mutation assignment followed by dependent asserts.

Alternative considered: allow arbitrary expression statements and ignore non-test code. That would hide invalid discovery patterns and conflict with the checkpoint's discovery-error requirement.

## Risks / Trade-offs

- Mutation assertions need runtime references beyond the current `result` expression -> add minimal `arg` or equivalent reference support in encoders and both runner implementations.
- Recursive discovery can change ordering when multiple files exist -> sort by POSIX relative path and preserve in-file source order.
- Existing tests assert root IDs as `tests.py:<line>` -> keeping the relative path for root `tests.py` preserves those IDs.
- Multiple mutation asserts after one call could produce multiple reported tests or one grouped test -> prefer one reported test per entrypoint call with all postconditions checked together to maintain one-call traceability.

## Migration Plan

1. Update discovery data structures and ID assignment to carry relative file paths.
2. Add recursive file collection and validation around existing per-file AST parsing.
3. Add mutation sequence parsing and postcondition serialization.
4. Extend Python and Node runners to evaluate post-call references.
5. Add focused unit and CLI tests for nested files, invalid files, no-test discovery errors, valid mutations, and invalid mutation patterns.

Rollback is limited to reverting these code and test changes; no persisted data or external dependencies are introduced.

## Open Questions

- None.
