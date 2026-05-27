## MODIFIED Requirements

### Requirement: Generate command produces a tester file
The `generate` sub-command SHALL parse `tests.py` in `<tests_dir>`, resolve the target language from `--lang`, and write a single tester file into `<tests_dir>`. The written file SHALL be `tester.py` for `--lang python`, `tester.js` for `--lang javascript`, `tester.ts` for `--lang typescript`, `tester.cpp` for `--lang cpp`, and `tester.rs` for `--lang rust`.

#### Scenario: Python tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang python` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.py` is created and the process exits `0`

#### Scenario: JavaScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang javascript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.js` is created and the process exits `0`

#### Scenario: TypeScript tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang typescript` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.ts` is created and the process exits `0`

#### Scenario: C++ tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang cpp` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.cpp` is created and the process exits `0`

#### Scenario: Rust tester generated
- **WHEN** `generate <tests_dir> --entrypoint solve --lang rust` is run and `<tests_dir>/tests.py` exists
- **THEN** `<tests_dir>/tester.rs` is created and the process exits `0`

### Requirement: Unsupported language is an error
The `generate` command SHALL reject any `--lang` value that is not `python`, `javascript`, `typescript`, `cpp`, or `rust`.

#### Scenario: Invalid lang rejected
- **WHEN** `generate <tests_dir> --entrypoint solve --lang ruby` is run
- **THEN** the process exits non-zero and no tester file is created or modified
