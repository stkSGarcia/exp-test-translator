## 1. Coverage

- [x] 1.1 Add discovery tests for non-string dictionary keys, set, frozenset, Counter, deque, defaultdict, and Decimal values, including nested cases.
- [x] 1.2 Add execution tests for container-meaning equality and inequality across Python, JavaScript, and TypeScript testers where the target runtime can produce equivalent values.
- [x] 1.3 Add CLI tests for `test --tol <float>` applying to nested numeric comparisons without changing nonnumeric equality.
- [x] 1.4 Add discovery and execution tests for `math.isclose`, `abs(a - b) < tol`, and `abs(a - b) <= tol` per-assert tolerance overrides.
- [x] 1.5 Add discovery and execution tests for typed raise assertions, substring message matching, regex message matching, wrong exception types, and message mismatches.

## 2. Discovery And Test Model

- [x] 2.1 Extend the test case model to carry tagged value payloads, tolerance metadata, expected exception type, and message matcher metadata.
- [x] 2.2 Replace literal-only value normalization with a constrained AST parser for supported literals and constructor calls.
- [x] 2.3 Allow only the import forms needed for supported collections, Decimal, math.isclose, and re.search while preserving discovery failure for other executable code.
- [x] 2.4 Parse typed raise blocks and validate supported handler bodies for pass-only, substring, and regex message checks.
- [x] 2.5 Parse math.isclose and absolute-difference tolerance assertions into executable comparison metadata.

## 3. Comparison And Execution

- [x] 3.1 Implement deterministic tagged value encoding and decoding or normalization helpers for supported containers and Decimal values.
- [x] 3.2 Implement deep comparison helpers that preserve dictionary key identity, unordered set/frozenset semantics, Counter counts, deque order, defaultdict contents, and Decimal numeric semantics.
- [x] 3.3 Apply default tolerance and per-assert tolerance policies only to applicable numeric equality and inequality comparisons, including nested structures.
- [x] 3.4 Update Python execution to evaluate typed raise expectations and message matchers.
- [x] 3.5 Update generated JavaScript/TypeScript tester helpers to consume the tagged payloads, compare supported values, apply tolerance policies, and evaluate typed/message raise expectations.

## 4. CLI And Payload Flow

- [x] 4.1 Add `--tol <float>` to the `test` subcommand and pass the effective default tolerance into tester execution.
- [x] 4.2 Preserve tester payload extraction and regenerated-discovery validation with the expanded test model.
- [x] 4.3 Ensure unsupported values, unsupported imports, malformed tolerance assertions, and malformed typed raise blocks produce discovery errors with the existing error JSON contract.

## 5. Verification

- [x] 5.1 Run the full test suite and update any existing assertions affected by the richer payload model.
- [x] 5.2 Manually exercise representative `generate` and `test` flows for Python, JavaScript, and TypeScript targets with the new comparison features.
- [x] 5.3 Run `openspec status --change support-rich-python-test-comparisons` and confirm the change is apply-ready.
