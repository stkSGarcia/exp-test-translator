# Spec: test-harness-generate

## Purpose

The `generate` sub-command parses a `tests.py` file and produces a language-specific tester file that can later be executed by the `test` command.

## Requirements

### Requirement: Generate command produces a tester file
The `generate` sub-command SHALL parse `tests.py` in `<tests_dir>`, resolve the target language from `--lang`, and write a single tester file into `<tests_dir>`. The written file SHALL be `tester.py` for `--lang python`, `tester.js` for `--lang javascript`, and `tester.ts` for `--lang typescript`.

#### Scenario: Python tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.py` is created and the process exits `0`

#### Scenario: JavaScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang javascript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.js` is created and the process exits `0`

#### Scenario: TypeScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang typescript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.ts` is created and the process exits `0`

### Requirement: Unsupported language is an error
The `generate` command SHALL reject any `--lang` value that is not `python`, `javascript`, or `typescript`.

#### Scenario: Invalid lang rejected
- **WHEN** `generate <tests_dir> --entrypoint solve --lang ruby` is run
- **THEN** the process exits non-zero and no tester file is created or modified

### Requirement: Generate failure leaves no tester file
If `generate` fails for any reason (missing `tests.py`, parse error, I/O error), it SHALL NOT create or modify `tester.py`, `tester.js`, or `tester.ts` in `<tests_dir>`.

#### Scenario: Missing tests.py
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and `<tests_dir>/tests.py` does not exist
- **THEN** the process exits non-zero and `<tests_dir>/tester.py` is not created

#### Scenario: Partial write rolled back on error
- **WHEN** `generate` begins writing the tester file but encounters an error mid-write
- **THEN** no partial tester file remains in `<tests_dir>`

### Requirement: Test discovery parses tests.py constructs
The generator SHALL discover and emit a tester case for each of the following constructs in `tests.py`:
- `assert ENTRYPOINT(args) == expected`
- `assert ENTRYPOINT(args) != expected`
- `assert ENTRYPOINT(args)`
- `assert not ENTRYPOINT(args)`
- `assert expected == ENTRYPOINT(args)` (call on right-hand side — treated as `eq`)
- `assert expected != ENTRYPOINT(args)` (call on right-hand side — treated as `ne`)
- `assert ENTRYPOINT(args) in container` (membership — produces `kind="in"`)
- `assert prim(ENTRYPOINT(args)) == expected` where `prim` is a supported primitive operation (see Requirement: Primitive operation transforms)
- `assert prim(ENTRYPOINT(args)) != expected` where `prim` is a supported primitive operation
- Raise-any block: `try: ENTRYPOINT(args); assert False\nexcept Exception: pass`
- Lines preceded by `# expect_stdout: "<literal>"` or `# expect_stderr: "<literal>"`

Assertions inside function bodies SHALL be discovered even if the function is never called.

#### Scenario: Equality assertion discovered
- **WHEN** `tests.py` contains `assert solve(1, 2) == 3`
- **THEN** the generated tester contains a test case that calls the entrypoint with `(1, 2)` and asserts the result equals `3`

#### Scenario: Raises assertion discovered
- **WHEN** `tests.py` contains the raise-any block pattern
- **THEN** the generated tester contains a test case that asserts the entrypoint raises any exception

#### Scenario: Assertions inside functions discovered
- **WHEN** `tests.py` contains `def test_foo(): assert solve(0) == 0` but `test_foo` is never called
- **THEN** the generated tester still includes a test case for that assertion

#### Scenario: expect_stdout annotation applied
- **WHEN** `tests.py` has `# expect_stdout: "hello\n"` on the line immediately before an assertion
- **THEN** the generated tester captures stdout during that call and asserts it equals `hello\n`

#### Scenario: Call on RHS of equality
- **WHEN** `tests.py` contains `assert 3 == add(1, 2)`
- **THEN** the generated tester contains a test case that calls the entrypoint with `(1, 2)` and asserts the result equals `3`

#### Scenario: Call on RHS of not-equal
- **WHEN** `tests.py` contains `assert 0 != add(1, 2)`
- **THEN** the generated tester contains a test case that calls the entrypoint with `(1, 2)` and asserts the result does not equal `0`

#### Scenario: Membership assertion discovered
- **WHEN** `tests.py` contains `assert add(1, 2) in [1, 2, 3]`
- **THEN** the generated tester contains a test case that calls the entrypoint with `(1, 2)` and asserts the result is a member of `[1, 2, 3]`

#### Scenario: Membership assertion passes when result is in container
- **WHEN** the entrypoint returns `3` and the test asserts `add(1, 2) in [1, 2, 3]`
- **THEN** the test case is reported as passed

#### Scenario: Membership assertion fails when result is not in container
- **WHEN** the entrypoint returns `5` and the test asserts `add(1, 2) in [1, 2, 3]`
- **THEN** the test case is reported as failed

