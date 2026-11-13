# ruff: noqa: E501 - the page's HTML and CSS template, one statement per line
"""One page per release run: pass or fail per scenario, with links. Pure: run JSON in, HTML out."""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

MARK = {"pass": "Pass", "fail": "Fail", "pending": "Waiting", "n/a": "–"}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _badge(state: str) -> str:
    return f'<span class="b {_e(state.replace("/", ""))}">{_e(MARK.get(state, state))}</span>'


def _expected(expect: Mapping[str, Any]) -> str:
    outcome = {
        "report": "a full report",
        "short_call": "held: short call",
        "no_conversation": "held: no conversation",
        "held": "a short-call or no-conversation hold",
        "any": "a report or a hold",
    }[expect["outcome"]]
    return f"{outcome}; {'sales' if expect['sales'] else 'not sales'}"


def render(run: Mapping[str, Any]) -> str:
    verdict = run.get("verdict") or {}
    rows = run.get("results") or []
    app = run.get("app") or {}
    passed = verdict.get("passed")
    headline = "Every gate passed" if passed else "Gate failed" if passed is False else "Running"
    gate_n = sum(1 for r in rows if r.get("gate") == "pass")
    det_rows = [r for r in rows if r.get("detect") in {"pass", "fail"}]
    det_n = sum(1 for r in det_rows if r["detect"] == "pass")
    not_sales = [r for r in rows if not r["expect"]["sales"]]
    caught = sum(1 for r in not_sales if r.get("detect") == "pass")
    body = []
    for r in rows:
        link = f'<a href="{_e(r["link"])}">Open report</a>' if r.get("link") else ""
        notes = "; ".join(r.get("notes") or [])
        focus = f'<div class="f">Next call: {_e(r["focus"])}</div>' if r.get("focus") else ""
        body.append(
            "<tr>"
            f'<td><b>{_e(r["id"])}</b><div class="t">{_e(r["title"])}</div><div class="p">{_e(r["persona"])}</div></td>'
            f"<td>{_e(_expected(r['expect']))}</td>"
            f'<td>{_e(r.get("outcome"))}<div class="p">{_e(r.get("detected"))}</div>{focus}</td>'
            f"<td>{_badge(r.get('gate', 'pending'))}</td>"
            f"<td>{_badge(r.get('detect', 'pending'))}</td>"
            f"<td>{_e(r.get('report_seconds') if r.get('report_seconds') is not None else '')}</td>"
            f'<td>{link}<div class="p">{_e(notes)}</div></td>'
            "</tr>"
        )
    crash = verdict.get("crashes") or []
    spend = run.get("spend") or {}
    spend_line = (
        f"Rs {spend['rupees']:.2f} measured ({spend.get('note', '')})"
        if spend.get("rupees") is not None
        else f"about Rs {run.get('spend_estimate', 0):.0f} estimated; measured spend follows the usage export"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Release call check</title>
<style>
:root{{--bg:#fff;--fg:#1b1f24;--mute:#5b6470;--line:#e3e6ea;--ok:#0f7b3f;--okb:#e6f4ec;--bad:#b42318;--badb:#fdecea;--wait:#7a5b00;--waitb:#fff6db}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#111418;--fg:#e8eaed;--mute:#9aa3ad;--line:#2a3038;--ok:#5fd08f;--okb:#12301f;--bad:#ff8a80;--badb:#3a1512;--wait:#ffd166;--waitb:#33290d}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:20px 16px 48px}}
h1{{font-size:22px;margin:0 0 4px}} .m{{color:var(--mute);margin:0 0 16px}}
.k{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}} .k div{{border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:150px}}
.k b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;vertical-align:top;padding:10px 8px;border-top:1px solid var(--line)}}
th{{font-size:13px;color:var(--mute);font-weight:600}} .t{{font-weight:600}} .p,.f{{color:var(--mute);font-size:13px}}
.b{{display:inline-block;border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
.pass{{color:var(--ok);background:var(--okb)}} .fail{{color:var(--bad);background:var(--badb)}} .pending,.na{{color:var(--wait);background:var(--waitb)}}
.wrap{{overflow-x:auto}} a{{color:inherit}}
</style></head><body><main>
<h1>{_e(headline)}: release call check {_e(run.get("run_id"))}</h1>
<p class="m">{_e(run.get("environment"))} · Play app {_e(app.get("versionName"))} ({_e(app.get("versionCode"))}) · web {_e((run.get("web") or {}).get("version"))} · phone {_e(run.get("serial"))} · set {_e(run.get("set"))} · started {_e(run.get("started_at"))}</p>
<div class="k">
<div>Pipeline gates<b>{gate_n} of {len(rows)}</b></div>
<div>Sales or not, right<b>{det_n} of {len(det_rows)}</b></div>
<div>Non-sales calls caught<b>{caught} of {len(not_sales)}</b></div>
<div>App crashes<b>{len(crash)}</b>{"" if verdict.get("app_alive", True) else " · app not running"}</div>
<div>Spend<b style="font-size:15px">{_e(spend_line)}</b></div>
</div>
<div class="wrap"><table>
<tr><th>Scenario</th><th>Expected</th><th>What the server did</th><th>Pipeline</th><th>Sales or not</th><th>Seconds to report</th><th>Report</th></tr>
{"".join(body)}
</table></div>
<p class="m">Synthetic voices and fictional people only, on the QA lead {_e(run.get("lead_name"))}. "Pipeline" gates the release: the app uploaded the call and the server finished it as expected, with every report section and a next-call focus. "Sales or not" measures detection: a report with no stored call purpose counts as coaching a sales call.{" " + _e(run.get("note")) if run.get("note") else ""}</p>
</main></body></html>
"""
