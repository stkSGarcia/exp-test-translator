## Context

`babel_code_goat.py` is a new standalone Python CLI. There is no existing codebase to integrate with. The tool must parse a `tests.py` file written in a constrained DSL, translate each test into a target language, and optionally execute that tester against a solution file. All execution for JS/TS is delegated to subprocesses (`node`, `npx ts-node` or `tsx`).

## Goals / Non-Goals

**Goals:**
- Parse the `tests.py` DSL (assertions, raise-any blocks, stdout/stderr annotations) into a language-agnostic test IR
- Emit correct, runnable tester files for Python, JavaScript, and TypeScript from that IR
- Run the tester against a solution and return a structured JSON result with line-based test IDs
- Enforce the `generate → test` contract (error if tester file missing on `test`)
- Cover all allowed value types: `None`, `bool`, `int`, `float`, `str`, `list`, `tuple`, `dict`

**Non-Goals:**
- Supporting languages beyond Python, JavaScript, TypeScript
- Linting or type-checking the solution files
- Parallel test execution
- Watching for file changes
- Supporting `tests.py` constructs outside the spec (e.g., `pytest` fixtures, `unittest`)

## Decisions

### 1. Parse `tests.py` with Python's `ast` module, not regex

The DSL is valid Python syntax. Using `ast` gives us accurate line numbers and reliable structure detection without fragile regex. The AST walk is a single pass that emits `TestCase` dataclass objects.

*Alternative considered*: `tokenize` + line-by-line regex — rejected because handling nested structures (dicts, tuples) is error-prone.

### 2. Intermediate Representation (IR)

All parsed tests are normalized into a `TestCase` dataclass before any code generation:

```python
@dataclass
class TestCase:
    id: str                    # "tests.py:12" or "tests.py:12#1"
    kind: Literal["eq", "ne", "truthy", "falsy", "raises", "eq_stdout", "eq_stderr"]
    args: list[Any]            # positional args to entrypoint
    expected: Any              # for eq/ne; None for raises/truthy/falsy
    expect_stdout: str | None
    expect_stderr: str | None
```

This decouples parsing from code generation and makes adding a new target language a matter of writing one emitter function.

### 3. Code generation approach: template strings, not an AST

For each target language, a single `emit_<lang>(cases, entrypoint) -> str` function builds the tester file as a string. This is simpler than an AST builder for the constrained output we need.

### 4. JS/TS execution strategy

- JavaScript: `node tester.js` with the solution file path injected via a CLI arg or `require`/`import`
- TypeScript: `npx tsx tester.ts` (preferred over `ts-node` due to zero-config support)
- The solution is loaded via `require`/dynamic `import` using a path passed as `process.argv[2]`

*Alternative considered*: writing a temporary wrapper script — rejected as unnecessary; the tester itself can accept the solution path.

### 5. Result collection protocol

The tester files write their results to a temp JSON file (path passed as an env var or CLI arg). `babel_code_goat.py` reads that file after the subprocess exits. This avoids stdout pollution from the solution code interfering with result parsing.

*Alternative considered*: parsing subprocess stdout — rejected because solution code may write to stdout, making the result line hard to isolate reliably.

### 6. stdout/stderr capture

When `expect_stdout` or `expect_stderr` annotations are present, the tester redirects the entrypoint call's stdout/stderr using `io.StringIO` (Python) or stream capture (JS/TS) and compares them exactly after the call.

### 7. Value serialization across languages

Allowed value types map cleanly to JSON. Values are serialized to JSON in `tests.py` parsing and embedded as JSON literals in the generated tester, providing consistent cross-language deserialization.

`tuple` is treated as a list for JSON purposes (JS/TS have no tuple type); equality checks use deep structural comparison.

## Risks / Trade-offs

- **Subprocess startup latency** (node/tsx cold start): For large test suites, each `test` invocation pays a fixed startup cost. → Acceptable for the target use case (single invocation per evaluation).
- **`tsx`/`ts-node` availability**: The tool requires `tsx` or equivalent to be on PATH for TypeScript. → Document as a prerequisite; emit a clear error if missing.
- **AST changes across Python versions**: `ast` module behavior can differ. → Target Python 3.9+ and document the requirement.
- **Deep nesting of values**: Extremely deep structures could hit recursion limits in the value serializer. → Not a realistic concern given the constrained DSL.

## Migration Plan

This is a net-new file; no migration needed. Drop `babel_code_goat.py` into the repo root and it is immediately usable.

## Open Questions

- Should the TypeScript tester use `require` (CommonJS) or `import` (ESM)? → Default to CommonJS for broadest compatibility; add a `--esm` flag later if needed.
- Exact subprocess command for TypeScript: `npx tsx` vs `npx ts-node`? → Use `npx tsx` as the primary with fallback detection.
