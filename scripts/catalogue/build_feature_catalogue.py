"""Build AC Admin's Feature catalogue from the code.

The product words live in scripts/catalogue/feature_seed.json. This script adds what the
code says: whether each feature's anchors exist in the working tree, the first release on
main that carried all of them, every page each web app serves (and which ones no feature
names yet), the API routes, the settings registry's areas, the env switches and the release
notes. It writes apps/admin-web/app/catalogue/catalogue.generated.json, which the Admin
page imports.

Anchors:
  sx:/leads, admin:/calls, learner:/practice, coach:/studio  a page of that web app
  packages/python/ac_platform/lead_desk                       a file or directory
  path#needle                                                 that file contains `needle`

Usage:
  python scripts/catalogue/build_feature_catalogue.py            # write the catalogue
  python scripts/catalogue/build_feature_catalogue.py --no-git   # skip release history
  python scripts/catalogue/build_feature_catalogue.py --strict   # fail on missing anchors
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "scripts" / "catalogue" / "feature_seed.json"
OUTPUT = ROOT / "apps" / "admin-web" / "app" / "catalogue" / "catalogue.generated.json"
SHOTS = ROOT / "apps" / "admin-web" / "public" / "catalogue" / "shots"

APPS = {
    "sx": ("sales-xray-web", "Sales X-Ray", "https://salesxray-dev.authorityclosers.com"),
    "admin": ("admin-web", "AC Admin", "https://admin-dev.authorityclosers.com"),
    "learner": ("learner-web", "AC Academy", None),
    "coach": ("coach-web", "Coach Studio", None),
}
# Pages that exist only to review or test screens; never product features.
INTERNAL_PAGE = re.compile(r"^/(review-fixture|dev-harness)(/|$)")
RELEASE_SUBJECT = re.compile(r"^Release (v\d+(?:\.\d+){1,2})\b\s*(.*)$")
API_ROUTE = re.compile(
    r"APIRouter\([^)]*?prefix=\"(?P<prefix>/v1[^\"]*)\""
    r"|\.(?P<method>get|post|put|patch|delete)\(\s*\"(?P<path>(?:/[^\"]*)?)\""
)
# A release this many days after the one before it starts the tracked history; anything
# already in it may be older ("by v0.40.0").
HISTORY_GAP_DAYS = 14
ENV_SWITCH = re.compile(r"\b(AC_[A-Z0-9_]+_ENABLED)\b")
SETTINGS_AREA = re.compile(r"area=\"([a-z0-9-]+)\"")
STATUSES = ("live", "dev", "planned")


@dataclass(frozen=True)
class Release:
    sha: str
    version: str
    date: str
    title: str


def page_routes(app_dir: str) -> dict[str, str]:
    """Route -> page file (repo-relative) for one Next app; route groups are dropped."""
    base = ROOT / "apps" / app_dir / "app"
    routes: dict[str, str] = {}
    if not base.is_dir():
        return routes
    for page in sorted(base.rglob("page.tsx")):
        if "node_modules" in page.parts:
            continue
        parts = [
            p
            for p in page.relative_to(base).parent.parts
            if not (p.startswith("(") and p.endswith(")"))
        ]
        route = "/" + "/".join(parts)
        routes.setdefault(route, page.relative_to(ROOT).as_posix())
    return routes


def resolve_anchor(anchor: str, routes: dict[str, dict[str, str]]) -> tuple[str, str | None]:
    """An anchor's repo path and optional needle; a page anchor becomes its page file."""
    needle = None
    if "#" in anchor:
        anchor, needle = anchor.split("#", 1)
    prefix, sep, rest = anchor.partition(":")
    if sep and prefix in APPS and rest.startswith("/"):
        path = routes[prefix].get(rest)
        if path is None:
            return f"apps/{APPS[prefix][0]}/app{rest}/page.tsx", needle
        return path, needle
    return anchor, needle


def present_now(path: str, needle: str | None) -> bool:
    target = ROOT / path
    if not target.exists():
        return False
    if needle is None:
        return True
    if target.is_dir():
        return any(
            needle in f.read_text(encoding="utf-8", errors="ignore")
            for f in target.rglob("*")
            if f.is_file() and "node_modules" not in f.parts
        )
    return needle in target.read_text(encoding="utf-8", errors="ignore")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    # Fixed git subcommands on this repository; nothing comes from outside.
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def releases(main_ref: str) -> list[Release]:
    """Every release commit on main, oldest first."""
    out = git("log", main_ref, "--format=%H%x09%ad%x09%s", "--date=short")
    if out.returncode != 0:
        return []
    found: list[Release] = []
    for line in out.stdout.splitlines():
        sha, date, subject = (line.split("\t", 2) + ["", ""])[:3]
        match = RELEASE_SUBJECT.match(subject)
        if not match:
            continue
        title = match.group(2).strip()
        if title.startswith("(") and title.endswith(")"):
            title = title[1:-1]
        found.append(Release(sha, match.group(1), date, title))
    return list(reversed(found))


