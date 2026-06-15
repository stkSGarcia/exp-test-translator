## Context

`babel_code_goat.py` currently discovers a constrained Python `tests.py` file with `ast`, stores each test as a `TestCase`, and runs cases through Python or Node subprocess snippets. Values are currently limited to `ast.literal_eval` primitives, dictionaries require string keys, and equality is exact. Exception assertions only support the existing raise-any pattern.

The checkpoint expands the same CLI and runner contract rather than introducing a new workflow. The implementation should keep generation failure-safe, preserve the one-line JSON output contract for `test`, and continue rediscovering `tests.py` at test time while using the generated tester file for entrypoint and language metadata.

## Goals / Non-Goals

**Goals:**

- Expand discovery to parse supported Python container constructors and restricted helper imports without executing `tests.py`.
- Preserve Python container meaning across Python, JavaScript, and TypeScript runners, including non-string dictionary keys.
- Add default and per-assert numeric tolerance handling for floats and `decimal.Decimal`.
- Support typed exception assertions with substring and regex message checks.
- Keep existing IDs, output schema, exit-code behavior, and tester-file preservation guarantees.

**Non-Goals:**

- Supporting arbitrary imports, comprehensions, mutation, variables, fixtures, pytest, unittest, or executable setup code in `tests.py`.
- Implementing a general Python-to-JavaScript object model for every Python type.
- Adding external runtime dependencies beyond the existing Python standard library and optional Node runtime for JavaScript and TypeScript execution.
- Defining broad exception type mapping between Python and JavaScript beyond matching the discovered exception type name against the thrown error metadata.

## Decisions

1. Replace raw literal payloads with a typed value representation at the runner boundary.
   - Rationale: JSON object keys cannot preserve non-string dictionary keys, and JSON arrays cannot distinguish lists, tuples, sets, frozensets, counters, deques, and decimals.
   - Approach: Convert discovered values into tagged structures such as scalar, list, tuple, dict entries, set, frozenset, counter entries, deque, defaultdict entries, and decimal string. Decode those tags inside the Python runner and into practical JavaScript equivalents inside the Node runner.
   - Alternative considered: Continue using plain JSON with lossy conversions. This would fail non-string dict keys and blur container semantics.

2. Implement an AST-based supported-value parser instead of extending `ast.literal_eval`.
   - Rationale: `ast.literal_eval` cannot parse `set(...)`, `frozenset(...)`, `collections.Counter(...)`, `deque(...)`, `defaultdict(...)`, or `decimal.Decimal(...)` calls, and the harness must still avoid executing `tests.py`.
   - Approach: Track restricted imports and aliases for `math`, `re`, `collections`, `Counter`, `deque`, `defaultdict`, `decimal`, and `Decimal`; accept only known constructor call shapes with supported literal arguments.
   - Alternative considered: Execute `tests.py` in a sandbox and inspect resulting values. This would reintroduce discovery side effects and miss assertions inside uncalled functions.

3. Extend `TestCase` with comparison and exception metadata.
   - Rationale: Per-assert tolerance and typed raise behavior belong to individual discovered tests, while `--tol` is a default applied when no per-test override exists.
   - Approach: Add fields for comparison mode, absolute tolerance, relative tolerance, expected exception type, message matcher kind, and message pattern. The aggregator passes the CLI default tolerance into execution so each runner can resolve the effective comparison settings.
   - Alternative considered: Encode tolerance only in expected values. That makes `math.isclose` and `abs(...) < tol` harder to represent and does not model typed exception assertions.

4. Centralize comparison behavior inside each runner snippet.
   - Rationale: Actual return values exist inside the target-language subprocess, so tolerance and container comparison must run there after the solution call.
   - Approach: Python uses native container decoding plus recursive comparison helpers. Node decodes tags into arrays, maps, sets, decimal strings/numbers as appropriate and uses recursive comparator functions that understand the same tags and Python truthiness rules.
   - Alternative considered: Serialize actual results back to the parent process for comparison. This would struggle with JavaScript `Set`, `Map`, custom errors, and non-JSON values.

5. Treat typed exception names as discovered strings.
   - Rationale: Python built-in exception classes can be resolved directly in the Python runner, while JavaScript/TypeScript solutions may expose custom error classes or names that intentionally match the Python test expectation.
   - Approach: For Python, compare raised exceptions with the named built-in exception class. For Node, compare the thrown value's constructor name and `name` property to the expected type string. Message substring and regex checks run against `str(exc)` in Python and `String(error.message ?? error)` in Node.
   - Alternative considered: Maintain a broad Python-to-JavaScript exception translation table. That would be speculative and could surprise solutions that intentionally throw named custom errors.

## Risks / Trade-offs

- Tagged value encoding increases implementation complexity -> Keep the tag schema small, deterministic, and covered with focused discovery plus execution tests.
- JavaScript equivalents for Python containers are necessarily approximate -> Compare by documented container meaning and avoid promising arbitrary Python behavior beyond the checkpoint.
- Decimal precision may be lossy in JavaScript if coerced to `number` -> Preserve decimal source strings in value tags and use numeric conversion only for tolerance comparisons where the spec calls for numeric behavior.
- Restricted import and alias handling may reject creative but valid Python spelling -> Document and test the supported import forms instead of expanding into general name resolution.
- Regex behavior differs slightly between Python and JavaScript -> Use source patterns that both runners can evaluate and treat invalid runner-side regexes as failed tests.

## Migration Plan

No migration is required. Existing supported tests continue to discover and execute as before. New `--tol` behavior is opt-in and defaults to exact numeric comparison when omitted.

## Open Questions

None for the checkpoint scope.
