# ADR 0047: First-report call measurements

Date: 2026-10-03
Status: Accepted design; implementation in AUT-428

Store one `conversation_call_metrics` row when an acquisition usage receives its
first completed report. Its primary key references the usage settlement. The
recording lock and existing first-settlement branch prevent reruns from replacing
the original measurements or adding another row. No backfill or HTTP surface is
part of this change.

`call_metrics.stored_summary` produces deterministic `call-metrics/2` timings,
counts, ratios, speaker IDs and segment IDs. It stores no transcript words,
quotes, custom labels, provider explanations or score. The optional outcome kind
is copied from the validated report overview; outcome text and evidence are not
copied. The summary hash uses the checkpoint canonical JSON encoding.

Measurements stay keyed by source speaker IDs. Reader-side role mapping follows
the current confirmed speaker map, so changing the salesperson's role does not
rewrite first-report measurements. No salesperson role is inferred by this store.

The insert shares the report and completed-settlement transaction, inside a
savepoint. A computation or insert exception rolls back only the measurements.
The report still completes; `call_metrics_skipped` logs only the exception class,
without its message or traceback. A failed first insert is not retried by a later
report, because that would change which report supplies the measurements.

Retention follows each recording's approved retention. Build option B applies:
both expiry and explicit deletion clear `summary` and `outcome_kind` through
`finish_erasure`, setting `erased_at`. IDs, rules, timestamps and the summary hash
remain as content-free provenance. Numbers receive no independent or indefinite
retention. The retention-v2 alignment supersedes the earlier option A proposal.
Tests use fictional seven-day legacy and 730-day future-policy recordings; these
fixtures do not issue a new policy, change consent, or change existing promises.

Migration `20261003_0071` follows speaker-map revision `20261003_0070` and is
forward-only. It replaces the original card's 0055 number, which was no longer
the next available ID. Model registration, the `ac-postgres-parity-v43`
backup/restore catalogues and release-head checks accompany it.

The fictional retention checks use the real scheduler for expiry and the owned
deletion command for explicit erasure, then the recovery-fenced internal lease
and `finish_erasure`. They keep metrics until adapter confirmation and verify
SQL NULL content afterwards while preserving settlement and provenance. The
730-day fixture represents a future approved policy without activating one.
