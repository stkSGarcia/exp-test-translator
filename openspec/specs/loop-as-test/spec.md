# Spec: loop-as-test

## Purpose

For-loops and while-loops in `tests.py` are treated as test constructs. Each loop emits a loop-level test case (pass/fail based on whether the loop body executes at all), and each assertion inside the loop emits iteration-indexed test cases.

## Requirements

### Requirement: Loop statement is a test
A for-loop or while-loop statement SHALL itself be treated as a test construct with its own test ID equal to the line number of the `for` or `while` keyword.

The loop-as-test SHALL pass if the loop body executes at least once.
The loop-as-test SHALL fail if the loop iterates zero times or the iterable cannot be statically evaluated.

#### Scenario: Non-empty loop passes
- **WHEN** a for-loop iterates over a non-empty iterable
- **THEN** a `loop_pass` test case is emitted with ID `tests.py:<for_line>`

#### Scenario: Empty iterable loop fails
- **WHEN** a for-loop iterates over an empty list `[]`, `range(0)`, or empty string
- **THEN** a `loop_fail` test case is emitted with ID `tests.py:<for_line>` and no body assertions are emitted

#### Scenario: Unevaluable iterable loop fails
- **WHEN** the loop iterable cannot be resolved at parse time
- **THEN** a `loop_fail` test case is emitted; no body assertions are emitted

### Requirement: Loop body assertions have iteration-indexed IDs
Each assertion inside a loop body SHALL generate a test case with ID `tests.py:<assertion_line>:<iteration_index>` where `iteration_index` is the zero-based iteration number.

#### Scenario: Two iterations produce two assertion IDs
- **WHEN** an assertion on line 3 executes for 2 iterations
- **THEN** test cases `tests.py:3:0` and `tests.py:3:1` are emitted

#### Scenario: Multiple assertions per iteration
- **WHEN** a loop body contains two assertions (lines 4 and 5) and iterates twice
- **THEN** four test cases are emitted: `tests.py:4:0`, `tests.py:4:1`, `tests.py:5:0`, `tests.py:5:1`

### Requirement: Loop body assertions obey single-call traceability
Each assertion in a loop body SHALL trace to exactly one entrypoint invocation. The single-call traceability rules from non-loop assertions apply unchanged inside loop bodies.

#### Scenario: Two entrypoint calls in one assertion is an error
- **WHEN** an assertion inside a loop references the entrypoint twice (e.g. `assert add(a,b) == add(b,a)`)
- **THEN** the assertion is not recognized as a valid test case (no TestCase is emitted for it)

### Requirement: Variable binding for loop targets
When a for-loop iterates over a named variable, the variable SHALL be resolved from module-level assignments visible before the loop. Loop target variables SHALL be bound to their per-iteration values and available for resolving expressions in body assertions.

#### Scenario: Named list variable is resolved
- **WHEN** `cases = [(1,2,3)]` is assigned before a `for a,b,exp in cases:` loop
- **THEN** `a=1`, `b=2`, `exp=3` are available when parsing body assertions

#### Scenario: Starred expansion in entrypoint call
- **WHEN** a loop body contains `assert add(*args) == exp` and `args` is bound to `(1, 2)` in the current iteration
- **THEN** the entrypoint call args are resolved as `[1, 2]`

### Requirement: Supported for-loop patterns
The parser SHALL support the following for-loop forms:
- `for <target> in <list_or_variable>:` — direct iteration
- `for <idx>, <target> in enumerate(<iterable>):` — with enumerate
- `for i in range(<n>):` and `for i in range(<start>, <stop>):` — integer range

#### Scenario: Direct for-in loop
- **WHEN** a for-loop iterates `for a, b in [(1,2),(3,4)]:`
- **THEN** two iteration binding sets are produced: `{a:1, b:2}` and `{a:3, b:4}`

#### Scenario: Enumerate loop
- **WHEN** a for-loop iterates `for i, (a, b) in enumerate(cases):`
- **THEN** each iteration binds `i` to its 0-based index and unpacks `(a, b)` from the element

#### Scenario: Range loop with index access
- **WHEN** a for-loop iterates `for i in range(len(cases)):` and the body accesses `cases[i]`
- **THEN** each iteration binds `i` to the integer index; body subscript expressions using `i` are resolved

### Requirement: While-loop support
The parser SHALL attempt to statically simulate simple while-loops of the form `while <cond>:` where the condition and body use only evaluable expressions, simple assignment, and augmented assignment. If simulation fails or exceeds 1000 iterations, the loop-as-test SHALL fail and no body assertions are emitted.

#### Scenario: Counter-based while loop
- **WHEN** a while loop uses `i = 0` / `while i < len(cases):` / `i += 1` with assertions accessing `cases[i]`
- **THEN** the loop is simulated and body assertions are unrolled for each iteration

#### Scenario: Unevaluable while condition
- **WHEN** the while condition references values that cannot be statically evaluated
- **THEN** a `loop_fail` test case is emitted; no body assertions are emitted

### Requirement: Nested loop support
Nested loops SHALL be supported. Each loop level is independently treated as a loop-as-test.

#### Scenario: Outer and inner loops each have their own test
- **WHEN** an outer for-loop contains an inner for-loop
- **THEN** both loops emit their own loop-as-test IDs; inner loop body assertions use the inner loop's iteration index

#### Scenario: Nested loop with zero inner iterations fails inner loop-as-test
- **WHEN** the outer loop iterates once but the inner loop iterates zero times
- **THEN** the outer loop-as-test passes; the inner loop-as-test fails

### Requirement: Emitter support for loop_pass and loop_fail kinds
All three emitters (Python, JavaScript, TypeScript) SHALL handle `loop_pass` and `loop_fail` test-case kinds. A `loop_pass` case SHALL be appended to the `passed` list without calling the solution function. A `loop_fail` case SHALL be appended to the `failed` list without calling the solution function.

#### Scenario: loop_pass appended to passed
- **WHEN** the generated tester encounters a case with `kind == "loop_pass"`
- **THEN** the case ID is appended to `passed` and the loop is continued without calling the solution function

#### Scenario: loop_fail appended to failed
- **WHEN** the generated tester encounters a case with `kind == "loop_fail"`
- **THEN** the case ID is appended to `failed` and the loop is continued without calling the solution function
