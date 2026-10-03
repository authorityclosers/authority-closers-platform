# AUT-447: Platform organisation members

The directory and members page at `/platform/organisations` consumes the
operator API frozen in PR #226 at `ccd99c0`. AUT-750's directory parser and GET
client are reused. No backend files, real memberships or environment settings
are changed.

The Platform console has separate identity and navigation from the academy
Admin shell. The navigation allowance is applied to the actual Platform
console's Organisations link rather than `admin-shell.tsx`. It requires
`platform_tenants_read`. Direct page admission requires the same capability;
write controls additionally require `platform_organisations_manage`.

Each action opens an explicit confirmation form naming the organisation and
target, requires a trimmed reason of 3–200 characters, and rechecks the current
person/session/selected context and grants before sending a command. Active
non-owner rows offer role change, removal and ownership transfer; invited rows
offer revocation. The server retains authority over all decisions. Every
dispatch gets a new UUIDv4 `Idempotency-Key`; concurrent submit events are
refused. Successful commands reload the directory and member rows. Errors
retain the reason and display the server's 403/404/409 detail verbatim as text.

Strict Zod parsers reject unknown response fields, roles, statuses, malformed
identifiers/dates and invalid usage values. Transport and parse failures have
an explicit retry state. Pending work is aborted when the page/form unmounts.

## Verification

- Organisation client suite: 51 tests passed.
- Focused Admin page/navigation suite: 32 tests passed.
- Admin TypeScript and lint passed.
- Tests use fictional `example.test` accounts and synthetic UUIDs only.

The live dev Platform read returned HTTP 403 from this run. No authenticated
dev journey is claimed. The real dev check follows the merge of backend PR
#226 and this PR, per the CTO's direction.

## Check on dev with fictional fixtures only

1. Sign in to admin-dev as a fictional operator granted both capabilities.
2. Open Platform → Organisations and choose a fictional organisation. Check
   member count, created date, member role/status, joined/last active dates and
   the server's 30-day minutes/calls.
3. Add a fictional email as member/admin, change a fictional active member's
   role, remove a member, transfer ownership and revoke a pending invitation.
   Each command must require a reason and explicit confirmation.
4. With read-only capability, verify that the directory is visible and all
   write controls are absent. Without read capability, verify that the link
   is absent and direct navigation makes no organisation requests.
5. Check exact 403/404/409 details with fictional failures. No SQL or real
   account changes are part of this check.
