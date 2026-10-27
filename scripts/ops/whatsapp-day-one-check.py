#!/usr/bin/env python3
"""First-day check for an organisation's own WhatsApp number: do Meta's webhooks arrive?

The risk (decision memo, 27 Oct 2026): AC's Messaging app is in Development mode, and
Meta says "some webhooks will not be sent if your app is in Dev mode". Sending works
with AC's own system-user token whatever the mode; what may not come is what Meta
pushes to us. So, after connecting the number
(scripts/data-changes/lead-desk-whatsapp-own-number.py):

1. From Sales X-Ray, send an approved template to a team phone (a lead with that number).
2. On that phone, reply "Hi".
3. Run this. It reads only, and says for each kind of webhook whether it arrived since
   the start time:
   - **messages**: the "Hi" became an inbound message (and a lead, or joined one);
   - **statuses**: our template went on to delivered or read (ticks);
   - **templates**: a template review came in (only if one was submitted since).

PASS on messages and statuses means two-way WhatsApp works for AC's own number in the
app's present mode. FAIL on either means the dev-mode risk is real. Then, in order:
(a) a separate small Meta app that holds only AC's own assets, published Live (no
review needed for own assets), or (b) a WhatsApp partner for AC's own number. Both are
in docs/product/lead-desk/whatsapp-own-number.md.

    set -a; . /etc/authority-closers/<environment>/api-live.env; set +a
    <venv python> scripts/ops/whatsapp-day-one-check.py --org <tenant id> --since <ISO time>

Production reads go through the logged path instead: ``--sql`` prints the read-only
query for ``~/costq/q.sh production <file>``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

SQL = """-- WhatsApp first-day check (read only): {org} since {since}
SELECT 'number' AS kind, n.display_number AS detail, n.status AS status, n.updated_at AS at
  FROM lead_desk_whatsapp_numbers n WHERE n.tenant_id = '{org}'
UNION ALL
SELECT 'message_' || m.direction, m.kind, m.status, coalesce(m.status_at, m.created_at)
  FROM lead_desk_whatsapp_messages m
 WHERE m.tenant_id = '{org}' AND m.created_at >= '{since}'
UNION ALL
SELECT 'template', t.name, t.status, t.updated_at
  FROM lead_desk_whatsapp_templates t
 WHERE t.tenant_id = '{org}' AND t.updated_at >= '{since}'
ORDER BY at;
"""


def verdict(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """PASS or FAIL per webhook kind, from the rows the query above returns."""
    rows = list(rows)
    numbers = [row for row in rows if row["kind"] == "number" and row["status"] == "active"]
    inbound = [row for row in rows if row["kind"] == "message_in"]
    ticked = [
        row
        for row in rows
        if row["kind"] == "message_out" and row["status"] in {"delivered", "read"}
    ]
    sent = [row for row in rows if row["kind"] == "message_out"]
    templates = [row for row in rows if row["kind"] == "template"]
    result = {
        "number": "PASS" if numbers else "FAIL: no active WhatsApp number in this organisation",
        "messages": "PASS"
        if inbound
        else "FAIL: no inbound message arrived (send one from a team phone, then run again)",
        "statuses": "PASS"
        if ticked
        else (
            "FAIL: our message never went past sent (no status webhook)"
            if sent
            else "WAIT: send a template from Sales X-Ray first"
        ),
        "templates": "PASS" if templates else "SKIP: no template review since then",
    }
    real = ("number", "messages", "statuses")
    result["overall"] = (
        "PASS: two-way WhatsApp works in the app's present mode"
        if all(result[key] == "PASS" for key in real)
        else "FAIL: see docs/product/lead-desk/whatsapp-own-number.md, 'If webhooks don't arrive'"
        if any(result[key].startswith("FAIL") for key in real)
        else "WAIT"
    )
    return result


async def read(org: UUID, since: datetime) -> list[dict[str, Any]]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from ac_platform.application.settings import Settings

    settings = Settings()
    if settings.environment == "production":
        raise SystemExit("Production: use --sql and the logged read path (~/costq/q.sh).")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text(SQL.format(org=org, since=since.isoformat())))
            return [dict(row._mapping) for row in rows]
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--org", type=UUID, required=True)
    parser.add_argument(
        "--since",
        type=datetime.fromisoformat,
        default=datetime.now(UTC) - timedelta(hours=2),
        help="ISO time the test began (default: two hours ago)",
    )
    parser.add_argument("--sql", action="store_true", help="print the read-only query only")
    args = parser.parse_args()
    since = args.since if args.since.tzinfo else args.since.replace(tzinfo=UTC)
    if args.sql:
        print(SQL.format(org=args.org, since=since.isoformat()))
        return
    rows = asyncio.run(read(args.org, since))
    print(json.dumps({"rows": len(rows), **verdict(rows)}, indent=2, default=str))


if __name__ == "__main__":
    main()
