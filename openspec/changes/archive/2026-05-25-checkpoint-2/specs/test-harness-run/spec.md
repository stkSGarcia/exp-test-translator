## ADDED Requirements

### Requirement: test command accepts --tol flag
The `test` sub-command SHALL accept an optional `--tol <float>` argument that sets the default absolute tolerance used for floating-point comparisons in generated testers. When `--tol` is not supplied, exact equality is used for floats (matching checkpoint 1 behavior).

The tolerance is applied to:
- `kind="eq"` and `kind="ne"` comparisons where the expected value is a float or Decimal, or a nested structure containing floats or Decimals
- It is NOT applied to `kind="truthy"`, `kind="falsy"`, or `kind="raises"` cases

Per-assert tolerance overrides (from `math.isclose`, `abs(a-b) < tol`) take precedence over the global `--tol`.

#### Scenario: --tol enables near-equal float comparison
- **WHEN** `test <solution> <tests_dir> --lang python --tol 0.01` is run and the solution returns a float within 0.01 of the expected value
- **THEN** the test case is reported as passed

#### Scenario: --tol failure when difference exceeds tolerance
- **WHEN** `test <solution> <tests_dir> --lang python --tol 0.001` is run and the solution returns a float differing from expected by more than 0.001
- **THEN** the test case is reported as failed

#### Scenario: Per-assert override takes precedence over --tol
- **WHEN** `test` is run with `--tol 0.5` and a specific test case was generated from `math.isclose(solve(x), y, abs_tol=0.001)`
- **THEN** that test case uses `abs_tol=0.001`, not `0.5`

#### Scenario: No --tol means exact float comparison
- **WHEN** `test` is run without `--tol` and the solution returns `3.14` but the expected value is `3.1400000001`
- **THEN** the test case is reported as failed (exact equality required)

#### Scenario: --tol applies to nested float in list
- **WHEN** `test` is run with `--tol 0.01` and the test asserts `solve() == [1.0, 2.0]` but the solution returns `[1.005, 1.995]`
- **THEN** the test case is reported as passed (tolerance applied recursively)