def history_starts(history: list[Release]) -> set[int]:
    """Releases with no release in the HISTORY_GAP_DAYS before them (the first included)."""
    starts = {0} if history else set()
    for index in range(1, len(history)):
        gap = date.fromisoformat(history[index].date) - date.fromisoformat(history[index - 1].date)
        if gap.days > HISTORY_GAP_DAYS:
            starts.add(index)
    return starts


def in_release(release: Release, path: str, needle: str | None) -> bool:
    if needle is None:
        return git("cat-file", "-e", f"{release.sha}:{path}").returncode == 0
    return git("grep", "-q", "-F", needle, release.sha, "--", path).returncode == 0


def first_release(history: list[Release], path: str, needle: str | None) -> int | None:
    """Index of the oldest release carrying the anchor (presence assumed to stay)."""
    if not history or not in_release(history[-1], path, needle):
        return None
    low, high = 0, len(history) - 1
    while low < high:
        mid = (low + high) // 2
        if in_release(history[mid], path, needle):
            high = mid
        else:
            low = mid + 1
    return low


def python_sources() -> list[Path]:
    base = ROOT / "packages" / "python" / "ac_platform"
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def api_routes(sources: list[Path]) -> list[str]:
    """Method and path of every route; a relative path joins the APIRouter prefix above it."""
    routes: set[str] = set()
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="ignore")
        prefix = ""
        for match in API_ROUTE.finditer(text):
            if match.group("prefix") is not None:
                prefix = match.group("prefix")
                continue
            path = match.group("path")
            if not path.startswith("/v1"):
                if not prefix:
                    continue
                path = prefix + ("" if path == "/" else path)
            routes.add(f"{match.group('method').upper()} {path}")
    return sorted(routes)


def env_switches(sources: list[Path]) -> list[str]:
    names: set[str] = set()
    for source in sources:
        names.update(ENV_SWITCH.findall(source.read_text(encoding="utf-8", errors="ignore")))
    return sorted(names)


def settings_areas() -> list[dict[str, object]]:
    registry = ROOT / "packages" / "python" / "ac_platform" / "admin_settings" / "registry.py"
    if not registry.exists():
        return []
    counts = Counter(SETTINGS_AREA.findall(registry.read_text(encoding="utf-8")))
    return [{"area": area, "entries": n} for area, n in sorted(counts.items())]


def shot_paths(fixture: str | None) -> dict[str, str]:
    """Screenshots of a feature's fixture page, made by `wb-ci --visual` (fictional data)."""
    if not fixture:
        return {}
    prefix, sep, rest = fixture.partition(":")
    app, path = (prefix, rest) if sep and prefix in APPS else ("sx", fixture)
    slug = path.removeprefix("/review-fixture/").strip("/").replace("/", "-")
    if app != "sx":
        slug = f"{app}-{slug}"
    shots: dict[str, str] = {}
    for size in ("390", "1440"):
        for theme in ("light", "dark"):
            name = f"{slug}-{size}-{theme}.webp"
            if (SHOTS / name).exists():
                shots[f"{size}-{theme}"] = f"/catalogue/shots/{name}"
    return shots


def fixture_url(fixture: str | None) -> str | None:
    if not fixture:
        return None
    prefix, sep, rest = fixture.partition(":")
    if sep and prefix in APPS:
        origin = APPS[prefix][2]
        return f"{origin}{rest}" if origin else None
    return f"{APPS['sx'][2]}{fixture}"


