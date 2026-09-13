# Provider controls: live API contract correction

Actual Chrome testing on staging showed the verified control administrator could
open Sales Xray settings, but the panel displayed "Provider controls unavailable."
The same-origin `GET /v1/admin/conversation/providers` returned HTTP 200. Its
catalog includes the documented `deployment` field; the frontend's strict schema
omitted that field and rejected every catalog entry. No provider configuration
had been saved (`current` was null).

The correction admits the four deployment kinds defined by the Python contract:
hosted, gateway, local and deterministic_tool. It retains strict validation and
all authorization, zero-paid-spend and dormant-configuration behavior.

The reproduction fixture is the public catalog and empty configuration returned
by the staging API, captured on September 13. It contains no session headers,
credentials, person identifiers or saved private configuration. The mounted panel
test first failed with the observed unavailable message, then passed after the
schema correction; it also clicks Add model and verifies that the selector opens.

- Red: `D:/AC-authority-closers-release-audit/provider-catalog-live-red.xml`.
- Green: `D:/AC-authority-closers-release-audit/provider-catalog-live-green-v2.xml`,
  seven passed, zero skips/failures/errors.
- Node 24.19.0; TypeScript and targeted ESLint passed. Prettier corrected only
  the new fixture and affected test formatting.

This is a local correction reproduced from live evidence. It has not yet been
deployed or verified in the staging browser after deployment. The existing API
did not activate inference or make a paid call during inspection.
