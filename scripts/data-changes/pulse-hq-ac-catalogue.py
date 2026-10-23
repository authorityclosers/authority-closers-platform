#!/usr/bin/env python3
"""Turn Pulse HQ on for Authority Closers in AC's own Pulse and load AC's feature catalogue.

Owner order, 23 Oct 2026 (~05:30 IST, relayed by the orchestrator): "reuse this [Pulse HQ,
pulse-dev.estateautopilots.com/hq/features] on pulse of Authority Closers so we have a
features listing there". Owner-approved data change (AGENTS.md, OWNER-APPROVED DATA CHANGES):
dry run by default, before and after printed, one transaction, idempotent, audited with the
approver and the issue; on apply, a pg_dump of AC's Pulse first.

What it changes, in AC's Pulse (container pulse-postgres-1 on ac, database pulse), only in the
organisation with slug ``authority-closers``:

1. Module switch: the organisation's ``tenant/modules`` document gets ``pulse_hq`` in ``on``
   (Pulse HQ is organisation-only, services/api/src/modules.ts ORG_ONLY). Done the way Pulse's
   own migrations change a configuration document: the active version is retired and the next
   version is added, active, with the same ``off`` list. Already on: nothing.
2. Catalogue: one ``pulse.hq_feature`` row per AC feature, keyed by its catalogue id, from
   ``apps/admin-web/app/catalogue/catalogue.generated.json`` (the Admin Feature catalogue,
   built from the code by scripts/catalogue/build_feature_catalogue.py). Upserted: a row whose
   fields already match is left alone, so a second run changes nothing; rows the organisation
   added by hand (other keys) are never touched.

HQ's 13 categories are Pulse's product areas, fixed in Pulse's code (pulse-hq.ts HQ_CATEGORIES,
apps/web/app/hq/model.ts CATEGORIES). AC's 12 categories are mapped to the nearest one
(``CATEGORY_TO_HQ``) and each feature's ``proof`` line keeps its AC category, product, release
and where its code lives, until Pulse has categories per organisation. Status: live -> live,
live behind a switch or on dev -> beta, planned -> idea. No ``href``: an AC feature has no
page inside Pulse.

Audit: ``pulse.actor_account`` names this script, the approver and the issue, so Pulse's own
audit trigger records the module document change; one more ``pulse.audit_event`` records the
catalogue load with its counts.

Another Pulse: --exec (how psql is reached, e.g. "ssh ea sudo docker exec -i <container>"),
--database, --db-user, --org-slug, --founder-email and --backups; the keys and the upsert make
a re-run there, or here, change only what differs.

Run on ac as root (it uses docker):
  python3 scripts/data-changes/pulse-hq-ac-catalogue.py                       # dry run
  python3 scripts/data-changes/pulse-hq-ac-catalogue.py --apply \\
      --approver "Suyash Kulkarni (owner)" --words "approve data change: ..." --issue "..."
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "apps" / "admin-web" / "app" / "catalogue" / "catalogue.generated.json"
EXEC = "docker exec -i pulse-postgres-1"
DATABASE = "pulse"
DB_USER = "pulse_admin"
ORG_SLUG = "authority-closers"
FOUNDER_EMAIL = "admin@authorityclosers.com"
BACKUPS = Path("/srv/authority-closers/pulse/backups")
SCRIPT = "scripts/data-changes/pulse-hq-ac-catalogue.py"
TEMPLATE = Path(__file__).with_suffix(".sql")

# AC category -> the nearest Pulse HQ category (pulse-hq.ts HQ_CATEGORIES).
CATEGORY_TO_HQ = {
    "calling": "xray",
    "leads": "clients",
    "analysis": "xray",
    "coaching": "xray",
    "chats": "chats",
    "ads": "clients",
    "team": "network",
    "admin": "admin",
    "developer": "platform",
    "apps": "apps",
    "academy": "people",
    "platform": "admin",
}
# Icons from Pulse HQ's own list (apps/web/app/hq/model.ts ICONS).
CATEGORY_ICON = {
    "calling": "PhoneCall",
    "leads": "Users",
    "analysis": "ScanSearch",
    "coaching": "Target",
    "chats": "MessagesSquare",
    "ads": "Megaphone",
    "team": "Building2",
    "admin": "Gauge",
    "developer": "Webhook",
    "apps": "Smartphone",
    "academy": "GraduationCap",
    "platform": "ShieldCheck",
}
FEATURE_ICON = {
    "the-report": "FileText",
    "brain-4": "Sparkles",
    "whatsapp": "MessageCircle",
    "ai-replies": "Bot",
    "cost-meter": "ChartColumn",
    "ai-spend-guard": "PiggyBank",
    "api-keys": "KeyRound",
    "connect-mcp": "PlugZap",
    "chrome-extension": "Chrome",
    "audit-trail": "ScrollText",
    "backups": "HardDrive",
    "certificates": "Award",
    "plans": "ReceiptText",
}
HQ_CATEGORIES = {
    "home", "work", "flows", "chats", "people", "finance", "clients",
    "creative", "xray", "network", "apps", "admin", "platform",
}  # fmt: skip


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def hq_status(feature: dict[str, Any]) -> str:
    if feature["status"] == "planned":
        return "idea"
    if feature["status"] == "dev" or feature.get("switch"):
        return "beta"
    return "live"


def proof_line(
    feature: dict[str, Any], categories: dict[str, str], products: dict[str, str]
) -> str:
    since = feature.get("since") or {}
    when = {
        "live": f"{'in releases by' if since.get('or_earlier') else 'live since'} "
        f"{since.get('version', '?')}",
        "dev": "on dev, not released yet",
        "planned": "planned",
    }[feature["status"]]
    parts = [
        f"AC: {categories.get(feature['category'], feature['category'])}",
        products.get(feature["product"], feature["product"]),
        when,
    ]
    paths = [a["path"] for a in feature.get("anchors", []) if a.get("exists")]
    if paths:
        parts.append(f"code: {paths[0]}")
    # Never a leading "/": Pulse turns the first "/path" in a proof line into a link inside Pulse.
    return _cut(" · ".join(parts), 300)


def rows(catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    """hq_feature rows for every feature, in the catalogue's order within each HQ category."""
    categories = {c["id"]: c["name"] for c in catalogue["categories"]}
    products = {p["id"]: p["name"] for p in catalogue["products"]}
    sort: dict[str, int] = {}
    out = []
    for feature in catalogue["features"]:
        category = CATEGORY_TO_HQ[feature["category"]]
        assert category in HQ_CATEGORIES, category
        what = "; ".join(d.rstrip(".") for d in feature.get("details", []))
        what = f"{what}." if what else ""
        if feature.get("switch"):
            switch = feature["switch"].rstrip(".")
            note = switch if switch.lower().startswith("off") else f"Switched off: {switch}"
            what = f"{what} {note}.".strip()
        out.append(
            {
                "key": feature["id"],
                "category": category,
                "name": _cut(feature["name"], 80),
                "promise": _cut(feature["value"], 200),
                "what": _cut(what, 600),
                "who": _cut(", ".join(feature.get("for", [])), 120),
                "status": hq_status(feature),
                "icon": FEATURE_ICON.get(feature["id"], CATEGORY_ICON[feature["category"]]),
                "proof": proof_line(feature, categories, products),
                "sort": sort.setdefault(category, 0),
            }
        )
        sort[category] += 1
    return out


