# ruff: noqa: E501 - the day page's HTML and CSS template, one rule per line
"""Play the test world one day at a time (docs/qa/test-world/WORLD.md).

    python scripts/call_testing/day.py plan [--day 2026-11-16] [--save]

``plan`` works out the day's leads and calls for the three TEST companies from the saved state
and writes the day's page (``~/ac-call-testing/world/<day>.html``). ``--save`` keeps the state
(story steps, next due days) so the next day follows on. Executing the calls in the TEST
workspaces comes once those workspaces exist (an owner-approved data change).
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str) -> Any:
    key = f"call_testing_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


world = _load("world")


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render(day: date, calls: list[Any], arrived: list[Any], leads: list[Any]) -> str:
    names = {a.key: a.name for a in world.AGENCIES}
    people = {(a.key, s.key): s.name for a in world.AGENCIES for s in a.sellers}
    lead_names = {lead.key: lead.name for lead in leads}
    totals = world.summary(calls)
    tiles = "".join(
        f"<div><b>{_e(names[key])}</b>{row['calls']} calls · {row['connected']} connected · "
        f"{row['not_sales']} not sales · {row['analysed']} analysed · {row['talk_seconds'] // 60} min talk · "
        f"{sum(1 for lead in arrived if lead.agency == key)} new leads</div>"
        for key, row in sorted(totals.items())
    )
    rows = "".join(
        "<tr>"
        f"<td>{_e(names[c.agency])}</td><td>{_e(c.start[11:16])}</td><td>{_e(people[(c.agency, c.seller)])}</td>"
        f"<td>{_e(lead_names.get(c.lead, '–'))}</td><td>{_e(c.kind.replace('_', ' '))}</td>"
        f"<td>{_e(c.seconds if c.connected else 'no answer')}</td><td>{'sales' if c.sales else _e(c.purpose)}</td>"
        f"<td>{'analysed' if c.analyse else ''}</td>"
        "</tr>"
        for c in calls
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test world day</title>
<style>
:root{{--bg:#fff;--fg:#1b1f24;--mute:#5b6470;--line:#e3e6ea}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#111418;--fg:#e8eaed;--mute:#9aa3ad;--line:#2a3038}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:20px 16px 48px}} h1{{font-size:22px;margin:0 0 4px}}
.m{{color:var(--mute)}} .k{{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}}
.k div{{border:1px solid var(--line);border-radius:10px;padding:10px 14px;flex:1 1 260px}} .k b{{display:block}}
.wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:8px;border-top:1px solid var(--line);font-size:14px}} th{{color:var(--mute)}}
</style></head><body><main>
<h1>Test world: {_e(day.strftime("%A %d %B %Y"))}</h1>
<p class="m">Planned day (world version {_e(world.WORLD_VERSION)}). Fictional companies, people and numbers only.</p>
<div class="k">{tiles}</div>
<div class="wrap"><table><tr><th>Company</th><th>Time</th><th>Seller</th><th>Lead</th><th>Call</th><th>Seconds</th><th>Kind</th><th></th></tr>{rows}</table></div>
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--day", default=datetime.now(world.IST).date().isoformat())
    plan.add_argument("--home", default=str(Path.home() / "ac-call-testing" / "world"))
    plan.add_argument("--analyse", type=int, default=3, help="calls analysed per company per day")
    plan.add_argument(
        "--save", action="store_true", help="keep the advanced state for the next day"
    )
    args = parser.parse_args(argv)
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    state_file = home / "state.json"
    state = (
        json.loads(state_file.read_text("utf-8"))
        if state_file.exists()
        else {"leads": [], "days": []}
    )
    day = date.fromisoformat(args.day)
    if day.isoformat() in state["days"]:
        raise SystemExit(f"{day} was already played; the state moves forward one day at a time")
    leads = world.load(state["leads"])
    calls, arrived = world.plan_day(leads, day, analyse_per_agency=args.analyse)
    (home / f"{day}.html").write_text(render(day, calls, arrived, leads), "utf-8")
    (home / f"{day}.json").write_text(
        json.dumps(
            {"day": day.isoformat(), "calls": [vars(c) for c in calls]},
            ensure_ascii=False,
            indent=1,
        ),
        "utf-8",
    )
    if args.save:
        state_file.write_text(
            json.dumps(
                {"leads": world.dump(leads), "days": [*state["days"], day.isoformat()]},
                ensure_ascii=False,
            ),
            "utf-8",
        )
    for key, row in sorted(world.summary(calls).items()):
        print(key, row)
    print("page", home / f"{day}.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
