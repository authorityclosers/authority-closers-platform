# Sales Xray provider credential lifecycle audit

Date: 2026-09-22
Scope: read-only source and staging-host inspection; mounted credential values
were read only in memory to authenticate the self-metadata request and were
not printed or persisted. No provider payload, database, service, permission,
identity, or deployment state was mutated.

## Finding

The current worker does not auto-refresh provider credentials. The child
identity module reads the externally managed `token_file_ref` once when a
provider child starts, places the value in the sterile Infisical child
environment, and `exec`s the fixed provider command. The process broker passes
the same file reference to each new child. There is no expiry inspection or
refresh loop in `child_identity.py`, `inference_broker.py`, `service.py`, or
`service_config.py`.

`infra/conversation-worker/HOSTED_ACTIVATION.md` records the historical
operating boundary that the original ElevenLabs/Groq tokens expired after 24
hours and the Gemini testing token expired at 2026-09-20 22:53 UTC. Those
dates describe the original provisioned credentials, not the current mounted
credentials. The worker still does not refresh them, and the template mounts
individual provider directories rather than a parent secret directory.

## Read-only staging-host receipt

The `ssh ac` inspection identified host `ac-kvm4-prod`. Both staging and
production Sales Xray worker containers were running, with the four identity
directories and `/usr/local/bin/infisical` mounted read-only. The staging
worker used the reviewed `dd6ee881...` activation service file.

The fresh self-metadata probe was taken on 2026-09-22 against the same host
during the `9986cf2ee9ab421aa16c16ae3ccccedf1f1adf1f` staging checkpoint. It
supersedes the historical activation-note expiry claims for the currently
mounted ElevenLabs and Gemini credentials; those notes remain useful only as
provisioning history.

`systemctl list-timers --all` showed no Sales Xray, Infisical, token,
credential, or identity refresh timer. The matching installed units were the
native helper, startup recovery, and edge reconcile services; no provider
identity refresh service was present. The only identity files observed were
regular mode-0400 files owned by UID 10001/GID root. A read-only call to
Infisical's service-token self-metadata endpoint (`GET /api/v2/service-token`)
returned HTTP 200 for the mounted ElevenLabs and Gemini credentials. Both
reported the expected project, `dev` environment, and `read` permission, with
`expiresAt=null`; current Infisical validation treats a null expiry as
non-expiring. Their reported scope is the shared `/sales-xray-test` parent,
which differs from the worker's provider-leaf path references and must remain
an explicit review finding. The child launcher fixes each provider command to
its provider-leaf path and the provider adapters select their expected key, so
this is a pre-existing least-privilege/path-isolation gap rather than a
current C2/C4 liveness blocker under the controlled `9986` approval. The
Deepgram and Groq credentials returned HTTP 404 from the same endpoint. No
token bytes or raw provider payloads were emitted.

The existing point-in-time C2/C4 success receipt and the fresh HTTP 200
self-metadata responses establish current ElevenLabs/Gemini liveness. They do
not establish automatic renewal. The historical expiry notes are stale for
those active credentials; the 404 responses for Deepgram/Groq remain a
separate availability finding.

## Durable remedy within current scope

No refresher or timer is justified by the current active credentials: the
authoritative self-metadata response reports them as non-expiring. If a future
equal-scope repair is approved, it must use an explicitly designated
management credential, preserve the observed project/environment/permission
and approved path contract, perform read-only metadata and child-scope
verification before an atomic regular-file replacement, and retain the old
file on failure. It must not repurpose a general VPS identity or broaden the
scope to recover the 404 credentials.

Any future refresh unit must be a separate, versioned operational artifact
rather than a container-side write path. Its release checks should prove the
fixed path allowlist, atomic replacement, permissions, no-secret logging, and
failure retention with synthetic opaque tokens. No such unit is installed or
required by this audit.

There is no current expiry blocker for the active ElevenLabs/Gemini
credentials. Current findings are the absent refresh automation as a
maintenance limitation, the historical-versus-current credential expiry
mismatch, the shared parent scope reported by the active self-metadata
endpoint, and the 404 responses for Deepgram/Groq.
