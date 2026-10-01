# Versioned watchdog source

C0 ([AUT-488](/AUT/issues/AUT-488)) imports the existing watchdog without changing
its executable logic. Root exported `/opt/ac-watchdog/ac_watchdog.py` on
2026-10-01T00:15:12Z under [AUT-585](/AUT/issues/AUT-585). Both the original and
sanitized artifact have SHA256
`a0482b5970e1d0089d0841a422e3585e0e7f1d701913123688ee0d9652562988`.
The 1,210 source lines are byte-identical; no redactions or config injection were
needed. The export scan reported zero credential-pattern matches. Provenance is
also recorded in `tests/infra/fixtures/ac_watchdog/c0.json` and
`docs/evidence/machine-fixes/C0.md`.

## Offline verification

From the repository's Python environment:

```bash
python3 -m pytest tests/infra/test_ac_watchdog.py -q
```

If system Python does not have the repository dependencies, use
`uv run python3 -m pytest tests/infra/test_ac_watchdog.py -q`.

Tests import the actual source with fake Telegram/database clients and no active
runtime credentials. They execute the unchanged `FREEZE` program, redirecting
only its home directory and lock file to fictional test paths. A real shared
`flock` prevents the exclusive approval write until release; exhausting the
existing 90 retries leaves state unchanged and refuses the merge. Tests preserve
the existing approval map and unrelated state, check the current literal lock
path `/run/ac-studio-sync/ac-studio-sync.lock`, and exclude `/run/user/1002`.
Fake GitHub responses also exercise the inherited merge hold, main/check and
freeze guards. No test sends a comment or merges a pull request.

The baseline is deliberately outside the repository's Python formatter/linter
targets (`packages/python` and `tests`). Formatting it would change the imported
digest. The new test file uses the normal repository checks. Later cards must
explicitly supersede the C0 byte-equality assertion when changing the source.

## SHA-pinned installer

The operator must first fetch the authoritative repository's `origin/main` and
check out the reviewed merged full SHA through the normal Root workflow. The
installer makes no network requests and trusts that fetched Git history. It
requires a lowercase full 40-character commit SHA, verifies that commit is an
ancestor of `refs/remotes/origin/main`, and compares both local source and
installer SHA256 digests with their executable regular-file blobs at that
revision. Dirty or mismatched files, symlinks, missing revision/merge evidence
and invalid arguments return exit 2 with:

```text
Refused: unverified watchdog source
```

```bash
bash infra/watchdog/install-watchdog.sh --dry-run --source-revision <merged-full-SHA>
```

Dry-run is also the default when neither mode is supplied. It exits 0 for a
verified source and writes no host files: no Git fetch, temporary files, runtime
config reads or service calls. Tests use private Git history representing a
merged revision, compare all repository files before/after, and trap host-write
commands. The pending C0 branch cannot pass the real merged-revision check before
merge; synthetic dry-run evidence is labelled accordingly.

Only the separate SHA-specific Root install task may run:

```bash
bash infra/watchdog/install-watchdog.sh --install --source-revision <merged-full-SHA>
```

Apply requires root and an existing, non-symlink `/opt/ac-watchdog` directory.
It materializes the verified Git blob into a temporary file in that directory,
checks its digest, sets root ownership and mode 0755, atomically replaces only
`/opt/ac-watchdog/ac_watchdog.py`, and verifies the installed digest. An identical
installed digest exits 0 without writing. It never creates or updates service
units, runtime configuration, credentials, state or logs. Root separately owns
the pre-install backup, recorded before/after digests, rollback source pin and
bounded service-health verification under the install card.

## Existing runtime dependencies

The unchanged source imports the existing `/opt/ac-watchdog/ac_telegram.py`
helper and `psycopg`. It keeps existing host paths for Paperclip configuration,
the root auth profile, GitHub CLI, per-lane checkouts and watchdog state, plus
the release/studio notification spools. These are runtime dependencies, not
files copied into Git or managed by this installer. No values from runtime
config, credentials, databases, state, logs or notification contents were read
for C0. Do not execute the watchdog's own `--dry-run` against the real runtime as
an offline test: that mode still reads Paperclip data.

After C0 merges, create/reuse the install card for the actual merged SHA and
block C1 on both C0 and its install. Host verification remains Root's work.
