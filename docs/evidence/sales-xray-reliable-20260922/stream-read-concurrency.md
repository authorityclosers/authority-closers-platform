# Account reads during retained audio playback

Parent staging checkpoint: `fbe5b4eaa909f060f91671b7169068d52b76591c`.
The completed hour-long report remains the provider acceptance fixture. This
follow-up makes no provider, prompt, budget, retention or retry-policy changes.

## Failure mechanism and bounded repair

The authenticated acquisition source response retains its request transaction
until streaming and cleanup end. The previous identity dependency acquired
exclusive Person and Session locks and updated session activity. A slow or
paused response could therefore block account reads in another browser tab.
This is a confirmed source-level concurrency hazard; it is not proof that every
earlier browser timeout had this cause.

An explicit read-only identity resolver acquires shared Person, Session, Tenant
and Membership locks in canonical order, revalidates current identity under
those locks, and does not update session revision or `last_seen_at`. The normal
resolver and mutation paths retain their existing exclusive behavior. Read
ownership checks opt into shared identity locks; source, recording, permission
and visitor fences remain held through the audio response and cleanup.

The enabled acquisition UI starts with `/v1/me/workspaces`, then acquisition
entry/session/policy reads. Its saved library, progress, report, transcript,
waveform and source use acquisition routes. Workspace discovery must participate
in the shared-read path or a full reload can still block before reaching the
acquisition session route. The legacy CallStudio fallback is selected only when
acquisition entry is disabled; this change does not claim that every legacy
conversation GET supports concurrent playback.

## Local verification

- Root identity unit suite: 47 passed.
- Root conversation-intelligence and HTTP unit suites: 2,086 passed, one POSIX
  ownership skip, and two temporary-path failures. The two failures hit the
  native socket's existing 107-byte path bound on Windows. Re-running their
  three-test file with a short private temporary root passed all three.
- Final whole-source/test Ruff lint and formatting passed for 688 files;
  Python type checking passed for all 302 source files.
- Final root workspace and learner-acquisition HTTP unit run: 17 passed. It
  includes revoked/expired session denial, zero workspace-read writes, shared
  mode on account GET and default mode on the existing mutation path.
- Final root PostgreSQL run: both new regressions passed in 23.98 seconds.
  With an authenticated HTTP 206 source response held open, session, workspace,
  progress and library GETs complete without changing session activity. An
  authenticated delete reaches its exclusive identity lock attempt and remains
  blocked until the stream releases; deletion then completes and the worker
  removes retained storage. A separate ASGI send barrier uses the real storage
  iterator to prove client cancellation releases the response fence and allows
  deletion to complete. A wrong visitor cannot read the call.
- A controlled baseline substituted the unchanged exclusive identity resolver
  for the read-only resolver in an isolated test process. The held-stream test
  failed at its two-second session-read timeout inside
  `resolve_actor -> _lock_person -> get_person_for_update`. The fixed test
  passes. No checkout files were changed for the baseline substitution.
- Independent route tracing verified the enabled acquisition boot and saved
  library paths. Learner-host entry and upload-policy reads now also opt into
  the read-only resolver; acquisition availability has no identity dependency.

All tests use synthetic local data and make no paid provider calls. Frozen-source
CI and deployed browser acceptance remain pending at this checkpoint. Production
remains unchanged. The legacy fallback is not covered by this concurrency claim,
and intentional account mutations still serialize against active audio streams.
