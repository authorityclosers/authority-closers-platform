"""The phone smoke after each build (QA system stage 1, step 10; owner, 18 Nov 2026).

    python scripts/phone_smoke.py SERIAL [--package PACKAGE] [--out DIR] [--workspace-prefix TEST]

On the test phone (the Redmi 13, serial 7505cec), over adb, with no model and no tokens: cold-start
the installed Sales X-Ray app, check it opens signed in to the QA account's TEST workspace, press
each item of the bottom bar once and check every screen draws its own words with no junk
("undefined", "NaN", "Invalid Date") and no error page. A screenshot of each screen and
`result.json` (what the phone ran: model, versionName, versionCode, read off the phone as
scripts/phone_capture.py does) land in DIR.

It only looks. It presses nothing but the bottom bar's own items, so it never dials, never adds a
lead, never uploads. Guards, each with its own exit code so a caller can tell them apart:
  3  the app is on its sign-in screen (the QA Google account is not signed in on this phone yet)
  4  the phone is busy: another app of ours (the Live design app) is in front; nothing was touched
  5  the app is signed in, but not to a TEST workspace: never test as a real seller, so it stops
  1  a screen failed; 0 all screens passed; 2 the phone or the app could not be reached
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("phone_capture", _HERE / "phone_capture.py")
assert _spec is not None and _spec.loader is not None
phone_capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phone_capture)

PACKAGE = "com.authorityclosers.salesxray"
LIVE_APP = "com.authorityclosers.salesxray.live"
DEFAULT_OUT = phone_capture.ROOT / "docs" / "evidence" / "phone-smoke"
# The bottom bar's items, by the words on them. Nothing else is ever pressed.
BAR = ("Home", "Leads", "Calls", "Reports", "Ask Dipak", "Chats", "More")
JUNK = re.compile(r"\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date|�")
BROKEN = re.compile(r"something went wrong|application error|page could not be found", re.I)
SIGN_IN = re.compile(r"continue with google|sign in to|sign in with", re.I)
NODE = re.compile(r"<node\b[^>]*>")
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

EXIT_FAILED = 1
EXIT_UNREACHABLE = 2
EXIT_SIGNED_OUT = 3
EXIT_BUSY = 4
EXIT_NOT_TEST = 5


def nodes(xml: str) -> list[dict[str, Any]]:
    """`uiautomator dump` XML -> every node with words: its text and the middle of its box."""
    out: list[dict[str, Any]] = []
    for raw in NODE.findall(xml):
        text = re.search(r'\btext="([^"]*)"', raw)
        described = re.search(r'\bcontent-desc="([^"]*)"', raw)
        words = html.unescape(
            (text.group(1) if text else "") or (described.group(1) if described else "")
        )
        box = BOUNDS.search(raw)
        if not words.strip() or not box:
            continue
        left, top, right, bottom = (int(n) for n in box.groups())
        out.append(
            {
                "text": words.strip(),
                "x": (left + right) // 2,
                "y": (top + bottom) // 2,
                "bottom": bottom,
            }
        )
    return out


def bar_items(found: list[dict[str, Any]], height: int) -> list[dict[str, Any]]:
    """The bottom bar's items: the known words, in the bottom sixth of the screen, left to right."""
    low = [n for n in found if n["text"] in BAR and n["y"] > height * 5 / 6]
    seen: set[str] = set()
    items = []
    for node in sorted(low, key=lambda n: n["x"]):
        if node["text"] not in seen:
            seen.add(node["text"])
            items.append(node)
    return items


def verdict(found: list[dict[str, Any]]) -> str | None:
    """What is wrong with a screen, from its words; None when it is fine."""
    words = [n["text"] for n in found]
    if len(words) < 4:
        return "a blank screen"
    joined = "\n".join(words)
    if BROKEN.search(joined):
        return "an error page"
    if any(JUNK.search(w) or w == "null" for w in words):
        return "junk on screen"
    return None


