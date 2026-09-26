# Sales Xray provider credential provenance audit

Date: 2026-09-22
Scope: read-only source, receipt, and staging-host inspection. Mounted
credential values were read only in memory to authenticate self-metadata
requests and were not printed or persisted. No provider payload, identity,
permission, service, or deployment state was changed.

## Determination

The mounted provider files are Infisical **service-token credentials** where
the current self-metadata endpoint recognizes them. This is supported by the
source-owned provisioning receipt and helper retained outside Git: the
historical Deepgram provisioner authenticates its management step with a
Universal Auth login, then creates a read service token before installing the
token file. The current read-only probe recognized the mounted ElevenLabs and
Gemini credentials and returned their project, `dev` environment, `read`
permission, and `expiresAt=null`. The same endpoint returned 404 for Deepgram
and Groq. The active ElevenLabs/Gemini metadata reports the shared
`/sales-xray-test` parent scope rather than the worker's provider-leaf path
references. The child launcher fixes each provider command to its
provider-leaf path and the provider adapters select their expected key, so
this is a pre-existing least-privilege/path-isolation gap rather than a
current C2/C4 liveness blocker under the controlled `9986` approval. It is
recorded for review and is not treated as authorization to broaden or rotate
credentials. The runtime child receives only `INFISICAL_TOKEN` and fixed
project/environment/path references.

Infisical's current CLI documentation confirms that `INFISICAL_TOKEN` may be
either a Universal Auth access token or a service token. The runtime file
alone cannot distinguish those forms, but the self-metadata response and
retained Sales Xray provisioning evidence identify the active files as service
tokens. Current Infisical source makes `expiresAt` nullable and only rejects a
service token when that field is present and in the past; therefore
`expiresAt=null` means non-expiring for these active credentials. This is
different from the stale historical expiry notes.

## Host and file-name evidence

On `ac-kvm4-prod` via read-only `ssh ac`, the provider directories contained
only `token` leaves. The worker mounts those directories read-only and does not
mount the root bootstrap file. The root-owned bootstrap file names the keys
`INFISICAL_PROJECT_ID`, `INFISICAL_VPS_CLIENT_ID`,
`INFISICAL_VPS_CLIENT_SECRET`, `INFISICAL_BACKUP_CLIENT_ID`, and
`INFISICAL_BACKUP_CLIENT_SECRET`. A separate legacy `production.env` also
contains `INFISICAL_AGENT_CLIENT_ID` and `INFISICAL_AGENT_CLIENT_SECRET`, but
no checked-in worker or host unit connects those names to Sales Xray provider
refresh, and the file is not mounted into the worker.

No provider-specific client-id/client-secret file, refresh unit, or timer is
present. The only current host mechanism is the one-shot externally managed
token file. The source-owned Deepgram helper is an historical operator script,
not an installed refresh service; when an identity already exists it verifies
and reuses it rather than renewing it. Absence of a timer does not establish
absence of equal-scope repair authorization.

## Minimal supported renewal path and authorization boundary

If a future equal-scope repair is approved, the minimal path is replacement,
not renewal: an explicitly designated management credential must obtain a
fresh service token with the currently approved provider/project/environment/
path/read scope, verify its scope and metadata, then atomically replace the
corresponding host file while preserving the existing regular-file,
UID-10001, GID-root, mode-0400 contract. A failed replacement must retain the
old file and emit only a redacted status. This audit does not install or run
that path.

Infisical Universal Auth can mint short-lived access tokens and, only when the
identity is configured for a periodic token, renew them through the documented
renew endpoint. No provider-mounted Universal Auth client credential or
periodic-token configuration is evidenced here. The general VPS Universal
Auth identity is documented for application/backup secret delivery and must
not be repurposed for provider refresh without explicit owner authorization.

Any future implementation still needs the non-secret identity reference and
permitted API/CLI operation for its explicitly designated management
credential. The general VPS identity must not be substituted merely because a
timer is absent.

## Primary documentation

- [Infisical `run` authentication](https://infisical.com/docs/cli/commands/run)
  documents `INFISICAL_TOKEN` as either a machine-identity token or service
  token.
- [Infisical Universal Auth login](https://infisical.com/docs/api-reference/endpoints/universal-auth/login)
  documents client-id/client-secret login and the returned access-token
  lifetime.
- [Infisical Universal Auth renewal](https://infisical.com/docs/api-reference/endpoints/universal-auth/renew-access-token)
  documents renewal of a machine-identity access token.
- [Infisical Token Auth](https://infisical.com/docs/documentation/platform/identities/token-auth)
  documents direct service-token use and replacement after expiry.
- [Infisical service-token router](https://github.com/Infisical/infisical/blob/main/backend/src/server/routes/v2/service-token-router.ts)
  documents the current `GET /api/v2/service-token` self-metadata route.
- [Infisical service-token service](https://github.com/Infisical/infisical/blob/main/backend/src/services/service-token/service-token-service.ts)
  shows nullable `expiresAt` and expiry enforcement only when it is present.