@dataclass(frozen=True)
class Target:
    """Which Pulse database and organisation: AC's own by default, any other by flag."""

    runner: tuple[str, ...] = tuple(shlex.split(EXEC))
    database: str = DATABASE
    user: str = DB_USER
    org_slug: str = ORG_SLUG
    founder_email: str = FOUNDER_EMAIL
    backups: Path = BACKUPS


def sql(
    features: list[dict[str, Any]], *, actor: str, apply: bool, target: Target | None = None
) -> str:
    """The whole change as one psql script: before, the change, after, then commit or rollback."""
    target = target or Target()
    data = json.dumps(features, ensure_ascii=False)
    assert "$ac_catalogue$" not in data and "$ac_actor$" not in actor
    for value in (target.org_slug, target.founder_email):
        assert "'" not in value and "__" not in value, value
    tokens = {
        "__ORG_SLUG__": target.org_slug,
        "__FOUNDER_EMAIL__": target.founder_email.lower(),
        "__ACTOR__": actor,
        "__COUNT__": str(len(features)),
        "__END_NOTE__": "== APPLIED (committed)"
        if apply
        else "== DRY RUN: rolled back, nothing changed",
        "__END__": "commit;" if apply else "rollback;",
        "__DATA__": data,  # last: the catalogue's own words are never scanned for tokens
    }
    script = TEMPLATE.read_text(encoding="utf-8")
    for token, value in tokens.items():
        script = script.replace(token, value)
    return script


