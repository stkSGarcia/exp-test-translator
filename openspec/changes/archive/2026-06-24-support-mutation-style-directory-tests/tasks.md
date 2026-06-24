## 1. Coverage

- [x] 1.1 Add discovery tests for recursive `.py` file discovery, including a nested file without root `tests.py`.
- [x] 1.2 Add discovery and CLI tests for non-Python test-like filenames under `<tests_dir>` producing discovery errors.
- [x] 1.3 Add discovery and CLI tests for an empty recursive suite producing discovery error JSON and exit code `2`.
- [x] 1.4 Add ID tests for nested file paths, root `tests.py` compatibility, same-line suffixes by file, and loop iteration suffixes by file.
- [x] 1.5 Add discovery and execution tests for standalone mutation calls followed by assertions about mutated arguments.
- [x] 1.6 Add discovery and execution tests for assignment mutation calls followed by assertions about the assigned result and mutated arguments.
- [x] 1.7 Add negative tests for mutation calls without immediate assertions, intervening statements, unrelated-variable assertions, and assertions that call the entrypoint again.
- [x] 1.8 Add cross-language execution tests proving Python, JavaScript, and TypeScript testers run mutation groups once and report per-assert IDs.

## 2. Recursive Discovery And IDs

- [x] 2.1 Add recursive source file enumeration for `.py` files under `<tests_dir>` with deterministic POSIX-style relative path ordering.
- [x] 2.2 Add test-like filename validation for non-`.py` files matching `test*`, `*_test`, `tests`, and `*_tests` patterns.
- [x] 2.3 Refactor discovery parsing so each source file carries its relative path into discovered `TestCase` records.
- [x] 2.4 Update ID assignment to group counters by relative path and line while preserving root `tests.py:<line>` IDs.
- [x] 2.5 Raise `DiscoveryError` when recursive discovery completes with no discovered tests.
- [x] 2.6 Update generate/test payload comparison paths to use recursive discovery consistently.

## 3. Mutation Discovery Model

- [x] 3.1 Extend the test case payload model with mutation group metadata needed to batch related assertions after one entrypoint invocation.
- [x] 3.2 Recognize valid mutation group starts from standalone entrypoint call statements and assignments whose value is the entrypoint call.
- [x] 3.3 Collect only immediately following contiguous assertion statements into a mutation group and reject unsupported mutation patterns.
- [x] 3.4 Derive allowed mutation assertion references from direct name arguments passed to the entrypoint and the direct assignment target when present.
- [x] 3.5 Validate every mutation assertion has zero configured entrypoint calls and references at least one allowed mutation variable.
- [x] 3.6 Reuse the existing expression whitelist for mutation assertions, adding variable-reference expression support where needed.

## 4. Tester Execution

- [x] 4.1 Update Python tester execution to evaluate each mutation group by invoking the entrypoint once, then evaluating all grouped assertions against post-call values.
- [x] 4.2 Update JavaScript tester execution to batch mutation group payloads and preserve per-assert pass/fail reporting.
- [x] 4.3 Update TypeScript tester execution to batch mutation group payloads and preserve per-assert pass/fail reporting.
- [x] 4.4 Ensure stdout/stderr expectation handling, tolerance comparisons, and structural comparisons still work for non-mutation tests after payload changes.

## 5. Verification

- [x] 5.1 Run the full pytest suite and update affected expectations for path-based IDs.
- [x] 5.2 Manually exercise representative `generate` and `test` flows for recursive files and mutation-style tests in Python, JavaScript, and TypeScript.
- [x] 5.3 Run `openspec status --change support-mutation-style-directory-tests` and confirm the change is apply-ready.
