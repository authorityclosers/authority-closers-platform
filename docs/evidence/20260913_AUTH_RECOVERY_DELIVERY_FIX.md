# Production recovery email incident and fix

## Observed behavior

On 13 September 2026, production recovery requests for an unverified password
account returned the expected neutral response but created no email challenge.
The user could not tell that initial verification, rather than a password reset,
was required. The no-token verification page also presented an invalid-link
error instead of the normal pending-verification state.

Read-only runtime investigation found a superseded earlier verification job and
a subsequently successful replacement. Current Resend delivery was working;
no current provider rejection or recovery hold was observed. Staging and
production identities remain separate.

## Change

- Recovery first attempts the existing password reset flow. If ineligible, it
  attempts the existing verification flow for an active unverified password
  account. Unknown, suspended, deleted and ineligible accounts retain the same
  neutral response. Verified passwordless accounts retain their existing
  mailbox-confirmed password setup behavior.
- Both challenge types use the canonical transaction, outbox and delivery path.
  Recovery itself creates no session and changes neither verification status
  nor password credentials. Course, activity and Sales continuation are retained.
- The verification page shows a pending state when no token is supplied, while
  rejected tokens still show an error. Recovery confirmation describes account
  recovery instructions without promising a password reset for every address.

## Validation

- 135 unit tests passed across Coach surface, password email continuity, Sales
  email continuity and password identity behavior.
- All 15 PostgreSQL password identity HTTP integration tests passed against a
  disposable database configured in UTC before migration. The database was
  dropped afterward. Coverage includes unknown, passwordless, suspended and
  deleted accounts, real verification consumption, and subsequent password reset.
- Scoped Ruff, formatting, mypy for the auth module, and git diff checks passed.
- UI validation: 16 focused and 120 extended tests, TypeScript, ESLint and
  Prettier passed before the final neutral confirmation wording adjustment.
- Independent combined review found no outstanding P0/P1; its earlier missing
  Coach test mock was corrected and included in the 135 passing tests.

## Real production browser evidence

On the existing production release 666dcd019987e83227bd3bec9451175fa9c03f96:

- A normal verification resend reached the user's Gmail inbox at 08:57 IST.
- Following that real email verified the account at 03:28:59 UTC. Normal
  onboarding then reached the authenticated learner home.
- Normal recovery after verification delivered reset emails at 09:05 and
  09:08 IST. The newest real email opened the production new-password form.
  No password was entered or changed by the operator.

No manual SQL recovery or identity bypass was used. Private email links and
credentials are deliberately absent from this evidence. These browser checks
prove current delivery and normal identity flows; the new source fix still
requires immutable CI artifacts and staging/production deployment.
