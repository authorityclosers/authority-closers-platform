# Production fast call-data activation — AUT-2182

Authority: the owner's 21 October order relayed on AUT-2182; host steps linked to AUT-63.
Production is v0.76, `6548c9f5e194232f0f2b520b6b63e1e2c3ec8c59`. Routing remains with
Align 3's v0.77 delivery.

The operator script calls the existing Admin settings routes in-process using the
named control account's current canonical Admin session. It never reads a session
token. Route admission checks the current person, session, workspace and Admin
membership. Normal settings validation/revision/audit stays in the route. A second
append-only audit pins the owner order, issue, source script and release.

Dry-run is the default and rolls back the whole transaction. Apply writes fast ON
at ₹150/day, deep OFF, streaming OFF, preserving models and other limits. Repeated
apply is a no-op after admission. An absent or revoked session is refused. No SQL
write, schema change, backfill, new provider, streaming gate, ledger or scoring
change is introduced.

Verification before apply:

- Fictional disposable PostgreSQL proof: dry-run rollback, actual route write and
  owner-order audits, idempotency and revoked-session refusal — passed.
- Existing launcher tests — five passed.
- Ruff check/format and `uv run python -c 'import ac_platform.http'` — passed.
- Production dry run — exit 0; proposed revision 1; current deep ON would become
  OFF, fast remains ON/150, streaming remains OFF. Rolled back.
- Installed launcher and service already match the released bytes. Do not repeat
  completed installs: launcher SHA256
  `c283a3e8bb0865b170f8d2651b0434acd933cf1e3d66d66d37b5508ee8f6fac8`;
  service SHA256 `dc93727e4a5b076519475b882a508f850983ad527d9d998c0bf9d998294b6af0`.
- Production runner initially disabled/inactive; first-start marker absent.

The production snapshot, final setting revision/audit, activation, first-start
boundary, stability and natural-call counts/cost are recorded on the issue receipt
as they complete. No runtime activation is claimed by this source-only receipt.
Rollback: `systemctl disable --now ac-call-data@production`. Preserve all run,
settings and audit history.

## Production apply — 21 October, 14:38Z

Committed operator source: `418fd2e7`; script SHA256
`db4ae3a8652dad51e94ec2dc141688e897563703131fbfa5a630731e14f7bcea`.
Snapshot `20261021T143150Z-before-AUT-2182-fast-only` completed with verified
Drive copy, schema 0118, 15,213,126 bytes and 2,072 restore TOC entries. Dump SHA256:
`b3f8986c2035ae6c1d45c235731cbaec039046e84d0afc1aa87535ffc7160cfe`.

Settings apply exited 0, revision 1. Independent Admin route read-back confirms
fast ON/150, deep OFF and streaming OFF. Exactly one `call_data.settings_saved`
and one `call_data.production_fast_order` audit event exist. The route's current
control-account admission remains enforced.

Existing installed launcher/unit bytes matched v0.76 and were reused, preserving
completed prior work. Systemd was reloaded and the production unit enabled once.
First-start boundary: `2026-10-21T14:38:40+00:00`. Initial service read-back:
enabled, active/running, zero restarts, ExecMainStatus 0. The activation command's
immediate copy of the marker raced systemd startup and returned exit 1 after
successful enablement; subsequent read-back found the marker and recovered only
the receipt capture. Settings apply and service enablement were not replayed.
Production hold manifest matched before/after.

At 14:39:08Z, content-free Admin API verification reports zero starts/outcomes,
zero deep rows, zero backfills and zero automatic runs with pre-marker transcripts.
Admin AI spend includes the fast pipeline with cap 150/enabled, spend 0, and deep
cap 300/disabled, spend 0. No first successful fast run exists yet. No authenticated
browser UI or ten-minute stability result is claimed at this point.

Secure host receipt custody:
`/var/lib/ac-release/operator-evidence/AUT-2182/fb9c252e-78d8-4e1e-8021-fceef969e165/`.
Root retains responsibility for the ten-minute and next-natural-call verification
on AUT-2182. Close only the superseded call-data runner portion of AUT-2129 after
acceptance; preserve its unrelated backup dependencies and history.
