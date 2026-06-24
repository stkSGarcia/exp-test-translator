## Context

`babel_code_goat.py` currently discovers tests by parsing `<tests_dir>/tests.py`, walking supported Python AST constructs, assigning line-based IDs with a hard-coded `tests.py` prefix, and serializing discovered cases into generated Python, JavaScript, and TypeScript testers. Prior changes added loop expansion and a scoped discovery context for literal values, but assertion discovery is still centered on direct entrypoint calls in assertion expressions.

Checkpoint 5 expands discovery in two ways: test files can live anywhere under `<tests_dir>`, and mutating entrypoint calls can define tests when followed immediately by assertions about the mutated arguments or assigned result.

## Goals / Non-Goals

**Goals:**

- Discover tests recursively from every `.py` file under `<tests_dir>`.
- Reject non-Python files with test-like names so accidental unsupported suites fail early.
- Produce stable test IDs using the source file path relative to `<tests_dir>`, with forward slashes.
- Support mutation-style groups where one standalone or assigned entrypoint call is immediately followed by related assertions.
- Enforce mutation constraints as discovery rules: no unrelated statements between the call and assertions, no entrypoint calls inside the related assertions, and each assertion must reference a variable tied to the mutating call.
- Preserve existing assertion, raise block, loop, tolerance, primitive expression, and generated tester semantics.

**Non-Goals:**

- Supporting arbitrary setup code before or between mutation assertions.
- Inferring aliasing through helper functions, attribute mutation, global state, or custom classes.
- Changing CLI arguments, result JSON shape, exit code mapping, or generated tester filenames.
- Requiring generated JavaScript or TypeScript testers to parse Python test files at runtime.

## Decisions

1. Enumerate source files before AST discovery.

   Discovery will scan `<tests_dir>` recursively, sort matching `.py` paths by their POSIX-style relative path, parse each file independently, and concatenate discovered cases. A helper should reject files whose names match `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>` when `<ext>` is not `py`. If the recursive scan yields no test cases, discovery raises `DiscoveryError`.

   Alternative considered: keep `tests.py` as preferred and only fall back to recursive discovery when absent. The checkpoint removes the required root file, so a single recursive path keeps behavior simpler and handles mixed root/nested suites consistently.

2. Carry source-relative IDs through discovery.

   `TestCase` or the ID assignment path will track a source ID prefix such as `tests.py` or `nested/test_foo.py`. `assign_ids` will group duplicate and loop-iteration counters by `(source, line)` rather than only line number. Existing suffix rules stay intact after the prefix changes: same-line non-loop tests use `#k`, and loop body expansions use `:<iteration-index>`.

   Alternative considered: assign IDs during parsing in each file. Keeping assignment centralized preserves current duplicate-line behavior and makes nested loop suffixes easier to audit.

3. Treat mutation-style groups as a distinct discovery construct.

   `discover_in_body` will recognize an expression statement calling the entrypoint or an assignment whose value calls the entrypoint. It will collect the immediately following contiguous `ast.Assert` statements until the next non-assert statement. If no following assert exists, the construct is unsupported and discovery fails. If a later assertion in the file references the same mutation target outside the immediate group, normal assertion rules apply and will fail because it has no entrypoint call.

   Alternative considered: translating each mutation assertion into the existing direct assertion model. That would either invoke the mutating entrypoint once per assertion or lose the relationship between the call and the mutated object.

4. Serialize mutation groups so the entrypoint is invoked once per group.

   A mutation group will produce one payload test per related assertion. Each test needs the entrypoint arguments, the assertion expression, and group metadata that tells generated testers to run the entrypoint once, then evaluate every assertion against the post-call values. For assignments such as `result = mutate(a)`, the assigned variable is also available to assertions. Generated testers can execute grouped mutation tests by batching adjacent payload items with the same group ID.

   Alternative considered: one payload item for the entire mutation group. Separate payload items preserve per-assert IDs and pass/fail reporting while still allowing a single mutation call per group.

5. Validate mutation assertion references during discovery.

   Discovery will derive the allowed reference set from variables passed to the entrypoint call plus the direct assignment target, when present. Every assertion in the group must reference at least one allowed variable and must contain zero configured entrypoint calls. Existing primitive expression support can be reused for supported comparison, truthy, falsy, membership, indexing, and helper forms once variable references are resolved against the post-mutation environment at runtime.

   Alternative considered: require every mutation assertion to reference all mutated variables. The checkpoint only requires at least one variable passed to or assigned from the mutation call, which supports common checks such as `assert a == [...]` after `sort_colors(a)`.

## Risks / Trade-offs

- [Risk] Recursive discovery changes IDs for tests in root `tests.py` only minimally but changes ordering when multiple files exist. -> Mitigation: sort relative paths and keep root `tests.py:<line>` IDs unchanged.
- [Risk] Test-like filename detection can reject harmless fixtures. -> Mitigation: limit rejection to explicit test-like filename patterns under `<tests_dir>`.
- [Risk] Mutation batching adds payload complexity across three generated testers. -> Mitigation: serialize clear group metadata and add parity tests for Python, JavaScript, and TypeScript runners.
- [Risk] Reference detection might miss complex mutation aliases. -> Mitigation: support only direct names passed as arguments or assigned from the call, and raise discovery errors for unsupported patterns.
- [Risk] Mutation assertions can accidentally become arbitrary expression execution. -> Mitigation: reuse the existing expression whitelist and reject assertions with unsupported helper calls or entrypoint invocations.
