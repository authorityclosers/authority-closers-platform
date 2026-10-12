"""Build the review fixture's AC Sandbox states from real synthetic-v1 bundles
through the production adapter (no database, no provider).

uv run python scripts/coaching_sandbox_fixture.py [import_ready dir] \
  > apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ac_platform.coaching import placeholder
from ac_platform.coaching.sandbox import call_view, index_call, rep_uuid, rep_view, team_view
from ac_platform.conversation_intelligence.checkpoints import content_hash

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/acdev/datasets/synthetic-v1/import_ready")
TENANT = UUID("00000000-0000-4000-8000-00000000aa01")
VIEWER = UUID("00000000-0000-4000-8000-00000000aa02")
SESSION = UUID("00000000-0000-4000-8000-00000000aa03")

started = time.perf_counter()
payloads, calls = {}, []
for folder in sorted(ROOT.glob("syn-*")):
    parts = {
        name: json.loads((folder / f"{name}.json").read_text())
        for name in ("metadata", "transcript", "coaching")
    }
    sha = content_hash(parts)
    call = index_call(
        key=folder.name,
        occurred_at=datetime.fromisoformat(parts["metadata"]["at"]),
        payload_sha256=sha,
        metadata=parts["metadata"],
        participants=parts["transcript"]["participants"],
        focus=parts["coaching"]["current_focus"],
        tenant_id=TENANT,
    )
    if call:
        calls.append(call)
        payloads[call.key] = parts
calls.sort(key=lambda c: (c.occurred_at, c.key), reverse=True)
calls = tuple(calls)
print("indexed", len(calls), "in", round(time.perf_counter() - started, 2), "s", file=sys.stderr)
team = team_view(calls, person_id=VIEWER, tenant_id=TENANT)


def score(rep_key):
    mine = [c for c in calls if c.rep_key == rep_key]
    newest = payloads[mine[0].key]["coaching"]
    ids = (newest["diagnosis"].get("pattern_counts") or {}).get("call_ids") or []
    return (newest["progress"]["mastery_state"] != "Not Enough Evidence", len(ids), len(mine))


best = max({c.rep_key for c in calls}, key=score)
mine = tuple(c for c in calls if c.rep_key == best)
latest = payloads[mine[0].key]
earlier = {
    k: payloads[k]
    for k in (latest["coaching"]["diagnosis"].get("pattern_counts") or {}).get("call_ids", [])
    if k in payloads
}
rep = rep_view(mine, latest, earlier, person_id=rep_uuid(TENANT, best), tenant_id=TENANT)
clips = (
    placeholder.clips_for(rep.focus.skill_id, gap_type=rep.root_cause.gap_type) if rep.focus else ()
)
rep = rep.model_copy(update={"media_clips": clips, "session_id": SESSION})
one = call_view(mine[0], latest, person_id=VIEWER, tenant_id=TENANT)
one = one.model_copy(
    update={
        "media_clips": placeholder.clips_for(one.focus.skill_id, gap_type=one.root_cause.gap_type)
        if one.focus
        else (),
        "session_id": SESSION,
    }
)
out = {
    "team": json.loads(
        team.model_copy(update={"session_id": SESSION}).model_dump_json(by_alias=True)
    ),
    "rep": json.loads(rep.model_dump_json(by_alias=True)),
    "call": json.loads(one.model_dump_json(by_alias=True)),
}
print(
    "rep",
    best,
    rep.person_name,
    rep.mastery.state,
    len(rep.evidence),
    "moments",
    len(mine),
    "calls",
    file=sys.stderr,
)
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
