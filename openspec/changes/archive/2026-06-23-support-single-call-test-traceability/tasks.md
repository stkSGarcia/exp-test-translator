## 1. Discovery Model

- [x] 1.1 Add a serializable primitive expression representation that can contain constants, one entrypoint-result placeholder, unary/binary operations, comparisons, membership, indexing, and whitelisted primitive helpers.
- [x] 1.2 Implement an AST normalizer that walks assertion expressions, serializes supported primitive operations, and records exactly one configured entrypoint invocation with serialized arguments.
- [x] 1.3 Reject assertions with zero configured entrypoint calls, more than one configured entrypoint call, unsupported helper calls, or unsupported Python constructs by raising `DiscoveryError`.
- [x] 1.4 Update `parse_assert` to handle entrypoint calls on either comparison side, membership assertions, primitive wrappers such as `sorted(ENTRYPOINT(...))`, and primitive numeric/container expressions.
- [x] 1.5 Preserve existing typed raise parsing, rich literal serialization, stdout/stderr expectation comments, `math.isclose`, and absolute-difference tolerance behavior while routing applicable expressions through single-call validation.

## 2. Tester Evaluation

- [x] 2.1 Extend the discovered test payload so generated testers can distinguish legacy direct-call assertions from primitive expression assertions during execution.
- [x] 2.2 Add primitive expression evaluation to the Python tester, ensuring the solution callable is invoked exactly once per test before expression evaluation.
- [x] 2.3 Add equivalent primitive expression evaluation to the JavaScript tester source.
- [x] 2.4 Add equivalent primitive expression evaluation to the TypeScript tester source.
- [x] 2.5 Keep pass/fail/error JSON output, result coverage accounting, and stdout/stderr capture behavior unchanged for all existing test forms.

## 3. Coverage

- [x] 3.1 Add discovery tests for right-hand entrypoint calls, membership assertions, primitive numeric expressions, primitive container access, and `sorted(ENTRYPOINT(...))`.
- [x] 3.2 Add rejection tests for multiple entrypoint calls, assertions with no entrypoint call, and unsupported helper calls wrapping the entrypoint.
- [x] 3.3 Add end-to-end Python execution tests proving primitive expression assertions pass/fail correctly and invoke the entrypoint once per test.
- [x] 3.4 Add generated JavaScript and TypeScript tester coverage for the supported primitive expression operations.
- [x] 3.5 Run the existing unit test suite and focused CLI scenarios for supported languages.