def build(use_git: bool, main_ref: str) -> tuple[dict[str, object], list[str]]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    routes = {key: page_routes(app[0]) for key, app in APPS.items()}
    history = releases(main_ref) if use_git else []
    starts = history_starts(history)
    sources = python_sources()
    all_api = api_routes(sources)
    problems: list[str] = []
    named_pages: set[str] = set()

    categories = {c["id"] for c in seed["categories"]}
    products = {p["id"] for p in seed["products"]}
    features: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in seed["features"]:
        fid = item["id"]
        if fid in seen:
            problems.append(f"{fid}: duplicate id")
        seen.add(fid)
        if item["category"] not in categories:
            problems.append(f"{fid}: unknown category {item['category']}")
        if item["product"] not in products:
            problems.append(f"{fid}: unknown product {item['product']}")

        anchors = []
        since_index: int | None = -1
        for anchor in item.get("anchors", []):
            path, needle = resolve_anchor(anchor, routes)
            exists = present_now(path, needle)
            if not exists:
                problems.append(f"{fid}: anchor {anchor} not found ({path})")
            named_pages.add(path)
            first = first_release(history, path, needle) if history and exists else None
            if first is None:
                since_index = None
            elif since_index is not None:
                since_index = max(since_index, first)
            anchors.append({"anchor": anchor, "path": path, "exists": exists})

        if item.get("status") == "planned":
            status = "planned"
        elif not anchors:
            status = "dev"
            problems.append(f"{fid}: not planned, but it names no code")
        elif all(a["exists"] for a in anchors) and since_index is not None and since_index >= 0:
            status = "live"
        else:
            status = "dev"
        since = None
        if status == "live" and since_index is not None and since_index >= 0:
            release = history[since_index]
            since = {
                "version": release.version,
                "date": release.date,
                "or_earlier": since_index in starts,
            }

        api_count = sum(
            1
            for route in all_api
            if any(route.split(" ", 1)[1].startswith(p) for p in item.get("api", []))
        )
        features.append(
            {
                "id": fid,
                "name": item["name"],
                "product": item["product"],
                "category": item["category"],
                "value": item["value"],
                "for": item.get("for", []),
                "details": item.get("details", []),
                "switch": item.get("switch"),
                "status": status,
                "since": since,
                "anchors": anchors,
                "api": {"prefixes": item.get("api", []), "routes": api_count},
                "fixture": item.get("fixture"),
                "preview": fixture_url(item.get("fixture")),
                "shots": shot_paths(item.get("fixture")),
            }
        )

    pages = []
    for key, (_app_dir, app_name, _origin) in APPS.items():
        product_pages = {r: p for r, p in routes[key].items() if not INTERNAL_PAGE.match(r)}
        unnamed = sorted(r for r, p in product_pages.items() if p not in named_pages)
        pages.append(
            {
                "app": app_name,
                "key": key,
                "pages": len(product_pages),
                "fixtures": len(routes[key]) - len(product_pages),
                "named": len(product_pages) - len(unnamed),
                "unnamed": unnamed,
            }
        )

    by_prefix = Counter("/".join(route.split(" ", 1)[1].split("/")[:3]) for route in all_api)
    head = git("log", "-1", "--format=%h%x09%cd", "--date=iso-strict") if use_git else None
    head_sha, head_date = (
        head.stdout.strip().split("\t") if head and head.returncode == 0 else ("", "")
    )
    latest = history[-1] if history else None
    catalogue = {
        "schema": 1,
        "source": {"commit": head_sha, "date": head_date, "main": main_ref},
        "latest_release": (
            {"version": latest.version, "date": latest.date, "title": latest.title}
            if latest
            else None
        ),
        "products": seed["products"],
        "categories": seed["categories"],
        "audiences": seed["audiences"],
        "features": features,
        "counts": {s: sum(1 for f in features if f["status"] == s) for s in STATUSES},
        "pages": pages,
        "api": {
            "routes": len(all_api),
            "areas": [{"prefix": p, "routes": n} for p, n in by_prefix.most_common()],
        },
        "settings": settings_areas(),
        "switches": env_switches(sources),
        "releases": [
            {"version": r.version, "date": r.date, "title": r.title}
            for r in reversed(history[-30:])
        ],
    }
    return catalogue, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-git", action="store_true", help="skip release history")
    parser.add_argument("--main", default="origin/main", help="ref whose releases count")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any problem")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    catalogue, problems = build(not args.no_git, args.main)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalogue, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    prettier = ROOT / "node_modules" / ".bin" / "prettier"
    if prettier.exists():  # the file is checked by prettier like any other in the repo
        subprocess.run(  # noqa: S603 - the repo's own prettier on the file just written
            [str(prettier), "--write", "--log-level", "warn", str(args.output)], check=False
        )
    counts = catalogue["counts"]
    where = args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output
    print(
        f"{len(catalogue['features'])} features: {counts['live']} live, {counts['dev']} on dev, "
        f"{counts['planned']} planned -> {where}"
    )
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    return 1 if args.strict and problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
