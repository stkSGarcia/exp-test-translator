## Why

The harness needs every discovered test to map to exactly one invocation of the configured entrypoint so pass/fail results remain traceable and unambiguous. The checkpoint also requires common primitive operations around that single call, so useful assertions can be translated without permitting arbitrary multi-call logic.

## What Changes

- Enforce a single-entrypoint-call constraint for each discovered assertion or expectation block.
- Reject assertion expressions that contain multiple entrypoint invocations or multiple non-primitive function calls.
- Allow supported primitive operations over numbers, strings, and containers inside traceable assertions when they still depend on exactly one entrypoint invocation.
- Preserve existing supported comparison, tolerance, output, exception, and JSON result behavior while tightening discovery rules for unsupported multi-call constructs.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `babel-code-goat-cli`: Refines test discovery and traceability requirements for allowed assertion expressions and primitive operations.

## Impact

- Updates Python AST discovery and validation for assertion expressions.
- Updates generated runner metadata or execution plans as needed to evaluate primitive operations while preserving one traced entrypoint result.
- Adds focused regression tests for single-call acceptance, multi-call rejection, and primitive operation coverage across supported languages.
