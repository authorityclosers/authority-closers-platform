# Migration safety: root causes of the v0.86 failures (24 Oct 2026)

Owner, 24 Oct 2026 (~03:15 IST): "find out root cause and fix root cause so next time this does not happen".
v0.86 (PR #529) was blocked by four migration and CI failures. Each one had a root cause in our own checks, and each
is now fixed in the checks themselves, with tests.

**In one paragraph, for the owner.** Our migration checks disagreed with each other and ran too late. A test told
authors that new migrations must refuse every rollback, while the release gate demanded that they roll back, so
following the test broke the release. The release gate compared database schemas as raw text, and a backup and
restore rewrites that text, so correct rollbacks looked wrong. Nothing stopped an edit to a migration that was already
released until the release itself refused it. And these checks ran only on the release pull request, hours after the
code was written. Now the rule is one rule: every new migration may roll back while its tables are empty and must
refuse once they hold data. The gate compares schemas after the same backup-and-restore round trip on both sides. A
check refuses any change to a released migration. All of this runs on every workbench commit in wb-ci, minutes after
the change, without depending on the hand-published staging snapshot.

| # | What failed in v0.86 | Root cause | Fix | Caught now by |
|---|---|---|---|---|
| 1 | 0127 written as forward-only broke migration-safety | `test_checked_in_migrations_preserve_forward_only_recovery_policy` treated every revision outside a hand-kept list as forward-only (a downgrade that always raises); migration-safety rehearses upgrade, downgrade and re-upgrade, which such a downgrade fails | 3572ab22: the 82 revisions before 0088 are a frozen forward-only list; every other revision, including each new one, must use the history guard (refuse before changing anything when history exists, roll back when empty), tested per migration; no list edit for new migrations | the policy test in every Python run and in the wb-ci migrations job |
| 2 | "downgrade did not restore the baseline schema" for any downgrade that recreates an IN-list CHECK (0123 needed a hand-written workaround) | the gate compared raw `pg_dump` text; the baseline is restored from staging's dump, and PostgreSQL re-parses CHECKs on restore, so a freshly created constraint never matches the restored text | 366a8bd8: every compared schema goes through the same dump, restore into a scratch database, and dump again; a docker test recreates an IN-list CHECK (passes) and a different CHECK (fails); against the old gate the first case fails exactly as in v0.86 | the gate everywhere it runs |
| 3 | a wording sweep (d85f7fe1) edited released migration 0096's docstring; the gate refuses any rewrite of history, but only on the release PR | released migrations were editable, and no early check said so | 75b19015: `scripts/ci/released_migrations.py` fails when a migration on `origin/main` changes ("released migrations are history; add a new revision") | the wb-ci migrations job |
| 4 | authors learned of 1-3 and of shellcheck failures hours later | migration-safety and validate-control-plane ran only on the release PR | a8216e17: wb-ci gates. **migrations**: released history, recovery policy, gate fixtures and a rehearsal of the new revisions on a baseline built from the migrations (`--baseline-from-migrations`). **control-plane**: `scripts/validate-control-plane.sh` with the pinned ShellCheck. Both run whenever their paths change, even with `--py`/`--web`. Also fixed: the Python family matched `migrations/` instead of `db/migrations/`, so a migration-only commit ran no Python tests | every workbench commit |

**Rules for anyone adding a migration** (also in docs/ops/WORKBENCH-CI.md):
- A migration on `main` is history: never edit it, not even its docstring. Add a new revision.
- A new revision's downgrade uses the history guard: lock its tables, and if any history exists raise
  `RuntimeError("... history requires forward recovery.")` before changing anything; otherwise roll back. Nothing
  needs adding to a test list.

**Still manual.** The release PR's migration-safety rehearses on staging's schema export
(`AC_MIGRATION_SCHEMA_ARTIFACT_ID`), which a governed operator publishes with a one-day retention; it expired at 10:21Z
on 24 Oct. wb-ci no longer needs it, but each release PR with migrations still does, so a refresh before each such
release (or an automated daily export) remains a follow-up.
