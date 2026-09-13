# Dedicated hosted Sales Xray service

The hosted worker now has an explicit startup command, independent of API
Settings and the ordinary outbox worker. The API accepts authorized uploads and
plans; this service drains durable work through retention, native C1 inspection,
plan advancement, then admitted C2/C4/C5 inference. Persisted checkpoints remain
reusable when a judge/profile changes. Existing authorization, minute and money
reservations, publication fences and retention remain in the domain workers.

Hosted intake issues the exact `audioatlas-16000-v1` recipe. Local 48 kHz work
retains `audioatlas-48000-v1`. The quote, worker and publication checks bind the
recipe to its exact rate, window profile, native source, source bytes and retained
feature artifact. A hosted worker rejects a pending 48 kHz quote before execution;
intake and the run route reject pre-cutover quotes with an instruction to prepare
the call again. Stop old intake and drain its accepted jobs before changing the
API/worker together; do not reinterpret or manually rewrite queued quotes.

Transcription planning and private draft import use the same verified C1 selector.
Planning prefers the hosted profile when both exist; an import attached to an
existing run selects that run's exact recipe. C2 still depends on the original
C0 source checkpoint, so changing the measurement or coaching profile reuses the
transcript. PostgreSQL tests cover separate C1 persistence, reuse, unchanged C2
identity, exact quote admission and refusal to execute a quote for another rate.

`python -m ac_platform.conversation_intelligence.service --config <absolute-file>
--sha256 <manifest-digest>` is the supervised entry point. `--check` validates
references and the installed exact release without reading credentials or
starting workers; it is not a provider/connectivity/confinement test.

Before the first bind mounts, run the same pinned image/manifest as UID10001
with `--prepare-storage` and mount only the approved private parent directory
(plus manifest). This initializes both new roots through the storage adapter,
including its ownership marker. It reads no DB/provider credential. An existing
directory without the marker is refused; do not fabricate the marker or adopt
an unrelated directory. Existing owned roots are verified idempotently. Provision
the helper's bounded output filesystem after scratch initialization. The ordinary
worker overlay then mounts only the individual roots, not the parent directory.

## Release-owned inputs

The strict JSON manifest uses schema_version `ac.sales_xray.worker_service/1`.
Required fields:

| Field | Meaning |
| --- | --- |
| environment / release_id | staging or production, and exact 40-character image release marker |
| sales_xray_approval_path / sales_xray_approval_sha256 | Existing exact hosted approval bundle and its digest |
| sales_xray_storage_root / sales_xray_scratch_root | Different absolute private roots shared with the API/helper |
| database_url_file | External DB-only credential file; read by the worker at runtime |
| native_socket_path / native_image_ref | Private helper socket and immutable reviewed native image digest |
| providers | One explicit entry per approved provider, no implicit fallback |

Each provider entry contains `credential_ref`, `provider_id`, `executable`,
`project_ref`, `environment_ref`, `secret_path_ref`, `token_file_ref`. References
must match the pinned stage approvals. Each provider has its own narrowly
mounted directory containing only its `token` file, external to source/audio storage,
mode0400 or0600 and readable by the
runtime UID. Only the fixed child identity module reads them. The reviewed
Infisical executable is mounted read-only; it imports neither parent folders nor
expanded secrets. No provider key is part of this manifest, image, command or log.

Container references are `/run/ac-sales-xray/identities/elevenlabs/token`,
`/run/ac-sales-xray/identities/groq/token` and
`/run/ac-sales-xray/identities/gemini/token`. Each child opens the current file
when it starts; it does not reuse a token cached by the worker. An external
identity provisioner can atomically replace the token inside the corresponding
directory without changing the container mount. The broker deadline is
180seconds; provision at least240seconds of remaining validity at dispatch and
refresh ahead of that margin. The worker does not renew identities or
buy/extend provider allowances.
The DB-only file is `/run/ac-sales-xray/database-url`; rotate it with a worker
restart because the SQLAlchemy pool is created once at startup.

The service does not load dotenv files or inherit API/session/OAuth credentials.
It rejects unapproved ambient environment variables. The database URL is limited
to the existing `ac_runtime` role and `ac_platform` database; it is never printed.
SQL parameter logging is disabled and the pool is capped at two connections.

## Supervision and deployment

`infra/conversation-worker/compose.hosted.yaml` is an explicit opt-in overlay on
the current application compose. It uses the immutable API Python image with a
different command, no HTTP port, readonly root, no capabilities, a bounded temp
filesystem, CPU/RAM/PID limits and a 16-minute graceful shutdown window. The
native helper has a separate service identity and container-runtime boundary.
The database worker receives its private Unix socket, never the Docker socket.
Native source/output paths must use the same host/container absolute mappings.

On SIGTERM/SIGINT the service stops admitting new stages, drains accepted work,
then disposes its DB pool. Failures exit nonzero using a content-free code so
the supervisor can restart it and the existing durable leases reconcile work.
Stopping this service is the rollback action for its activation; preserve
stored sources/checkpoints and audit history. Roll back the release-owned
approval/config/image references together, never edit queue rows manually.

## Evidence boundary

Local test receipts are supplied with the integration handoff. They verify
configuration tamper rejection, credential separation, inert checks, bounded
DB settings, graceful stop and disposal. They are not Linux container, provider,
staging or production receipts. The release task must build the exact native
image, prove its resource/network/file confinement, start the separate helper,
and run authenticated upload/report/deletion/IDOR smoke checks on staging before
promoting the same images to production and repeating the smoke checks.

`scripts/test_hosted_native_linux.py` is the executable native smoke for that
Linux slot. Run it as UID/GID10001 with `--socket`, `--workspace-root`, the exact
`--image-ref`, and a new external `--receipt` path. It sends a generated one-second
16kHz tone through the actual helper/container twice, checks deterministic native
results, rejects a different image, verifies the helper still works, removes its
scratch and writes a content-free receipt. No database or provider credentials
are needed. A successful run exercises the real container confinement preflight;
it does not replace the separate load, termination/reap, deletion or browser tests.
