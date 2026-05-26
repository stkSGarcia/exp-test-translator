## MODIFIED Requirements

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

## ADDED Requirements

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
