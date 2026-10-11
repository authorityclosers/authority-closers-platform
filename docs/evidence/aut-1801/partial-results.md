# AUT-1801: retained partial results on progress

`GET /submissions/{id}` now adds `partial_results` to the existing progress
response. Existing fields and canonical run/minute/report states retain their
meaning. Before C2 completes, the partial state is `waiting`.

After the selected C2 checkpoint validates, the response contains a transcript
preview (first 24 segments, total segment count, revision, timebase and duration).
After each selected C4 checkpoint validates, it contains up to 12 source-cited
observations in `key_moments` and the completed/total fact-chunk counts. These are
provisional extraction results, not Coaching, official scoring or a delivered
report. Final report availability still comes from the canonical report path.

Selection binds the current plan, tenant, person, recording, generation and exact
stage run IDs. Fact requests must name that selected transcript checkpoint;
packets must match its source/revision/timebase. Manifest and payload digests are
verified before projecting any content. Quoted plans and local retries suppress
previous downstream output. Missing/corrupt retained output returns an
`unavailable` partial corner state while ordinary progress remains readable.

The existing owner/organisation read boundary runs first. Existing sensitive
segment withholding runs over the preview and moment evidence before it leaves
the application. Provider raw responses are never read for previews. The caps
keep repeated progress reads bounded on long calls.

Strike A can show transcript and moments from this additive response as their
validated checkpoints arrive, and keep the existing C0–C6 state display. This is
checkpoint-driven progress, not unvalidated provider token streaming.
The existing `GET /submissions/{id}/transcript` route provides the full retained
transcript after C2 when the preview's total count exceeds its 24-segment cap.