#### Scenario: Primitive-wrapped call discovered
- **WHEN** `tests.py` contains `assert sorted(f([3, 1, 2])) == [1, 2, 3]`
- **THEN** the generated tester contains a test case that calls the entrypoint with `([3, 1, 2])`, applies `sorted` to the result, and asserts it equals `[1, 2, 3]`

#### Scenario: Primitive-wrapped call passes when transform matches
- **WHEN** the entrypoint returns `[3, 1, 2]` and the test asserts `sorted(f([3, 1, 2])) == [1, 2, 3]`
- **THEN** the test case is reported as passed

### Requirement: Test IDs are line-based
Each test case in the generated tester SHALL be identified as `tests.py:<line>` (1-based line number of the assertion or raise-any block). When multiple tests originate from the same line, they SHALL be disambiguated as `tests.py:<line>#0`, `tests.py:<line>#1`, etc.

#### Scenario: Single test on a line
- **WHEN** an assertion is the only test on line 5 of `tests.py`
- **THEN** its ID in the tester output is `tests.py:5`

#### Scenario: Multiple tests on same line
- **WHEN** two tests originate from line 7
- **THEN** their IDs are `tests.py:7#0` and `tests.py:7#1`

### Requirement: Allowed argument and expected value types
The generator SHALL support the following value types in assertion arguments and expected values: `None`, `bool`, `int`, `float`, `str`, `list`, `tuple`, `dict` (with keys of any hashable constant type), `set`, `frozenset`, `decimal.Decimal`, `collections.Counter`, `collections.deque`, `collections.defaultdict`. Nested combinations SHALL be supported. Equality SHALL be deep/structural according to each container's semantics.

#### Scenario: Nested dict/list round-trips
- **WHEN** `tests.py` contains `assert solve({"a": [1, 2]}) == {"b": (3,)}`
- **THEN** the generated tester encodes and compares these values with deep equality in the target language

#### Scenario: Non-string dict key
- **WHEN** `tests.py` contains `assert solve({1: "a", (2, 3): "b"}) == {}`
- **THEN** the generated tester encodes the dict with integer and tuple keys and compares with deep equality

#### Scenario: set argument and expected value
- **WHEN** `tests.py` contains `assert solve({1, 2, 3}) == {4, 5}`
- **THEN** the generated tester encodes the sets and asserts structural set equality (order-independent)

#### Scenario: frozenset expected value
- **WHEN** `tests.py` contains `assert solve() == frozenset({1, 2})`
- **THEN** the generated tester encodes the frozenset and asserts structural equality

#### Scenario: Decimal argument and expected value
- **WHEN** `tests.py` contains `from decimal import Decimal; assert solve(Decimal("1.5")) == Decimal("3.0")`
- **THEN** the generated tester treats Decimal values as numeric and asserts numeric equality

#### Scenario: Counter expected value
- **WHEN** `tests.py` contains `from collections import Counter; assert solve("aab") == Counter({"a": 2, "b": 1})`
- **THEN** the generated tester encodes the Counter and asserts structural equality

#### Scenario: deque argument
- **WHEN** `tests.py` contains `from collections import deque; assert solve(deque([1, 2, 3])) == [1, 2, 3]`
- **THEN** the generated tester encodes the deque and compares with sequence equality

#### Scenario: defaultdict expected value
- **WHEN** `tests.py` contains `from collections import defaultdict; d = defaultdict(int); d["x"] = 1; assert solve() == d`
- **THEN** the generated tester encodes the defaultdict entries and compares by dict equality

### Requirement: Solution callable forms
The generated tester SHALL support two forms of entrypoint resolution:
1. A module-level callable named exactly as `--entrypoint`
2. A class with the same name as `--entrypoint`, constructible with zero arguments, with an instance method or static method of that name

#### Scenario: Module-level function used
- **WHEN** the solution exports a function named `solve`
- **THEN** the tester calls `solve(args...)` directly

#### Scenario: Class method used
- **WHEN** the solution exports a class named `solve` with a method `solve`
- **THEN** the tester instantiates `solve()` and calls `.solve(args...)`

### Requirement: Test discovery supports typed raises with message matching
The generator SHALL discover and emit a tester case for typed raises blocks where a specific exception type is expected, optionally with a message assertion. Supported patterns are:

```py
try:
    f(args)
    assert False
except SomeError as e:
    assert "substring" in str(e)
```

and the regex variant:

```py
import re
try:
    f(args)
    assert False
except SomeError as e:
    assert re.search(r"pattern", str(e))
```

#### Scenario: Typed raises with string-contains message match
- **WHEN** `tests.py` contains a `try/except ValueError as e: assert "bad" in str(e)` block around `ENTRYPOINT(args)`
- **THEN** the generated tester contains a test case that asserts the entrypoint raises `ValueError` and the message contains `"bad"`

#### Scenario: Typed raises with regex message match
- **WHEN** `tests.py` contains a `try/except ValueError as e: assert re.search(r"bad", str(e))` block
- **THEN** the generated tester contains a test case that asserts the entrypoint raises `ValueError` and the message matches the regex `bad`