def signed_out(found: list[dict[str, Any]], height: int) -> bool:
    return bool(SIGN_IN.search("\n".join(n["text"] for n in found))) and not bar_items(
        found, height
    )


def in_test_workspace(found: list[dict[str, Any]], prefix: str) -> bool:
    """The header names the workspace: the QA account's starts with TEST (never a real seller's)."""
    return any(re.match(rf"^(\S+\s+)?{re.escape(prefix)} ·", n["text"]) for n in found)


def screen_height(phone: Any) -> int:
    found = re.search(r"(\d+)x(\d+)", phone.shell("wm", "size"))
    return int(found.group(2)) if found else 2400


def dump(phone: Any) -> list[dict[str, Any]]:
    phone.shell("uiautomator", "dump", "/sdcard/sx-smoke.xml", timeout=40)
    return nodes(phone.shell("cat", "/sdcard/sx-smoke.xml", timeout=20))


def smoke(
    phone: Any, package: str, out: Path, prefix: str, wait: float = 3.0
) -> tuple[int, dict[str, Any]]:
    result: dict[str, Any] = {
        "schema": "ac.sales-xray.phone-smoke/1",
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "screens": [],
    }
    if phone.state() != "device":
        result["note"] = "the phone is not connected"
        return EXIT_UNREACHABLE, result
    front = phone_capture.parse_focus(phone.shell("dumpsys", "window"))
    if front == LIVE_APP:
        result["note"] = "busy: the Live design app is in front; nothing was touched"
        return EXIT_BUSY, result
    result.update(phone_capture.facts(phone, package))
    height = screen_height(phone)
    phone.shell("am", "force-stop", package)
    phone.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    found: list[dict[str, Any]] = []
    for _ in range(20):
        time.sleep(wait)
        found = dump(phone)
        if len(found) >= 4:
            break
    if not found:
        result["note"] = "the app drew nothing after a cold start"
        return EXIT_UNREACHABLE, result
    if signed_out(found, height):
        result["note"] = (
            "the app is on its sign-in screen: the QA account is not signed in on this phone"
        )
        return EXIT_SIGNED_OUT, result
    if not in_test_workspace(found, prefix):
        result["note"] = (
            f"signed in, but not to a {prefix} workspace: stopped (never test as a real seller)"
        )
        return EXIT_NOT_TEST, result
    out.mkdir(parents=True, exist_ok=True)
    items = bar_items(found, height) or [{"text": "Home", "x": None, "y": None}]
    for item in items:
        if item["x"] is not None:
            phone.shell("input", "tap", str(item["x"]), str(item["y"]))
            time.sleep(wait)
            found = dump(phone)
        note = verdict(found)
        name = re.sub(r"[^a-z0-9]+", "-", item["text"].lower()).strip("-")
        (out / f"{name}.png").write_bytes(phone.screenshot())
        result["screens"].append(
            {"name": item["text"], "ok": note is None, **({"note": note} if note else {})}
        )
    result["ok"] = all(screen["ok"] for screen in result["screens"])
    return (0 if result["ok"] else EXIT_FAILED), result


def main(argv: list[str] | None = None, run: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("serial", help="the phone's adb serial (adb devices)")
    parser.add_argument("--package", default=PACKAGE)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--workspace-prefix", default="TEST")
    given = parser.parse_args(argv)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = given.out or DEFAULT_OUT / stamp
    phone = phone_capture.Phone(
        phone_capture.find_adb(), given.serial, run or phone_capture.real_runner
    )
    try:
        code, result = smoke(phone, given.package, out, given.workspace_prefix)
    except RuntimeError as error:
        code, result = EXIT_UNREACHABLE, {"note": str(error)[:200], "screens": []}
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for screen in result.get("screens", []):
        print(
            f"{'ok  ' if screen['ok'] else 'FAIL'} {screen['name']}"
            f"{' (' + screen['note'] + ')' if screen.get('note') else ''}"
        )
    if result.get("note"):
        print(result["note"])
    print(f"exit {code} -> {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
