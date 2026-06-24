## Context

`babel_code_goat.py` currently discovers tests from exactly `<tests_dir>/tests.py`, parses that file into `TestCase` objects, and assigns IDs using a hard-coded `tests.py:<line>` prefix. Assertions are normally valid only when the assertion expression contains exactly one configured entrypoint call, while loop-expanded assertions reuse the same model with `in_loop=True`.

Checkpoint 5 changes two discovery assumptions. First, tests can live in any recursive `.py` file under `<tests_dir>`, and IDs need to identify the relative file path. Second, in-place mutation tests are valid even though the follow-up assertions do not call the entrypoint directly, as long as they immediately follow a statement or assignment that calls the entrypoint and inspect a variable tied to that call.

## Goals / Non-Goals

**Goals:**

- Discover supported tests from all recursive Python files under `<tests_dir>`.
- Reject test-like non-Python files and empty recursive discovery results as discovery errors.
- Preserve existing assertion, raise, loop, tolerance, value, stdout/stderr, and coverage semantics.
- Add mutation-style test support with explicit validation for immediacy, entrypoint reuse, and variable relevance.
- Generate stable relative-path IDs for root and nested files.
- Keep generated Python, JavaScript, and TypeScript tester payloads self-contained.

**Non-Goals:**

- Supporting arbitrary pytest syntax, fixtures, imports, helper calls, or unittest classes.
- Supporting mutation blocks separated by setup statements after the entrypoint call.
- Inferring aliasing through complex object graphs beyond variables passed to or directly assigned from the mutation call.
- Changing public CLI arguments or output JSON shape.

## Decisions

1. Store relative source paths on discovered test cases.

   `TestCase` should gain a `source_path` field, populated with the forward-slash relative path for the file currently being discovered. `assign_ids` should key duplicate-line and loop-iteration counters by `(source_path, line)` and format IDs with `source_path` instead of the fixed `tests.py` prefix.

   Alternative considered: prepend the path only after all files are discovered. Keeping the path on each case is simpler because loop expansion, same-line suffixing, and generated payload comparison all operate on `TestCase` values.

2. Split discovery into file scanning and per-file parsing.

   `discover_tests` should recursively scan `<tests_dir>` for `.py` files in deterministic relative-path order, reject test-like non-Python basenames, and call a per-file parser for each Python source. The per-file parser should use the relative path as the AST filename and expectation-comment context. After all files are parsed, an empty discovered list is a `DiscoveryError`.

   Alternative considered: keep `tests.py` as a special required root plus add optional nested files. That would contradict the checkpoint requirement that no root `tests.py` is required.

3. Represent mutation tests as setup plus assertion evaluation.

   Mutation-style discovery should parse an entrypoint expression statement or assignment into a setup payload containing the entrypoint args and, for assignment, the assigned name. Each immediate follow-up assertion should become its own test case with a mutation setup and an assertion expression to evaluate after the setup call. Generated testers should execute the setup call once for that test, bind the assigned result when applicable, then evaluate the assertion expression against the post-call variable environment.

   Alternative considered: group multiple follow-up assertions into one test. The existing result model reports one ID per assertion, so separate test cases preserve coverage accounting and failure localization.

4. Validate mutation follow-up assertions syntactically during discovery.

   Discovery should collect names referenced by each follow-up assertion, verify that the assertion contains no configured entrypoint calls, and require at least one referenced name to be either a variable passed as a direct argument to the mutation call or the assignment target receiving the call result. Existing expression/value parsing can be reused where possible, but mutation assertions need an evaluator that can compare names, containers, primitive operations, and allowed helper forms against the post-call environment rather than against a single `actual` value.

   Alternative considered: execute mutation assertions during discovery in Python. That would violate the current design, where discovery is static and generated testers execute against solutions in the selected target language.

## Risks / Trade-offs

- Mutation expression evaluator grows beyond the current single-`actual` expression model -> Keep the supported assertion surface aligned with existing primitive assertion forms and reject unsupported helper calls during discovery.
- Recursive ordering could change expected result order -> Sort relative paths lexicographically and preserve source order within each file.
- Existing tests assert hard-coded `tests.py` IDs -> Update only expectations affected by source-aware ID formatting; root `tests.py` IDs remain unchanged.
- JavaScript and TypeScript testers need mutation assertion evaluation too -> Encode mutation setup and assertion expressions in the shared JSON payload and implement equivalent evaluation in both runner templates.
- Generated tester payload compatibility changes -> `test` already compares the regenerated discovery payload with the embedded payload, so stale testers will fail consistently with existing behavior.
