## Context

The repository currently contains planning artifacts and the checkpoint description, but no implementation for the requested harness. The change will add a root-level Python CLI, `babel_code_goat.py`, that generates tester files from a constrained Python `tests.py` format and then runs solutions through the generated tester for a selected target language.

The main constraints are behavioral: unsupported languages must fail, `generate` must not damage existing tester files on failure, `test` must require a pre-existing generated tester, and `test` must emit exactly one JSON object on stdout with fixed keys and exit codes.

## Goals / Non-Goals

**Goals:**

- Provide a deterministic CLI for `generate` and `test`.
- Parse only the allowed `tests.py` constructs and fail discovery cleanly when unsupported or malformed input is encountered.
- Produce language-specific tester files named `tester.py`, `tester.js`, or `tester.ts`.
- Ensure result accounting includes every discovered test exactly once in either `passed` or `failed`.
- Preserve strict stdout behavior for the `test` command.

**Non-Goals:**

- General-purpose Python-to-JavaScript or Python-to-TypeScript translation.
- Supporting arbitrary pytest, unittest, imports, decorators, fixtures, async tests, or custom comparators.
- Defining a package/module export convention beyond the allowed callable forms.
- Installing or managing target-language runtimes or TypeScript toolchains.

## Decisions

- Use Python's standard-library `argparse`, `ast`, `json`, `subprocess`, and filesystem APIs for the CLI.
  - Rationale: the project does not need external dependencies for parsing the constrained Python input or producing JSON output.
  - Alternative considered: depend on a parser or transpiler package. That would add setup complexity without improving the constrained grammar.
- Represent discovered tests with a small internal model containing ID, source line, assertion kind, entrypoint call, expected value, and optional stdout/stderr expectations.
  - Rationale: one normalized model can feed all generated tester languages and can enforce coverage accounting before output.
  - Alternative considered: generate target code directly during AST traversal. That would duplicate validation and make discovery failures harder to report consistently.
- Treat discovery as an all-or-error phase.
  - Rationale: the checkpoint requires `{"status":"error","passed":[],"failed":[]}` when discovery fails, so no partially discovered set should leak into execution.
  - Alternative considered: skip unsupported tests and continue. That violates the coverage rule and hides authoring mistakes.
- Generate tester files through a temporary file followed by atomic replacement on successful generation.
  - Rationale: this satisfies the guarantee that failed generation does not create or modify `tester.py`, `tester.js`, or `tester.ts`.
  - Alternative considered: write directly to the final file. Direct writes risk partial files on generation failures.
- Make `test` read and execute the existing tester file without regenerating it.
  - Rationale: `generate -> test` is a required workflow boundary, and missing testers are errors.
  - Alternative considered: auto-generate during `test`. That weakens the workflow contract and can mask stale generation behavior.

## Risks / Trade-offs

- TypeScript execution depends on the local environment having a way to run `.ts` files if the generated tester is executed directly -> Keep the generated tester simple and document implementation assumptions in tests without adding dependency management to this change.
- Entrypoint loading is intentionally narrow -> Validate both allowed callable forms and return `error` when neither exists.
- Capturing stdout/stderr exactly can be brittle across language runtimes -> Capture per-test output around only the entrypoint invocation and compare raw text.
- Nested functions and duplicate same-line tests can complicate IDs -> Assign IDs from AST source locations and add `#0`, `#1`, and later suffixes only when multiple tests share a line.
