# Fresh fictional staging canary — 26 September 2026

## Scope and deployed source

Owner explicitly approved accepting the current Terms and running the selected 67-second fictional test once. The test used staging web `fb4b6f1fdbd82a237e935a5062d3b6652a3b9b66`, core `94b47e41d625634c3743b9ca49a94ab29cf3fbeb`, schema `20260924_0048`. Production was not changed by this test.

Fixture SHA-256: `61126c06f8fdb10853ce8eed99e1e852595f4dc3c8e76c9f4475c15b71d92218`. Synthetic source only; no private customer audio exported in this evidence.

## Browser acceptance

- Selected English, accepted Terms, and clicked Analyse once.
- Recording saved, analysis progressed, report opened automatically. No Review plan, Continue analysis, fresh plan, or retry click.
- Report preserved the corrected affordable budget and identified security approval as the blocker. It recorded no purchase or agreed follow-up date.
- A source clip played with a valid audio resource. Pause/end state was observed at the clip boundary; this is not proof of a mid-clip pause action.
- Calls showed the new entry as Report ready; reopening that entry loaded the same report.
- Found a separate stale root upload banner on Calls: it continued to say Analysis started after the report had completed. Assigned a bounded repair; not resolved by the test itself.

## Canonical server evidence

A SELECT-only probe pinned the exact staging API container and schema. Source hash, plan manifest, task intents, provider receipts and checkpoint bindings were verified. No database writes or new provider requests were made by the probe.

- Upload saved: `2026-09-26T05:31:59.197785Z`.
- One accepted plan, state `completed`.
- C2: existing ElevenLabs `scribe_v2` result reused, zero job attempts and no new dispatch timestamp.
- C4: Gemini `gemini-3.8-flash`, `facts-v2`, one attempt, succeeded.
- C5: Gemini `gemini-3.8-flash`, `coaching-v5`, one attempt, succeeded; no repair.
- Completion settlement: `2026-09-26T05:32:39.688851Z`, 67 allowance seconds.
- Approximately 40.5 seconds from saved upload to settlement. This is not a cold-transcription latency benchmark or a provider billing amount.
- Verified checkpoints cover C0 through C6 (two C4 records).

Sanitized private receipt SHA-256: `7b07dbbd2542c205bfbf2cd8bcec37de88511a9be90004210e813eda1513c9b4`.
Probe SHA-256: `3c674ad38497c468f2d151adbb501a6cf6bc751c34aeb2183513c60eae988712`.

## Limits

This is one fictional English acceptance test using a reused transcript. It does not establish OpenAI performance, fresh speech-engine performance, multilingual or long-call quality, production acceptance, or completion of the full v0.2 scope. Some report language remains overly technical. The five historical paused calls are separate unresolved work.
