## ADDED Requirements

### Requirement: parse_tests accepts a file_prefix argument for ID generation
The `parse_tests` function SHALL accept an optional `file_prefix: str` argument. When provided, all generated test IDs SHALL be prefixed with `<file_prefix>:` (e.g., `subdir/tests.py`) instead of the bare `tests.py:` prefix. When not provided, the prefix defaults to `tests.py` for backwards compatibility.

#### Scenario: Prefix applied to plain assertion ID
- **WHEN** `parse_tests(source, "solve", file_prefix="subdir/test_cases.py")` is called and the source has an assertion on line 4
- **THEN** the resulting test case ID is `subdir/test_cases.py:4`

#### Scenario: Prefix applied to loop-as-test ID
- **WHEN** `parse_tests` is called with `file_prefix="nested/foo.py"` and the source has a for-loop on line 2
- **THEN** the loop-as-test ID is `nested/foo.py:2`

#### Scenario: Default prefix is tests.py
- **WHEN** `parse_tests` is called without `file_prefix`
- **THEN** test IDs use the `tests.py:` prefix (existing behaviour unchanged)

### Requirement: Mutation call statements are parsed into test cases
The `_collect_stmts` function SHALL recognise `ast.Expr` nodes whose value is an entrypoint call as mutation call statements. When found, the immediately following `ast.Assert` statements that reference at least one argument variable are collected as mutation test cases. A `DiscoveryError` is raised if a following assertion does not reference any argument variable.

#### Scenario: Mutation statement followed by valid assertion
- **WHEN** source contains `fn(a)` as a statement followed by `assert a == expected`
- **THEN** `_collect_stmts` emits a `TestCase` with `mutation_check=0`, `args=[initial_a]`, `expected=expected_value`

#### Scenario: Mutation statement followed by invalid assertion raises DiscoveryError
- **WHEN** source contains `fn(a)` as a statement followed by `assert 1 == 1` (no reference to `a`)
- **THEN** `_collect_stmts` raises `DiscoveryError`

### Requirement: Mutation call assignments are parsed into test cases
The `_collect_stmts` function SHALL recognise `ast.Assign` nodes where a single target is a name and the RHS is an entrypoint call. The immediately following assertions referencing the assigned name or any argument variable are collected as test cases. Assertions checking the assigned name use `mutation_check=None` (return value check). Assertions checking an argument variable use the appropriate `mutation_check` index.

#### Scenario: Assignment followed by assertion on assigned name
- **WHEN** source contains `result = fn(x)` followed by `assert result == expected`
- **THEN** a `TestCase` is emitted with `mutation_check=None`, `args=[x_value]`, `expected=expected_value` (standard return-value check)

#### Scenario: Assignment followed by assertion on argument variable
- **WHEN** source contains `r = fn(a)` followed by `assert a == expected_a`
- **THEN** a `TestCase` is emitted with `mutation_check=0`, `args=[initial_a]`, `expected=expected_a`

### Requirement: DiscoveryError is raised for out-of-constraint mutation patterns
A new `DiscoveryError` exception class SHALL be defined and raised by `parse_tests` (or its helpers) in the following situations:
- An assertion immediately following a mutation call does not reference any mutation-tracked variable
- Any other mutation pattern detected outside the defined constraints

#### Scenario: DiscoveryError is a distinct exception type
- **WHEN** a constraint violation occurs during parsing
- **THEN** a `DiscoveryError` is raised (not `ValueError` or other generic exceptions), allowing callers to distinguish discovery violations from parse errors