def psql(script: str, target: Target) -> int:
    process = subprocess.run(  # noqa: S603 - argv from the operator's flags; SQL on stdin
        [*target.runner, "psql", "-U", target.user, "-d", target.database],
        input=script,
        text=True,
        check=False,
    )
    return process.returncode


def snapshot(target: Target) -> Path:
    """A custom-format pg_dump of the target Pulse (AC's: next to the auto-update's backups)."""
    path = target.backups / f"pulse-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-before-pulse-hq.dump"
    with path.open("wb") as out:
        dump = subprocess.run(  # noqa: S603 - argv from the operator's flags
            [*target.runner, "pg_dump", "-U", target.user, "-d", target.database, "-Fc"],
            stdout=out,
            check=False,
        )
    if dump.returncode != 0 or path.stat().st_size < 100_000:
        raise SystemExit(f"Snapshot failed ({dump.returncode}); nothing was changed: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run)")
    parser.add_argument("--approver", default="", help="who approved, e.g. Suyash Kulkarni (owner)")
    parser.add_argument("--words", default="", help="the approval, verbatim")
    parser.add_argument("--issue", default="", help="the issue or card this change belongs to")
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE)
    parser.add_argument("--print-sql", action="store_true", help="print the SQL and stop")
    # Another Pulse (e.g. AC as an organisation in EA's production Pulse): where psql runs and
    # which organisation; the defaults are AC's own Pulse on ac.
    parser.add_argument("--exec", default=EXEC, help=f"how to reach psql (default: {EXEC})")
    parser.add_argument("--database", default=DATABASE)
    parser.add_argument("--db-user", default=DB_USER)
    parser.add_argument("--org-slug", default=ORG_SLUG)
    parser.add_argument("--founder-email", default=FOUNDER_EMAIL, help="who the rows are by")
    parser.add_argument("--backups", type=Path, default=BACKUPS, help="where the snapshot goes")
    args = parser.parse_args(argv)
    target = Target(
        runner=tuple(shlex.split(args.exec)),
        database=args.database,
        user=args.db_user,
        org_slug=args.org_slug,
        founder_email=args.founder_email,
        backups=args.backups,
    )

    if args.apply and not (args.approver.strip() and args.words.strip() and args.issue.strip()):
        parser.error("--apply needs --approver, --words (verbatim) and --issue")
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    features = rows(catalogue)
    actor = _cut(
        f"Data change {SCRIPT} · approver: {args.approver or 'dry run'} · "
        f"issue: {args.issue or 'none'} · words: {args.words or 'none'}",
        500,
    )
    script = sql(features, actor=actor, apply=args.apply, target=target)
    if args.print_sql:
        print(script)
        return 0
    if not target.runner or not shutil.which(target.runner[0]):
        raise SystemExit(f"Can't run {target.runner[:1]}: on ac, run this as root (docker).")
    print(f"{len(features)} AC features from {args.catalogue} -> {target.org_slug}")
    if args.apply:
        print(f"Snapshot: {snapshot(target)}")
    return psql(script, target)


if __name__ == "__main__":
    sys.exit(main())
