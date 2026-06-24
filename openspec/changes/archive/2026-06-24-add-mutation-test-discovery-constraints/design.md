## Context

`babel_code_goat.py` currently discovers Python tests by parsing `<tests_dir>/tests.py`, walking supported AST nodes, and assigning IDs with a hard-coded `tests.py:<line>` prefix. Earlier checkpoints added traceable expression assertions and loop expansion, but mutation-style tests such as `sort_colors(a); assert a == [...]` are still unsupported because the entrypoint call is not inside the assert. Checkpoint 5 also broadens discovery from a single file to all Python files under `<tests_dir>`.

## Goals / Non-Goals

**Goals:**

- Discover tests recursively from `.py` files beneath `<tests_dir>` while preserving deterministic ordering and generated tester payload stability.
- Reject test-like non-Python files before generation so likely misnamed tests do not silently disappear.
- Support mutation-style groups made of one entrypoint call statement or assignment immediately followed by related asserts.
- Enforce that each mutation-style assert references a mutated input variable or the variable assigned from the entrypoint result.
- Generate relative-path test IDs for all discovered tests, including nested files, same-line suffixes, and loop iteration suffixes.
- Keep existing assertion, raise expectation, loop, value, tolerance, and cross-language runner behavior intact.

**Non-Goals:**

- Supporting arbitrary statement sequences between mutation calls and assertions.
- Supporting mutation-style assertions that do not mention a variable tied to the entrypoint call.
- Discovering tests from non-Python files or adding a separate test manifest.
- Changing CLI arguments, generated tester filenames, result JSON keys, or exit code semantics.

## Decisions

1. Discover files before parsing tests.

   `discover_tests()` will collect candidate files with `Path.rglob("*")`, reject test-like non-`.py` paths matching `test*.<ext>`, `*_test.<ext>`, `tests.<ext>`, or `*_tests.<ext>`, then parse only `.py` files. Files should be processed by forward-slash relative path order to keep payloads stable across platforms. If no tests are produced after all `.py` files are parsed, discovery raises `DiscoveryError`.

   Alternative considered: continue requiring `tests.py` and add optional nested includes. Recursive discovery is the checkpoint requirement and avoids inventing include syntax.

2. Carry source identity through discovery and ID assignment.

   `TestCase` should retain a source path or equivalent file identifier in addition to its line number. The parser for a single file can pass the relative path into `assign_ids()` so IDs become `<relative-path>:<line>`, with `#k` same-line suffixes and existing loop iteration suffixes applied after that prefix.

   Alternative considered: rewrite line numbers into globally unique integers. Relative paths are more debuggable and explicitly required by the checkpoint.

3. Treat mutation groups as statement-level discovery units.

   `discover_in_body()` should detect an entrypoint call that appears as either `Expr(Call(entrypoint, ...))` or a single-target assignment whose value is `Call(entrypoint, ...)`. The statement starts a mutation group, and the following one or more adjacent `assert` statements are consumed as mutation asserts. The group is invalid if there is no following assert, if any following assert fails the variable-reference rule, or if a later assert appears to depend on the mutation call after an unrelated statement has broken adjacency.

   Alternative considered: accept any later assert that references the same variable. That is more permissive but makes unrelated tests order-dependent and harder to translate safely.

4. Validate mutation asserts by variable reference rather than entrypoint traceability.

   A mutation-style assert is valid when it references at least one variable passed to the entrypoint call, or the variable directly assigned from the call. These asserts will be serialized with the same expression comparison machinery used for ordinary asserts, but their actual value is read from the referenced variable after the entrypoint call instead of being produced by another solution invocation. Generated testers must perform the setup, call the entrypoint once, then evaluate every serialized mutation assert against post-call variables.

   Alternative considered: allow mutation asserts to call the entrypoint again. That would violate the mutation-style contract and could hide implementations that return correct values but fail to mutate inputs.

5. Keep mutation support narrow in the first pass.

   Mutation calls should accept the same supported argument values and name resolution already available to discovery. Mutation assertion expressions should stay inside the supported primitive comparison surface and fail discovery for unsupported helper calls, unsupported variable references, or multiple entrypoint calls.

   Alternative considered: execute Python tests directly during discovery to observe mutated values. That would make discovery depend on the reference implementation and would not translate cleanly to JavaScript or TypeScript solutions.

## Risks / Trade-offs

- [Risk] Recursive discovery can accidentally include generated tester files. -> Mitigation: exclude `tester.py`, `tester.js`, and `tester.ts` from discovery and preserve failed-generation behavior that does not write tester files.
- [Risk] Relative-path IDs can change snapshots from earlier behavior. -> Mitigation: root-level `tests.py` still produces `tests.py:<line>`, while nested files add only the required path prefix.
- [Risk] Mutation serialization adds a second execution shape across generated testers. -> Mitigation: model mutation groups explicitly in the payload and add cross-language end-to-end tests for Python, JavaScript, and TypeScript where feasible.
- [Risk] Test-like filename matching might reject user fixture files. -> Mitigation: keep the pattern limited to common test file names and only apply it to non-`.py` files under `<tests_dir>`.
