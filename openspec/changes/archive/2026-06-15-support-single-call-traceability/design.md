## Context

`babel_code_goat.py` discovers tests from Python AST nodes and currently recognizes assertion shapes by finding the entrypoint call in a fixed syntactic position. That works for direct assertions such as `solve(1) == 2`, `math.isclose(solve(1), 1.0, ...)`, and `abs(solve(1) - 1.0) < tol`, but it does not model assertions where primitive operations wrap the entrypoint result, such as membership checks, sorting, arithmetic, string methods, or container indexing.

The checkpoint tightens the traceability contract: each discovered test must invoke the configured entrypoint exactly once. It also expands the allowed expression surface around that single invocation to include primitive operations over numbers, strings, and containers. Discovery must still reject unsupported code without executing `tests.py`, keep output and exception behavior unchanged, and run the same discovered test semantics for Python, JavaScript, and TypeScript solutions.

## Goals / Non-Goals

**Goals:**

- Enforce exactly one configured entrypoint invocation per discovered assertion or expectation block.
- Reject assertions that contain multiple entrypoint calls, multiple unsupported function calls, or arbitrary helper function calls beyond the documented tolerance helpers and primitive operations.
- Support primitive expression transforms and predicates around the single entrypoint result for numbers, strings, and containers.
- Preserve existing typed value encoding, tolerance handling, exception expectations, output expectations, IDs, JSON schema, and exit codes.
- Add focused tests showing accepted direct and wrapped single-call expressions, rejected multi-call expressions, and cross-language primitive operation execution.

**Non-Goals:**

- Supporting arbitrary Python execution, user-defined helper functions, assignment, mutation, comprehensions, fixtures, pytest, or unittest.
- Treating calls to non-primitive libraries as safe expression transforms.
- Guaranteeing exact Python semantics for every string/container method in JavaScript and TypeScript runners.
- Changing how tester files are generated, named, or preserved.

## Decisions

1. Add an AST trace analyzer that counts and extracts the configured entrypoint call before classifying an assertion.
   - Rationale: Traceability should be enforced uniformly instead of relying on each assertion parser to happen to accept only one call.
   - Approach: Walk each assertion expression, count calls to the configured entrypoint, reject zero or more than one, and reject non-allowlisted function calls unless they are part of supported helper assertions or primitive operations. For raise-expectation blocks, keep the current stricter form of one expression statement that directly calls the entrypoint.
   - Alternative considered: Extend each existing parser independently. That would duplicate call counting and make regressions likely when adding new assertion forms.

2. Represent supported wrapped assertions as an expression plan evaluated after the entrypoint returns.
   - Rationale: Existing `TestCase` data stores arguments and expected values, but primitive operations such as `sorted(solve([3, 1, 2])) == [1, 2, 3]` require transforming the actual result before comparison.
   - Approach: Add a small, serializable expression AST for the actual side of an assertion. The plan has one placeholder for the entrypoint result plus allowlisted operations such as unary/binary arithmetic, comparisons, boolean `not`, membership, indexing, slicing where supported, `len`, `sorted`, `sum`, `min`, `max`, `abs`, selected string methods, and selected container constructors. Python and Node runners evaluate the plan after invoking the solution exactly once.
   - Alternative considered: Evaluate the expression during discovery. That is impossible because the entrypoint result is only available at test execution time.

3. Keep primitive operation support explicit and deterministic.
   - Rationale: "Primitive operations" should not become arbitrary Python execution through method calls or constructor side effects.
   - Approach: Use an allowlist with clear operand validation. Permit operations only when every non-placeholder operand is a supported literal/tagged value or another allowed primitive expression. Reject lambdas, comprehensions, attribute access except allowlisted string methods, subscripting with unsupported indices, and calls to unknown names.
   - Alternative considered: Translating arbitrary Python AST into runner code. That would expand the execution surface and make JavaScript/TypeScript parity fragile.

4. Evaluate primitive expressions inside each target-language runner.
   - Rationale: The actual return value exists in the solution subprocess and may be a native Python object, JavaScript array, Set, Map, Error, or scalar.
   - Approach: Decode expected literals as today, invoke the solution once, then pass the actual return value through the expression-plan evaluator before applying the existing comparison, truthiness, tolerance, output, or exception logic. Node support maps allowed primitive operations onto JavaScript equivalents while preserving documented semantics for arrays, sets, maps/objects, strings, and numbers.
   - Alternative considered: Serialize actual values back to the parent process and evaluate there. Existing cross-language rich values and non-JSON objects make that lossy.

## Risks / Trade-offs

- The allowlist may reject valid-looking Python expressions that are outside the checkpoint scope -> Cover the accepted surface in specs and tests, and fail unsupported expressions during discovery with the existing error result.
- Python and JavaScript primitive semantics differ for edge cases -> Prefer simple operations with stable cross-language meaning and treat unsupported edge cases as failed tests or discovery errors.
- Expression-plan metadata increases runner complexity -> Keep the plan schema small, versioned through existing tester metadata if necessary, and reuse existing tagged value encoding.
- Counting calls separately from expression planning can drift -> Build the expression parser so it returns both the plan and the single traced call location, with tests for nested wrappers and rejection cases.

## Migration Plan

No migration is required. Existing tests remain valid. New primitive wrapped assertions are opt-in, and unsupported multi-call assertions continue to produce the existing discovery error result.

## Open Questions

None for the checkpoint scope.
