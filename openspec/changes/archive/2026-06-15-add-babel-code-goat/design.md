## Context

The repository currently contains checkpoint requirements but no implementation. The new `babel_code_goat.py` module needs to act as both a generator and runner for a constrained Python test format, translating discovered tests into target-language harness behavior for Python, JavaScript, and TypeScript solutions.

The `test` command does not accept an entrypoint argument, so generated tester files must preserve the entrypoint and language context needed by later runs. `test` must also treat the expected tester file as an explicit prerequisite and leave it untouched.

## Goals / Non-Goals

**Goals:**

- Provide a root-level CLI with `generate` and `test` subcommands.
- Keep generation deterministic and failure-safe for `tester.py`, `tester.js`, and `tester.ts`.
- Parse the allowed subset of `tests.py` without executing `tests.py` during discovery.
- Use a shared internal test-case model so Python, JavaScript, and TypeScript harness behavior follows one contract.
- Emit exactly one JSON result line from `test` and map status to the required exit codes.

**Non-Goals:**

- Supporting arbitrary Python test syntax, pytest, unittest, fixtures, imports, or side-effectful discovery.
- Defining package/module export conventions beyond the checkpoint's callable resolution rules.
- Installing external JavaScript or TypeScript runtimes or dependencies.
- Providing sandboxing for untrusted solution code beyond subprocess isolation and captured output.

## Decisions

1. Implement a single Python CLI module using `argparse`.
   - Rationale: The required surface is small and self-contained, and a single file matches the checkpoint request.
   - Alternative considered: A package with multiple modules. This adds structure before the behavior needs it.

2. Discover tests with Python `ast` plus source-line bookkeeping.
   - Rationale: AST discovery can find assertions inside functions without executing them, validate the allowed subset, and preserve 1-based line numbers for IDs.
   - Alternative considered: Execute `tests.py` and intercept assertions. This would miss uncalled functions and introduce discovery side effects.

3. Normalize discovered tests into an internal test-case representation.
   - Rationale: Each test can carry its ID, assertion operation, entrypoint call arguments, expected value, and optional raw stdout/stderr expectations before any target-specific rendering or execution.
   - Alternative considered: Directly translate AST nodes into each language generator. This would duplicate parsing rules and make coverage guarantees harder to enforce.

4. Treat generated tester files as durable harness artifacts containing metadata.
   - Rationale: `test` lacks an entrypoint flag, so the tester file is the handoff from `generate` to `test`. The runner can verify the expected file exists, read metadata, and execute without modifying the tester.
   - Alternative considered: Require `--entrypoint` on `test`. This conflicts with the checkpoint CLI.

5. Render generation output in memory and write the tester only after all validation succeeds.
   - Rationale: The failure contract requires that `tester.py`, `tester.js`, and `tester.ts` are not created or modified on generation failure.
   - Alternative considered: Stream generated content directly to the destination. This risks partial files on errors.

6. Execute solution code in subprocesses with stdout/stderr captured.
   - Rationale: Capturing process output is necessary for the exact JSON-only CLI output and raw stdout/stderr expectations. Subprocess boundaries also keep solution output from leaking into the tool's stdout.
   - Alternative considered: In-process execution for all languages. This is not viable for JavaScript or TypeScript and makes output isolation more fragile.

## Risks / Trade-offs

- Unsupported or ambiguous `tests.py` syntax -> Report discovery failure as `status="error"` for `test` and fail `generate` without changing tester files.
- Runtime availability for JavaScript or TypeScript -> Detect execution failures and report them through the required error/failure path without emitting extra stdout.
- Solution code prints unexpected output -> Capture stdout/stderr per test and compare only when expectations are attached.
- Tests that cannot execute after successful discovery -> Include their IDs in `failed` so coverage remains complete.
- Generated tester metadata becomes stale if `tests.py` changes -> Rediscover current `tests.py` during `test` while using the generated tester for the required entrypoint/language handoff.

## Migration Plan

No migration is required. This change adds a new root-level CLI and new generated files only when users run `generate`.

## Open Questions

None for the checkpoint scope.
