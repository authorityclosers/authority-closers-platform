# OpenAI worker access: verified prerequisite and provisioning blocker

Task: [AUT-2179](/AUT/issues/AUT-2179). Root run:
`7fa59631-02d7-4165-9e54-5b570ce09b50`, 21 October 2026, approximately
08:38–08:48 UTC. Host authorization/audit linkage: [AUT-63](/AUT/issues/AUT-63).
Source inspection pin: `3e09d69854f23095296d63b510b8ee915cd77be4` in dev/live.

## Result

The three stored `OPENAI_API_KEY` values match the requested fingerprints.
Workers cannot yet read them. No credential grant, installation or activation
was performed. [AUT-2180](/AUT/issues/AUT-2180), assigned to CEO for the existing
laptop Infisical administrator, must return environment-scoped credentials via
secure references. This is required execution material under the task's existing
authorization, not a new processor approval or key purchase.

## Secret-store verification

The existing root-only `ac-infisical-run` logs in as `ac-vps-runtime` and invokes
`infisical run`. Each child checked that `OPENAI_API_KEY` was nonempty and printed
only `sha256(value)[:12]`. Values remained in process memory; no provider call was
made. Project: `b421c44e-4599-4394-8df6-758ed8aedfed`.

| Infisical environment | Path | SHA256 prefix | CLI exit |
| --- | --- | --- | --- |
| dev | /sales-xray-test/openai | 4963df676805 | 0 |
| staging | /sales-xray/openai | f1044ecfa216 | 0 |
| prod | /sales-xray/openai | 24aa6dfd9fbe | 0 |

This proves root runtime read access and the stored-key fingerprints only.

## Current worker evidence

- Dev Gemini token: `/etc/authority-closers/development/identities/gemini/token`.
- Hosted Gemini token:
  `/etc/authority-closers/secrets/sales-xray/identities/gemini/token`.
- Both resolve through the metadata API to service token
  `81e17e85-d087-4960-9206-10c649fc1788`, name `Sales Xray staging provider read`,
  permissions `[read]`, scope `dev:/sales-xray-test`, no expiry.
- Worker-token CLI probes with the requested OpenAI environments/paths exited
  zero but had no `OPENAI_API_KEY`. A Gemini control probe had `GEMINI_API_KEY`;
  even a requested OpenAI path still injected Gemini. CLI success is not access
  proof. These host probes used the installed worker token; no claim is made
  that they ran inside each worker's sandbox.
- The historical hosted OpenAI token at the dedicated leaf returns metadata
  HTTP404. It was not overwritten, removed, copied or revoked.
- Both hosted containers currently have Gemini mounts and no OpenAI mount or
  OpenAI service-manifest entry. Their current Gemini references remain
  `dev:/sales-xray-test/gemini`, as already investigated in
  [AUT-1584](/AUT/issues/AUT-1584). Changing other providers is outside this task.
- Dev service manifests contain ElevenLabs/Gemini only. The dev one-pass wrapper
  supplies the Gemini token; its runner re-execs under Gemini `infisical run`.
- At inspection, `ac-one-pass@development-live` was active; staging and production
  one-pass units were inactive. No start/stop/restart was attempted.

## Authority limitation and safe continuation

Root's bootstrap contains runtime and backup machine credentials, not a logged-in
Infisical user/admin session. The project membership API confirms
`ac-vps-runtime` (`738561a8-b16c-45f1-8cfc-30d1ee55c54c`) has the built-in Viewer
role. Existing worker service tokens are read-only. The official
[service-token router](https://github.com/Infisical/infisical/blob/main/backend/src/server/routes/v2/service-token-router.ts)
accepts user JWT authentication for service-token creation; it does not accept
machine-identity or service-token authentication there. No grant mutation was
attempted using an incompatible identity, and no broader credential was delivered
to a worker.

The administrator must provide one read-only OpenAI token for each environment
and return only secure Infisical/password-manager references and nonsecret scope
metadata. Root will then install with secure backups and guarded rollback, verify
environment-specific mounts and child injection, and require the three expected
fingerprints under the actual worker identities. Keep the shared Gemini token
unchanged. The hosted validators' fixed shared OpenAI host-directory contract
must gain environment-specific support through source and normal release controls;
do not bypass it or edit live manifests by hand.

## Preserved state and checks

- `ac-root check`: exit 0. Normal-agent live-runs read: one active Root run,
  below the cap of three.
- Credential metadata, mount metadata, unit state and membership reads succeeded;
  the historical OpenAI metadata HTTP404 is retained as an adverse result.
- No host/Infisical mutation, database write, inference, real call processing,
  account/settings/purchase change, service lifecycle call or release occurred.
- No `production.HELD-*` files were present at inspection; none were changed.
- Root checkout remains clean main. Foreign dev/live application edits remain
  untouched. Changes in this run are documentation only.
- Documentation checks passed: `git diff --check`, all three expected
  fingerprints and pending-access wording, both relative evidence links, and
  checks for accidental raw-key/token assignment text. No application test,
  typecheck or build is needed for these documentation-only changes.
