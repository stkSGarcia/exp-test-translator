# Spec: test-parsing

## Purpose

The test parser reads `tests.py` and extracts test cases from assertions and loop constructs. This spec covers the internal parsing rules that govern how Python source is interpreted into structured test data.

## Requirements

### Requirement: Variable assignment tracking
The parser SHALL track module-level `ast.Assign` statements where the target is a simple name and the RHS is a constant-evaluable expression. These bindings SHALL be available to subsequent loop and assertion parsing within the same scope.

#### Scenario: Variable assigned before loop is available
- **WHEN** `cases = [(1, 2)]` appears before a for-loop
- **THEN** `cases` is available as a binding when evaluating the loop iterable

#### Scenario: Variable not yet assigned is not available
- **WHEN** the for-loop appears before any assignment of the variable it iterates
- **THEN** the loop iterable is treated as unevaluable and the loop-as-test fails

### Requirement: Loop statements are not transparent
For-loops and while-loops SHALL be handled by dedicated loop processing logic rather than transparently recursing into the body. The loop processor is responsible for emitting the loop-as-test and any unrolled body assertions.

#### Scenario: For-loop no longer produces un-indexed assertion IDs
- **WHEN** an assertion inside a for-loop is processed
- **THEN** its test ID uses iteration-indexed format (`tests.py:<line>:<iter>`), not the plain `tests.py:<line>` format used for top-level assertions

### Requirement: _ast_to_value accepts bindings
The `_ast_to_value` helper SHALL accept an optional `bindings` mapping. When a `Name` node is encountered and the name is present in bindings, the stored value SHALL be returned. All recursive calls within `_ast_to_value` SHALL propagate the bindings.

#### Scenario: Name node resolved from bindings
- **WHEN** `_ast_to_value(ast.Name('x'), bindings={'x': 3})` is called
- **THEN** it returns `3`

#### Scenario: Unknown name raises ValueError
- **WHEN** `_ast_to_value(ast.Name('y'), bindings={})` is called and `y` is not a recognized constant call
- **THEN** it raises `ValueError`

### Requirement: Entrypoint call arg collection handles starred args
When collecting arguments from an entrypoint call node, the parser SHALL handle `ast.Starred` argument nodes by expanding the bound value into the positional argument list.

#### Scenario: Starred tuple expansion
- **WHEN** the entrypoint call is `add(*args)` and `args` is bound to `("__tuple__", [1, 2])`
- **THEN** the collected args list is `[1, 2]`

#### Scenario: Starred list expansion
- **WHEN** the entrypoint call is `fn(*vals)` and `vals` is bound to `[10, 20, 30]`
- **THEN** the collected args list is `[10, 20, 30]`
