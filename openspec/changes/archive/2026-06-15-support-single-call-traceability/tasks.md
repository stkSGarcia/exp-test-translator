## 1. Discovery Trace Model

- [x] 1.1 Add a small expression-plan data structure that can represent an entrypoint result placeholder, supported literals, primitive operations, comparisons, membership checks, indexing, and supported primitive calls.
- [x] 1.2 Implement AST analysis that extracts exactly one configured entrypoint invocation from each assertion expression and rejects zero or multiple entrypoint calls.
- [x] 1.3 Validate non-entrypoint calls against the allowed helper and primitive-operation surface, rejecting unsupported helper calls during discovery.
- [x] 1.4 Preserve direct existing assertion support, including entrypoint calls on either side of equality and inequality comparisons.

## 2. Assertion Parsing

- [x] 2.1 Update standard equality, inequality, truthy, and `not` assertion discovery to store an expression plan for the actual side instead of only raw entrypoint arguments.
- [x] 2.2 Add membership assertion support for single-call expressions such as `assert ENTRYPOINT(args...) in expected_container`.
- [x] 2.3 Add primitive wrapper support for expressions such as `sorted(ENTRYPOINT(args...))`, numeric arithmetic around the result, selected string methods, and supported container indexing.
- [x] 2.4 Keep `math.isclose(...)`, `abs(a - b) < tol`, `abs(a - b) <= tol`, raise-any blocks, and typed exception blocks compatible with the single-call trace rules.

## 3. Runner Evaluation

- [x] 3.1 Extend `TestCase` JSON encoding to include the expression plan while preserving existing tagged value encoding.
- [x] 3.2 Add Python runner evaluation for the supported expression-plan operations after invoking the solution exactly once.
- [x] 3.3 Add Node runner evaluation for the supported expression-plan operations for JavaScript and TypeScript solutions.
- [x] 3.4 Route equality, inequality, truthiness, membership, tolerance, stdout/stderr, and exception matching through the evaluated expression result without changing output JSON or exit codes.

## 4. Verification

- [x] 4.1 Add discovery tests for entrypoint calls on the right-hand side, membership assertions, primitive wrappers, and nested primitive expressions.
- [x] 4.2 Add rejection tests for multiple entrypoint calls and unsupported helper calls in assertion expressions and entrypoint arguments.
- [x] 4.3 Add Python execution tests proving each accepted assertion invokes the solution exactly once and evaluates primitive operations correctly.
- [x] 4.4 Add JavaScript and TypeScript smoke tests for membership, sorting or equivalent primitive wrappers, string operations, and rejection behavior when Node is available.
- [x] 4.5 Run the repository test suite and `openspec status --change "support-single-call-traceability"` to confirm the change is apply-ready.
