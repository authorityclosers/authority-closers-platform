# M1b: AST-only additive migration exception

Task: [AUT-660](/AUT/issues/AUT-660). Base: `8e3fe3e` (main after the merged M1a PR).
Sources: [approved M1 plan](/AUT/issues/AUT-589#document-plan), revision
`8c9f8dbb-4f41-4f78-96aa-e62e7cee1cb7`; [CEO amendment](/AUT/issues/AUT-631#document-amendment),
revision `c663a58e-c3c9-46e6-b0bc-61c9e860cca1`.

## Implementation

The public contract `classify_changed_files(files, contents, *, changed_files, truncated=False)`
is unchanged: same inputs, `routine`/`escalation`, sorted unique reason codes, no IO.
For a record with status `added` whose filename starts `db/migrations/` (exact case) and ends
`.py`, `_additive_migration` parses the supplied head string with `ast.parse` and never
executes, compiles to bytecode or imports it. Only when it proves the upgrade additive does the
classifier drop `protected:migration` and `path:unknown-root` for that filename. The check runs
before unknown-root refusal; every other protected rule (names, secrets, instructions) still
applies to the same path. Modified, removed and renamed migrations (either rename direction)
keep both reasons.

Accepted `upgrade()` statements, and nothing else (docstring and `pass` allowed):

- `op.create_table("t", ...)`: only `sa.Column` items and `sa.PrimaryKeyConstraint` of string
  literals; `schema` (string) and `if_not_exists` (bool) options.
- `op.create_index(name, "t", [literal columns])`: `name` a string or `op.f("...")`; `unique`
  omitted or literal `False`; no `postgresql_where` or expression columns.
- `op.add_column("t", sa.Column(...))`: explicit `nullable=True`, or a static non-None
  `server_default`; never `primary_key=True`.

Columns take a literal name and an allowlisted `sa.*` or `postgresql.JSONB/TSVECTOR` type whose
arguments are `int`/`bool` literals only, with keywords limited to `length`, `timezone`,
`precision`, `scale`, `asdecimal` and `as_uuid` (type arguments are written into DDL raw, so
string precisions and `collation` escalate). Column keywords are limited to `nullable`,
`server_default`, `primary_key` (literal bools) and `comment`. A static default is a string
literal (SQLAlchemy quotes it), `sa.func.now()`, `sa.false()`, `sa.true()`, or
`sa.text("<sql>")` whose whole string is one of: a signed integer or decimal, `true`, `false`,
`now()`, or one single-quoted literal with no `'`, `;`, `\` or `--` inside, optionally followed
by `::jsonb`. `sa.text` is written into DDL unchanged, so anything else (multi-statement SQL,
function calls such as `gen_random_uuid()`, casts other than `::jsonb`, comments) escalates. Positional `ForeignKey`, FK/unique/check
constraints, `sa.Index`, `sa.Enum`, `unique=`/`index=` and `**kwargs` all escalate: this is
narrower than the `migration_safety` helper's additive allowlist, which is not the merge rule.

Because Alembic imports the whole file, the module level is also restricted: docstrings,
an allowlist of imports (`from alembic import op`, `import sqlalchemy as sa`,
`from sqlalchemy.dialects import postgresql`, `__future__`, `collections.abc.Sequence`,
`typing.Any`), literal `revision`/`down_revision`/`branch_labels`/`depends_on` assignments with
call-free annotations, and exactly one undecorated, argument-free `upgrade()` (an optional single
`downgrade()`; its body is not inspected). Anything else (helpers, relative imports, rebinding
`op`, module calls, `if`/`class`, `async def`, defaults or decorators) escalates. Parse
failures, null bytes, deep nesting, missing or duplicate `upgrade()` escalate.

Against the 59 revision files on main (60 `.py` files with `env.py`), after the CTO review fix,
exactly 3 still qualify (`0024` plain index, `0048` add_column with
`sa.false()` default, `0061` nullable JSON column); all others use FK/check constraints,
`execute`, data writes or alter/drop and stay escalations.

## Tests

`tests/unit/test_merge_class.py` keeps every M1a fixture and adds fictional cases: 15 allowed
upgrade bodies plus 16 allowed `sa.text` default forms and a literal-int Numeric table; 73
disallowed bodies (unique/dynamic indexes, implicit vs explicit nullability, None/dynamic
defaults, FK/unique/check, string type arguments and collations, raw SQL, execute,
drop/alter/rename/batch, other ops, non-call statements) plus 25 unsafe `sa.text` defaults
(multi-statement, `gen_random_uuid()`, comments, quotes, casts, case and whitespace variants); 21 parse-error, missing/ambiguous upgrade and module-code
cases; merged-migration edit/delete/rename, wrong case or suffix and other protected rules;
missing contents; and a no-execution test with `open`/`exec`/`eval`/`__import__`/`os.system`/
`socket` patched to raise. Mutation sanity: removing the unique, nullability or import guard
each fails 2-3 tests.

## Verification (2026-10-02, platform lane checkout, repository venv)

- `PATH="$PWD/.venv/bin:$PATH" python3 -m pytest tests/unit/test_merge_class.py -q`:
  **589 passed**, exit 0 (M1a: 427; first M1b head `c16e433`: 537). Against `c16e433`'s
  classifier the same suite fails 31 of the new fixtures, including the CTO's
  `sa.text("0; DROP TABLE demo_victim; --")` and `sa.Numeric("10) CHECK (false")` cases.
- Ruff format/lint and mypy on both files; `pnpm run format:check`, `pnpm run lint`,
  `pnpm run typecheck`; `git diff --check`; `python3 scripts/ac_task.py check`: all exit 0.
  Remote CI/single-track receipts are on the PR; this offline evidence does not claim them.

No classifier result or merge approval grants owner permission. CTO review then CEO approval
stays mandatory until the verified synchronized Root switch; M2 waits for this PR to merge.
No screen, API, report, migration, workflow or watchdog changes; no browser QA applies.
