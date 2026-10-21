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
