## 1. IR and Parser Foundations

- [x] 1.1 Add `mutation_check: int | None = None` field to `TestCase` dataclass in `babel_code_goat.py`
- [x] 1.2 Define `DiscoveryError` exception class in `babel_code_goat.py`
- [x] 1.3 Add `file_prefix: str = "tests.py"` parameter to `parse_tests` and thread it through to the ID-assignment logic so all emitted IDs are prefixed with `<file_prefix>:`

## 2. Mutation Test Parsing

- [x] 2.1 Add a helper `_collect_names(node: ast.expr) -> set[str]` that recursively collects all `ast.Name` identifiers referenced in an expression
- [x] 2.2 In `_collect_stmts`, detect `ast.Expr` statements whose value is an entrypoint call; collect the names of positional args (those that are `ast.Name` nodes) as mutation-tracked variables and record their current values from `bindings`
- [x] 2.3 After detecting a mutation call statement, consume the immediately following `ast.Assert` statements from the statement list; for each assert, call `_collect_names` on the test expression and validate that at least one mutation-tracked name appears — raise `DiscoveryError` if not
- [x] 2.4 For each valid mutation assertion, determine the `mutation_check` index (position of the referenced arg in the call's arg list) and emit a `TestCase` with `kind`, `args`, `expected`, and `mutation_check` set appropriately
- [x] 2.5 Detect `ast.Assign` with a single `ast.Name` target whose RHS is an entrypoint call; treat the assigned name and any `ast.Name` args as mutation-tracked; emit test cases for immediately following assertions (assignment target → `mutation_check=None`; arg names → `mutation_check=<idx>`)

## 3. Tester Emitters — Mutation Execution

- [x] 3.1 In `emit_python`, update the test-execution loop to check `c["mutationCheck"]` — when set, pass the args, call the function, then compare `args[c["mutationCheck"]]` to `expected` instead of the return value
- [x] 3.2 In `emit_javascript`, add the same `mutationCheck` handling: call `fn(...args)`, then evaluate `args[c.mutationCheck]` against `expected`
- [x] 3.3 In `emit_typescript`, add the same `mutationCheck` handling as JS with appropriate type annotations

## 4. Directory-Based Discovery

- [x] 4.1 Add `discover_test_files(tests_dir: Path) -> list[Path]` that uses `rglob("*.py")` to find all `.py` files, sorted by path; also scans all files for test-like non-`.py` names (`test*`, `*_test`, `tests`, `*_tests` with any non-`.py` extension) and raises `DiscoveryError` if any are found
- [x] 4.2 Update `cmd_generate` to call `discover_test_files` instead of directly looking for `tests.py`; iterate over discovered files, calling `parse_tests` with the appropriate `file_prefix` (relative path from `tests_dir` with forward slashes) for each; accumulate all test cases
- [x] 4.3 After accumulating test cases, raise `DiscoveryError` (caught by `cmd_generate`) if the list is empty
- [x] 4.4 Update `cmd_generate` to catch `DiscoveryError` (in addition to the existing `Exception` catch on `parse_tests`) and print to stderr with a non-zero exit

## 5. Verification

- [x] 5.1 Manually test the mutation case: create a minimal `tests_dir` with a `tests.py` containing `a = [2,0,2,1,1,0]; sort_colors(a); assert a == [0,0,1,1,2,2]`, run `generate`, confirm `tester.py` is created with the expected test case
- [x] 5.2 Manually test directory discovery: create a `tests_dir` with `sub/test_cases.py` containing a valid assertion, run `generate`, confirm the tester includes a test ID prefixed `sub/test_cases.py:`
- [x] 5.3 Manually test error cases: non-`.py` test-like file, empty discovery, and out-of-constraint mutation assertion each produce a non-zero exit with an error message and no tester file
