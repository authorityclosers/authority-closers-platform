# AUT-1677 — prepared Company human-save acknowledgement

Source base: Report `d986c9e`, integrating main `d2c2caa`. The existing Company
identity, four-field and actor/session read contracts are reused. This module
is prepared for the reviewed storage integration; no Company route or persisted
editor is mounted, and no API-ready claim is made.

`saveCompanyFields` sends one explicit PUT to the opaque Company's `/fields`
route with the expected revision and detached literal human text or Unknown.
It admits only name, industry, city and size. Company name requires text;
phone/email, numeric reinterpretation, source metadata and coercible Unknown
reasons are refused before transport. String bounds match the existing read
codec, so a command cannot claim a value that its acknowledgement cannot open.

The 200 acknowledgement must parse through the existing Company detail codec
and match person, tenant, session and Company ID. Its revision cannot precede
the expected revision, and every requested field must match exactly with
`basis=person` and a human lock. A same-value idempotent acknowledgement may
retain the revision. Human Unknown reads retain the lock without an old value.
The server remains responsible for permissions, optimistic conflict checks,
append-only history and audit; this client cannot grant them.

The shared response reader caps both advertised and streamed bytes at 128 KiB.
The existing 2.5-second read boundary also bounds acknowledgement transport and
cancels the underlying request. A 409 asks for reload. A missing route, pending
202, redirect, failed request, malformed/large acknowledgement, timeout or
changed scope yields an unconfirmed save without disclosing the response.
There is no automatic retry of an uncertain write.

Verification: the focused Company save and Report Coaching read batch passes
49 cases; the adjacent Company codecs/reads/pages and Report preload/Coaching
batch passes 126 cases. Incremental app typecheck and changed-file cached ESLint
pass. Cases cover foreign scopes/identities, stale revisions, mismatched or
unlocked values, Unknown locks, invalid commands, single-request failures,
bounded stalled responses and mutation of caller-owned values during transport.
All values and responses are fictional and local; no real API write occurs.
