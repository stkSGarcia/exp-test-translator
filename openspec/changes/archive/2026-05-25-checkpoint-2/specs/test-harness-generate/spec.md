## MODIFIED Requirements

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

## ADDED Requirements

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
