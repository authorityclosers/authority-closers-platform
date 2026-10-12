# AUT-1801: reconcile one uncertain C2 outcome

For Claude, the named hosted operator. Builder sessions remain read-only on
staging/production. The 11 October dev-first freeze prohibits staging/production
apply or retry until the owner lifts it. This tool does not itself check the
provider or retry the call: it records a privately verified exact outcome, then
the ordinary owner retry API performs fresh admission.

## Evidence before action

For submission `39512b2d-56e1-52c9-9c14-7f843ca3b37e` and recording
`55448228-bdb4-449d-acd8-b39d101a4379`, read back the exact terminal task/job/run,
source generation, dispatch time, provider attempt key and frozen quote/input.
Use ElevenLabs request history or support to correlate the original send with a
provider request ID and confirmation. The old transport did not transmit AC's
internal attempt key to ElevenLabs: that key alone is insufficient lookup proof.
Do not interpret a missing transcript, timeout, capacity hypothesis or absent
audit event as a confirmed unaccepted request.

Only a provider-confirmed `not_accepted` outcome qualifies. Completed results
need retained-result recovery; unknown results stay held. The actual provider
confirmation stays in approved private storage. The reviewed metadata file uses
the exact `C2OutcomeEvidence` schema in `provider_reconciliation.py`: original
attempt bindings, SHA-256s of the provider request ID and confirmation, method
(`provider_request_history` or `provider_support`), verification time, owner and
operator person IDs, environment and recorded approval reference. No credentials,
raw provider responses, audio or transcript contents belong in it.

## Dry-run, approval and apply

1. Pin the reviewed tool source and metadata file SHA-256. Obtain the owner's
   exact data-change approval naming the call and environment. One named
   operator runs it outside a release.
2. Through the existing injected application runtime, run
   `uv run python scripts/data-changes/reconcile-c2-provider-outcome.py --evidence <private-json> --evidence-sha256 <sha256>`.
   The default dry-run prints metadata-only before/after and appends nothing.
3. Production additionally requires a database snapshot and owner inspection of
   this dry-run. Apply with the same file/hash and `--apply`; production also
   requires `--production-snapshot-sha256 <sha256>`.
4. The one transaction locks/rechecks exact custody, recovery generation,
   terminal ownership and released customer minutes. It appends a distinct
   `conversation.provider_outcome_reconciled` event. It preserves the original
   job, dispatch fence, receipt absence, provider budget and minute journals.
   Identical replay reuses that event; conflicting evidence is refused.
5. Verify the audit event and unchanged terminal state through the app/operator
   read path. Then, when the freeze permits, the authenticated original owner
   calls `POST /submissions/{id}/retry`, approves the returned fresh plan and
   checks Report plus per-call Coaching. The existing source attempt limit,
   provider-route approval, consent, retention and budget gates still apply.
6. Post before/after, data-change run ID, event ID, evidence digest, tool SHA and
   approving person on AUT-1801. Keep all contents and credentials private.

No original HTTP observation is manufactured. No provider call is dispatched by
this script, and no provider no-charge claim is made. Customer minutes must
already be released; report delivery remains the only capture path. Ordinary
app retry supports this audited evidence immediately, so no hand-made state is
required for future calls.
