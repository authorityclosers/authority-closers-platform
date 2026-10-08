# AUT-1247: canonical smoke script release packaging

Source base: `b1ac586144490d2176fc15db5a5f13cd176a92c6` (main), including
PR #336's installer/engine changes merged as
`869a79e5993ee67fd940d80e09f29541eade13a7`.

## Implementation

- `infra/application/release-source-files.txt` opts the target revision into
  packaging exactly `scripts/data-changes/production-smoke-email-verification.py`.
  The engine validates that single allowed path and includes its exact Git blob
  in the same commit-bound archive. Missing source or an unsupported manifest
  fails closed. Older revisions without the manifest retain their old archive
  contract, including revisions that already contain an unbundled script.
- The archive verifier requires the manifest and canonical regular file. It
  retains the archive digest, commit, traversal, non-regular entry and verifier
  identity checks, and rejects duplicate paths, sibling scripts and collisions
  with the installed canonical path.
- The installer projects application files to the release root and preserves
  the canonical script's repository-relative path. Its existing manifest writer
  includes the script in `RELEASE-FILES.sha256`; immutable release/image reuse,
  provenance checks and activation behavior are unchanged.
- Normal staging delivery already updates the engine from validated main before
  proceeding with application delivery on the next tick. No manual install or
  alternate artifact path was added.

## Verification on 7 October 2026

- Approved canonical SHA-256 remains
  `11aae24a9301bb9eb9efee5a8dbb4535911cdba38ebd1c0ff2cc187d8366ce43`.
  The canonical script itself was not edited or executed.
- Real Git archives prove exact-commit selection despite an uncommitted file
  replacement, legacy archive compatibility, rejection of missing source and
  unsupported source manifests.
- An inert Bash harness runs the real installer extraction function and its
  manifest-generation block in a temporary test directory. It proves installed
  relative path, byte equality and approved digest. Manifest verification detects
  tampering and a missing installed script. Archive checks also reject missing
  source, unapproved siblings, symlinks, duplicates and projected path collisions.
- Relevant pytest suites: **416 passed, 1 skipped** in 31.14 seconds. The only
  skip requires an unavailable Docker daemon. Suites: application release,
  archive, guards, recovery, release engine and foundation installation.
- Ruff lint/format, Bash syntax and `git diff --check` pass for the changed areas.
  Test temporaries use the run-owned Paperclip scratch directory.

## Delivery acceptance still required

Sensitive infrastructure: CTO review, CEO approval bound to the PR head, then
watchdog merge and normal validated CI delivery. Local packaging tests do not
prove an installed serving release. The installed staging path will be
`/srv/authority-closers/application/current-staging/scripts/data-changes/production-smoke-email-verification.py`.
Root performs the final dev/staging read-only hash, consent-flag/AST and readiness
checks on AUT-1244 after ordinary delivery. Production snapshot/preview/apply
remains AUT-398. No host, database, secrets, service, timer, dev-refresh or
production operation was performed for this repair.
