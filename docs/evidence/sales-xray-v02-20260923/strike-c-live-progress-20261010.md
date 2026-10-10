# Strike C: owner progress follows the selected execution

Task: AUT-1676, owner inbox request of 10 October 15:48 IST. Continuation
baseline: `9aaa1a7b123c806bc9afd6b6112a153800a858cd`. Main
`4d623da` was integrated without conflicts, preserving Strike E's invitation
repair and its AUT-1750 ownership handoff. No invitation implementation was
added here.

The private submission read previously omitted the coordinator's current stage
and every timing field. A consumer could see no live plan movement despite a
completed pipeline. It now exposes additive, content-free execution metadata.
The original task list, state, run state, minute state and retry fields retain
their existing contracts and authorization.

`GET /v1/conversation/acquisition/submissions/{submission_id}` adds:

| Field | Meaning |
| --- | --- |
| `current_stage` | C0–C6 or null. The persisted plan stage wins; validated report availability gives C6. Before a plan, the latest known local stage is used. |
| `plan_state` | The persisted plan state, or null when no current provider plan applies. |
| `terminal_state` | `done`, `failed`, or null for an in-flight/quoted/profile-held run. Uses the existing canonical run-state projection. |
| `stage_progress` | Seven ordered rows, C0–C6. Separate from the original C2/C4/C5 `stages` task list. |
| `stage_progress[].stage` | C0–C6. |
| `stage_progress[].state` | `waiting` without execution evidence; otherwise the persisted task/local-run state or `completed` for a retained checkpoint. |
| `stage_progress[].started_at` | UTC ISO timestamp of the committed dispatch marker, or null when no start was recorded. |
| `stage_progress[].finished_at` | UTC ISO timestamp of terminal run completion/checkpoint publication/validated report persistence, or null when unknown or unfinished. |

Starts are deliberately not synthesized from enqueue time, the poll clock,
neighboring stages or report readiness. C0/C3/C6 do not store dispatch starts;
those fields remain null. Historical/cached local starts can also be unknown.
A chunked C4 finishes only once the selected stage is terminal. An unfinished
chunk does not acquire the preceding chunk's completion time.

The coordinator records the actual selected task IDs in its existing progress
JSON, including reused completed tasks and the selected bounded C5 repair.
Expiry and coordinator failure retain this selection and the current stage,
while partial work still rolls back. The speaker-role freeze behavior remains
unchanged. This requires no schema, billing, provider-authority or acceptance
change. The IDs are internal and are not added to the public response.

The timeline selects those tasks, so a retry does not inherit an old failed
task's dispatch/finish or its downstream C3/C6 checkpoint lineage. Old plans
without this additive selection retain their original source-scoped task
projection. Quoted and local retries do not claim provider-stage execution.
All reads remain under the existing ownership and source/generation fences;
the metadata query additionally binds tenant, person, source revision and hash,
ignores erased/mismatched checkpoints, and fetches no content payloads.

The legacy frontend still accepts this response and its nullable timestamps.
Strike A owns using the additive fields in its page and any client projection.
The current main processing panel independently polls the existing plan port.
No page/layout, report/prospect rendering or coaching code was edited here.

## Verification

- 82 focused progress/acquisition/plan unit checks pass; all 14 speaker-role
  freeze checks pass after adding a real run-ID shape to their fictional task
  fixture.
- Both cookie/HTTP/PostgreSQL capped-retry cases pass. They verify queued C2,
  dispatched terminal 503 evidence, stranger 404, clean successor timing,
  C4/C5/C6 read-back, all seven completion fields, preserved original task
  shape and the existing single delivered charge/race assertions.
- Four PostgreSQL coordinator exception/diagnostic cases pass. Selected stages
  survive a terminal transition while partial enqueue work rolls back.
- 52 focused frontend checks pass (legacy response compatibility, step
  projection and safe retry/status). Frontend typecheck, changed ESLint and
  Prettier pass.
- All six PostgreSQL plan-budget and local-retry/restart cases pass.
- Final targeted three-module mypy and changed-file Ruff lint pass.
- The native retained-C2 reupload fixture failed at upload admission (422: audio
  length could not be verified), before the changed coordinator assertion or
  progress query ran. This is not a passing native proof. The explicitly
  fictional measured fixtures in the two passing HTTP cases exercise the
  changed route without substituting for native validation. Final-head CI
  remains required for the complete native journey. The legacy C4 upgrade
  fixture also failed in its existing local C1 setup, before the changed
  assertion. Its immutable-hold expectations now include the selected IDs;
  these two setup failures are retained as limitations, not passing receipts.

This is fictional local test evidence. No deployed authenticated journey,
staging/production data change, provider replay, deployment or merge is claimed.
The shared-file gate currently conflicts with #429; it is not bypassed.
The companion expired unaccepted-quote patch still applies cleanly to the
integrated page, but its application and journey verification belong to Strike
A. The watchdog alarm implementation and operations handoff are unchanged.

On dev after the authorized watchdog merge, open an owned internal test call
and inspect the private submission response while the worker and coordinator
advance it. Confirm current-stage movement, real timestamps or explicit nulls,
terminal failure/delivery, released/delivered minutes and safe retry. Reload
and reopen to verify the same persisted evidence. Live dev receives main from
the UI lane; this checkout is not the live page.
