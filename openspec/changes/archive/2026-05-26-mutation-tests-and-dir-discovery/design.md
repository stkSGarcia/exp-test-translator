## Context

`babel_code_goat.py` currently discovers tests only from `<tests_dir>/tests.py` and only matches entrypoint calls embedded in `assert` expressions. Mutation-style functions (in-place operations like `sort_colors(a)`) cannot be tested because the call appears as a statement and the result is observed on the argument after the call, not from a return value. Test organisation is also limited to a single flat file.

## Goals / Non-Goals

**Goals:**
- Recognise entrypoint calls as statements (`fn(a)`) or assignments (`x = fn(a)`) followed by assertions on the mutated/returned variables
- Enforce constraint: every assertion immediately following a mutation call must reference at least one variable passed to — or assigned from — that call; violations are discovery errors
- Discover tests from all `.py` files under `<tests_dir>` recursively; detect and error on test-like non-`.py` files; error when no tests are found
- Update test IDs to include the relative file path prefix

**Non-Goals:**
- Changing the three tester emitters' runtime logic beyond adding mutation-mode test execution
- Supporting mutation-style patterns inside loops or nested scopes
- Modifying the `test` sub-command or tester runner output format

## Decisions

### Decision: Represent mutation tests with a new `mutation_check` field on `TestCase`

For a statement mutation call `fn(a)` where `a` resolves to a known value, the assertion `assert a == expected` becomes a test case where:
- `args` = the initial value of `a` (as a positional arg)
- `expected` = the expected value after mutation
- `mutation_check: int | None` = the index into `args` of the variable to inspect post-call (e.g., `0` for `a` in `fn(a)`)
- `kind` = `"eq"` (or other assertion kinds as applicable)

When `mutation_check` is `None` (the default), the tester checks the return value — identical to current behaviour. When set, the tester calls `fn(*args)` and then compares `args[mutation_check]` to `expected` instead of the return value.

*Alternative considered*: A new `kind` value like `"mutation_eq"`. Rejected because it would require changes to every kind-dispatch site in all three emitters; the field approach is additive and localised.

### Decision: Parse mutation groups in `_collect_stmts` using lookahead over the statement list

Rather than a separate parsing pass, mutation detection is integrated into the existing statement traversal. When `_collect_stmts` encounters an `ast.Expr` or `ast.Assign` whose value is an entrypoint call, it enters mutation mode:
1. Records which variables are "mutation-tracked" (args passed to the call; the assigned name for assignment form)
2. Advances the iterator to consume immediately following `ast.Assert` statements
3. For each following assert, checks whether the test expression contains at least one mutation-tracked name (via a recursive name-collection helper). If not → discovery error. If yes → creates a `TestCase` with `mutation_check` pointing to the relevant arg index
4. Exits mutation mode when a non-Assert statement is reached

*Alternative considered*: Two-pass approach (first detect mutation groups, then convert to test cases). Rejected as more complex with no benefit for single-file processing.

### Decision: Discovery error propagates as a raised exception through `parse_tests`

A new `DiscoveryError(message)` exception is raised from `parse_tests` (or the new multi-file discovery function) when:
- A mutation assertion fails its constraint check
- A test-like non-`.py` file is found in `<tests_dir>`
- No test cases are discovered across all `.py` files

`cmd_generate` catches `DiscoveryError` and exits non-zero with a message to stderr, same as the existing parse-error path.

### Decision: Multi-file discovery replaces the single `tests.py` lookup in `cmd_generate`

A new helper `discover_test_files(tests_dir: Path) -> list[Path]` returns all `.py` files under `tests_dir` (sorted for determinism) and raises `DiscoveryError` for test-like non-`.py` files. `cmd_generate` calls this and iterates over the results, calling `parse_tests` for each file and accumulating test cases. The final merged list is passed to the emitter as before.

Test IDs are prefixed with the file's relative path (forward slashes) during ID assignment in `parse_tests`, which now accepts a `file_prefix: str` argument (e.g., `"subdir/tests.py"`).

## Risks / Trade-offs

- **Mutation check is index-based**: The `mutation_check` index references `args[i]`. If a mutation call passes the same variable twice (`fn(a, a)`) the index points to its first occurrence; the post-call check sees the same list object. This is an edge case unlikely in practice.

- **Variable name resolution for mutation detection**: The constraint check (does an assertion reference a mutation variable?) uses AST name traversal, not value semantics. Aliased variables (`b = a; fn(a); assert b == ...`) will not be detected. This is acceptable given the stated constraints.

- **No mutation support inside loops**: Mutation calls inside loop bodies are not handled. If encountered, `_collect_stmts` will skip them (not produce a test case) rather than error. This can be tightened in a future change.

## Migration Plan

No migration needed. The only breaking change to external interface is the test ID format (`subdir/tests.py:5` instead of `tests.py:5`). Any caller relying on the old flat ID format must update ID references. The emitters accept the new IDs unchanged.
