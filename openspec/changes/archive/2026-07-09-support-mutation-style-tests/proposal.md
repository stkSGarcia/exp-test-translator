## Why

Mutation-style tests are a common way to validate functions that update an input object in place, but the current discovery contract is centered on expression-style assertions that directly call the entrypoint. Checkpoint 5 needs the harness to recognize a tightly constrained mutation pattern while rejecting ambiguous mutation uses during discovery.

Recursive test discovery is also needed so suites can be organized across a tests directory instead of requiring a single root `tests.py` file.

## What Changes

- Add support for mutation-style tests where an entrypoint call appears as a statement or assignment and is immediately followed by one or more assertions.
- Require each assertion in a mutation-style test group to reference at least one variable passed to the mutation call or directly assigned from it.
- Treat mutation patterns outside those constraints as discovery errors.
- Discover tests recursively from any `.py` file under `<tests_dir>`.
- Treat non-`.py` files with test-like names as discovery errors.
- Treat an empty recursive discovery result as a discovery error.
- Emit test IDs from the path relative to `<tests_dir>` using forward slashes, line numbers, and `#k` suffixes for multiple tests on one line.

## Capabilities

### New Capabilities
- `mutation-style-test-discovery`: Discovery, validation, and traceability rules for constrained in-place mutation tests and recursive test file discovery.

### Modified Capabilities
- `babel-code-goat-cli`: The CLI test discovery contract gains mutation-style test groups, recursive directory traversal, stricter discovery errors, and path-relative test IDs.

## Related Work

### Related Changes

- `support-loop-construct-tests`: Motivated by compact Python test patterns that were not recognized by the previous discovery contract. This change complements that work by adding another controlled non-call-in-assert pattern while preserving explicit discovery constraints.
- `support-single-call-test-traceability`: Motivated by broader expression support while keeping each discovered test traceable to one concrete entrypoint invocation. This change extends the traceability model to mutation calls by tying follow-up assertions to mutated or assigned variables.
- `add-babel-code-goat`: Established the CLI generation workflow and discovery surface for Python tests. This change builds on that CLI contract by expanding where tests are found and which supported test shapes can be translated.

### Related Specs

- `babel-code-goat-cli/support-single-call-test-traceability`: Defines traceable assertion discovery around exactly one entrypoint invocation. This change adapts that traceability rule for mutation-style calls followed by assertions over the mutated value.
- `babel-code-goat-cli/add-babel-code-goat`: Defines the root CLI, supported target generation behavior, and discovery/error reporting surface. This change reuses the same CLI discovery workflow and error contract.
- `babel-code-goat-cli/support-loop-construct-tests`: Defines allowed test constructs and discovery extensions for loop-based tests. This change follows the same pattern of accepting a constrained Python construct and rejecting unsupported variants as discovery errors.

## Impact

- Affected code likely includes the Python test discovery/parser, discovery error reporting, test ID generation, and generator inputs consumed by target-language runners.
- No new runtime dependencies are expected.