#### Scenario: Typed raises without message assertion
- **WHEN** `tests.py` contains a `try/except TypeError as e: pass` block around `ENTRYPOINT(args)`
- **THEN** the generated tester contains a test case that asserts the entrypoint raises `TypeError` (any message)

#### Scenario: Typed raises with wrong exception type fails
- **WHEN** the entrypoint raises `KeyError` but the test expects `ValueError`
- **THEN** the test case is reported as failed

#### Scenario: Typed raises with correct type but wrong message fails
- **WHEN** the entrypoint raises `ValueError("good message")` but the test expects the message to contain `"bad"`
- **THEN** the test case is reported as failed

### Requirement: Test discovery supports per-assert tolerance overrides
The generator SHALL detect and extract tolerance parameters from the following per-assertion patterns when the assertion tests the entrypoint result:

- `assert math.isclose(ENTRYPOINT(args), expected, abs_tol=<val>, rel_tol=<val>)` (either or both keyword args)
- `assert abs(ENTRYPOINT(args) - expected) < tol` and `<= tol`

When detected, the test case SHALL carry the extracted tolerance values and the emitted tester SHALL apply them to the numeric comparison.

#### Scenario: math.isclose with abs_tol
- **WHEN** `tests.py` contains `assert math.isclose(solve(x), 3.14, abs_tol=0.01)`
- **THEN** the generated tester asserts the result is within `abs_tol=0.01` of `3.14`

#### Scenario: math.isclose with rel_tol
- **WHEN** `tests.py` contains `assert math.isclose(solve(x), 1000.0, rel_tol=0.001)`
- **THEN** the generated tester asserts the result is within relative tolerance `0.001` of `1000.0`

#### Scenario: abs(a - b) < tol pattern
- **WHEN** `tests.py` contains `assert abs(solve(x) - 2.5) < 0.05`
- **THEN** the generated tester asserts the absolute difference between the result and `2.5` is less than `0.05`

#### Scenario: abs(a - b) <= tol pattern
- **WHEN** `tests.py` contains `assert abs(solve(x) - 2.5) <= 0.05`
- **THEN** the generated tester asserts the absolute difference between the result and `2.5` is at most `0.05`

### Requirement: Primitive operation transforms
The generator SHALL recognise and support the following primitive operations when wrapping a single entrypoint call in an assertion: `sorted`, `len`, `list`, `set`, `tuple`, `str`, `int`, `float`, `abs`, `sum`, `min`, `max`. Any other wrapping call SHALL NOT be matched as an entrypoint assertion.

Each emitter SHALL apply the equivalent operation in the target language before evaluating the comparison.

#### Scenario: sorted transform in Python tester
- **WHEN** `tests.py` contains `assert sorted(f([3, 1, 2])) == [1, 2, 3]` and `--lang python`
- **THEN** the generated `tester.py` calls `f([3, 1, 2])` and passes the result through `sorted()` before comparing to `[1, 2, 3]`

#### Scenario: sorted transform in JavaScript tester
- **WHEN** `tests.py` contains `assert sorted(f([3, 1, 2])) == [1, 2, 3]` and `--lang javascript`
- **THEN** the generated `tester.js` calls the entrypoint, applies a JS-equivalent sort, and asserts equality with `[1, 2, 3]`

#### Scenario: sorted transform in TypeScript tester
- **WHEN** `tests.py` contains `assert sorted(f([3, 1, 2])) == [1, 2, 3]` and `--lang typescript`
- **THEN** the generated `tester.ts` calls the entrypoint, applies a TypeScript-equivalent sort, and asserts equality with `[1, 2, 3]`

#### Scenario: len transform
- **WHEN** `tests.py` contains `assert len(f([1, 2, 3])) == 3`
- **THEN** the generated tester calls the entrypoint, applies a length operation, and asserts the result equals `3`

#### Scenario: Unsupported primitive not matched
- **WHEN** `tests.py` contains `assert custom_fn(f(1)) == 2` where `custom_fn` is not in the supported primitives list
- **THEN** the generator does NOT produce a test case for that assertion

### Requirement: Single-call constraint
Each test case produced by the generator SHALL be traceable to exactly one entrypoint invocation. Assertions that contain zero or more than one entrypoint call SHALL NOT be matched as test cases.

#### Scenario: Single call on LHS matched
- **WHEN** `tests.py` contains `assert f(1) == 1`
- **THEN** a test case is produced

#### Scenario: Single call on RHS matched
- **WHEN** `tests.py` contains `assert 1 == f(1)`
- **THEN** a test case is produced

#### Scenario: No entrypoint call not matched
- **WHEN** `tests.py` contains `assert 1 == 1`
- **THEN** no test case is produced for that assertion

#### Scenario: Multiple entrypoint calls not matched
- **WHEN** `tests.py` contains `assert f(1) == f(2)`
- **THEN** no test case is produced for that assertion
