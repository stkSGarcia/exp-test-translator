## Context

`babel_code_goat.py` discovers Python assertions from `tests.py`, serializes each discovered test, and emits language-specific testers. Today the parser accepts several explicit shapes, such as `ENTRYPOINT(args...) == expected`, `math.isclose(ENTRYPOINT(args...), expected, ...)`, and `abs(ENTRYPOINT(args...) - expected) < tol`. The checkpoint extends that surface: assertions must remain traceable to one configured entrypoint call, but the call can appear on either comparison side or inside primitive operations such as membership checks and sorting.

## Goals / Non-Goals

**Goals:**

- Discover each supported assertion only when it contains exactly one configured entrypoint invocation.
- Reject assertions that call the configured entrypoint multiple times, omit it, or depend on unsupported helper functions.
- Support primitive operations over numbers, strings, and containers around the entrypoint result while preserving existing tolerance helper behavior.
- Keep generated Python, JavaScript, and TypeScript testers driven by the same serialized test model.

**Non-Goals:**

- Supporting arbitrary Python execution during discovery or inside generated testers.
- Supporting user-defined helper functions, lambdas, comprehensions, generators, mutation, assignment expressions, or side-effecting calls in test assertions.
- Changing the CLI, test output JSON shape, test ID rules, stdout/stderr expectation comments, or solution callable resolution.

## Decisions

1. Normalize assertions around a single entrypoint placeholder.

   Discovery will walk the assertion AST and count configured entrypoint calls. Exactly one call becomes a placeholder with serialized arguments; zero or multiple calls raise `DiscoveryError`. This replaces fixed-position parsing for general assertions while preserving special parsing for typed raise blocks and tolerance helpers.

   Alternative considered: add a separate parser branch for every new assertion shape. That would be smaller initially, but it would keep spreading traceability rules across branches and make multi-call rejection brittle.

2. Serialize primitive expression evaluation as an explicit IR.

   When primitive operations wrap the entrypoint result, discovery will produce a compact expression tree that can be evaluated by each generated tester after invoking the solution once. The IR should cover constants, the entrypoint placeholder, unary and binary numeric/string operators, boolean combinations, comparisons, membership, indexing/slicing when supported, and whitelisted primitive helpers such as `sorted`. Existing value serialization remains responsible for literal argument and expected values.

   Alternative considered: evaluate the whole Python assertion expression at discovery time. That is impossible because the solution result is unknown during generation and would not work for JavaScript or TypeScript testers.

3. Treat tolerance helpers as whitelisted assertion helpers, not general function-call support.

   `math.isclose(...)`, `isclose(...)`, and supported `abs(...)` tolerance forms continue to produce tolerance metadata and must still contain exactly one entrypoint placeholder in the actual expression. Other calls are allowed only when they are already supported literal constructors or explicitly whitelisted primitive operations.

   Alternative considered: allow arbitrary pure-looking calls. Python AST cannot prove purity, and accepting helper calls would make generated cross-language testers depend on unavailable Python functions.

4. Classify unsupported assertion expressions as discovery errors.

   The existing error contract is simpler and safer than partially discovering valid tests while skipping unsupported ones. If a `tests.py` assertion cannot be normalized into the single-call primitive IR, discovery fails and the CLI returns the existing error JSON.

## Risks / Trade-offs

- [Risk] Primitive operation semantics can differ between Python and JavaScript, especially sorting, numeric edge cases, and container membership. -> Mitigation: define the supported operations narrowly and add cross-language tests for each operation that is represented in the IR.
- [Risk] The expression IR can grow quickly if it tries to model too much Python. -> Mitigation: start with the checkpoint examples and common primitive operations only, rejecting anything outside the whitelist.
- [Risk] Reworking assertion parsing could regress existing tolerance, rich value, or raise expectation support. -> Mitigation: keep existing tests, add focused discovery tests for old shapes, and add end-to-end tests for new primitive wrappers.
