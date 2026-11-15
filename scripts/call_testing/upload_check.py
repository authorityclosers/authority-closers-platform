"""Can anybody upload a recording in the Play app and get a report? One upload, timed step by step.

    python scripts/call_testing/upload_check.py --file AC-test-R03-investor-call.mp3 \
        [--workspace "Authority Closers" | --workspace Personal] [--agree]

On the Redmi 13 (``7505cec``), in the production Play app, as whoever is signed in: switch to
the workspace, + → Add a call → Choose a file → Downloads/ac-upload-check/<file>, then, only
with ``--agree``, tick "I agree to the Terms and Privacy Policy" and tap "Analyse my call", and
wait for the report. Without ``--agree`` it stops before the tick (a rehearsal: nothing is
uploaded). The file must already be in ``/sdcard/Download/ac-upload-check`` (synthetic,
fictional calls only). Each step's seconds and what the screen said are printed and saved
beside the run as JSON; the report itself is read back from production by the file's SHA-256
(``check.status_sql``, ac's logged read-only path).

The tick and the upload accept the app's terms for that account, so they run only under the
owner's own approval: whoever runs ``--agree`` must hold it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FOLDER = "ac-upload-check"
REPORT_WORDS = (
    "Biggest Strength",
    "Biggest Improvement",
    "Next call",
    "What happened",
    "Report ready",
)


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


phone = _load("phone")
check = _load("check")


# Below this the app's tab bar covers the page, above the other its header does (Redmi 13 at
# 1080 x 2187, density 476).
SAFE_BOTTOM = 1880
HEADER_BOTTOM = 350


def parse_full(xml: str) -> list[dict[str, Any]]:
    """Every node of a uiautomator dump: centre, top, bottom, label, class and whether checked."""
    found = []
    for match in re.finditer(r"<node [^>]*?>", xml):
        node = match.group(0)

        def attr(name: str, node: str = node) -> str:
            hit = re.search(rf' {name}="([^"]*)"', node)
            return hit.group(1) if hit else ""

        box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not box:
            continue
        x1, y1, x2, y2 = map(int, box.groups())
        found.append(
            {
                "x": (x1 + x2) // 2,
                "y": (y1 + y2) // 2,
                "top": y1,
                "bottom": y2,
                "label": (attr("text") or attr("content-desc")).strip(),
                "cls": attr("class"),
                "checked": attr("checked") == "true",
            }
        )
    return found


def parse_nodes(xml: str) -> list[tuple[int, int, str]]:
    """(x, y, label) of every node with text or a description, from a uiautomator dump."""
    return [(n["x"], n["y"], n["label"]) for n in parse_full(xml) if n["label"]]


def terms_controls(nodes: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The Terms checkbox (an unlabelled CheckBox; "I agree to the" is separate text) and the
    "Analyse my call" button, when both are fully on screen above the tab bar."""
    box = next((n for n in nodes if n["cls"].endswith("CheckBox") and n["bottom"] > n["top"]), None)
    button = next(
        (n for n in nodes if n["label"] == "Analyse my call" and n["bottom"] > n["top"]), None
    )
    if box and button and 250 < box["y"] < SAFE_BOTTOM - 150 and button["bottom"] < SAFE_BOTTOM:
        return box, button
    return None


class Screen:
    def __init__(self, adb: Any) -> None:
        self.adb = adb

    def full(self) -> list[dict[str, Any]]:
        self.adb.sh("uiautomator dump /sdcard/ctp-ui.xml >/dev/null 2>&1", check=False)
        xml = self.adb.sh("cat /sdcard/ctp-ui.xml", check=False)
        self.adb.sh("rm -f /sdcard/ctp-ui.xml", check=False)
        return parse_full(xml)

    def nodes(self) -> list[tuple[int, int, str]]:
        return [(n["x"], n["y"], n["label"]) for n in self.full() if n["label"]]

    def find(self, *texts: str, exact: bool = False) -> tuple[int, int, str] | None:
        """The first node for the first text that is on screen: texts are in priority order."""
        nodes = self.nodes()
        for text in texts:
            for x, y, label in nodes:
                if (label == text) if exact else (text.lower() in label.lower()):
                    return x, y, label
        return None

    def wait(self, *texts: str, seconds: float = 20, exact: bool = False) -> tuple[int, int, str]:
        deadline = time.monotonic() + seconds
        while True:
            hit = self.find(*texts, exact=exact)
            if hit or time.monotonic() > deadline:
                if not hit:
                    raise TimeoutError(f"not on screen after {seconds:.0f} s: {' / '.join(texts)}")
                return hit
            time.sleep(1)

    def tap(self, hit: tuple[int, int, str]) -> None:
        self.adb.sh(f"input tap {hit[0]} {hit[1]}")

    def tap_text(self, *texts: str, seconds: float = 20, exact: bool = False) -> str:
        hit = self.wait(*texts, seconds=seconds, exact=exact)
        self.tap(hit)
        return hit[2]

    def scroll_down(self) -> None:
        # Slow enough for the WebView to scroll, and above the page's sound-level picture.
        self.adb.sh("input swipe 540 1500 540 500 500")

    def scroll_up(self) -> None:
        # Only on a page that is scrolled down: a downward drag at the top of a page opens the
        # app's account sheet (You, with Log out).
        self.adb.sh("input swipe 540 900 540 1700 500")

    def header(self) -> str:
        """Back out of whatever covers the page (the account sheet, search, a picker) until the
        header's + shows; it does on every page of the app. Never taps: a tap on the page
        title or on the active Home tab opens the account sheet or search."""
        for _ in range(4):
            if self.adb.foreground() != phone.PACKAGE:
                self.adb.bring_forward()
                time.sleep(2.5)
            hit = self.find("Add a lead, a call or a task")
            if hit and not self.find("Log out", exact=True):
                return hit[2]
            self.adb.sh("input keyevent KEYCODE_BACK", check=False)
            time.sleep(1.5)
        raise TimeoutError("the app's header never came back")

    def reset(self) -> str:
        """A clean start: leave any file picker or "Open with" chooser an earlier run left open,
        clear a picked file or the "That didn't go through" card."""
        for _ in range(4):
            if self.adb.foreground() == phone.PACKAGE:
                break
            self.adb.sh("input keyevent KEYCODE_BACK", check=False)
            time.sleep(1)
        self.header()
        # New analysis scrolled down: back up until Clear all is below the header (behind the
        # header, a tap lands on its search or account buttons instead).
        for _ in range(6):
            clear = self.find("Clear all", exact=True)
            if clear and clear[1] > HEADER_BOTTOM:
                break
            if not clear and not self.find("file added", "Analyse my call", "I agree to the"):
                break
            self.scroll_up()
            time.sleep(1)
        cleared = []
        for _ in range(3):
            hit = self.find("Analyse another call", "Clear all", exact=True)
            if not hit or hit[1] <= HEADER_BOTTOM:
                break
            self.tap(hit)
            cleared.append(hit[2])
            time.sleep(2)
        if self.find("file added", "files added"):
            raise TimeoutError("a picked file is still there after Clear all")
        self.header()
        return "clean" + (f" (tapped {', '.join(cleared)})" if cleared else "")


def run(args: argparse.Namespace) -> dict[str, Any]:
    adb = phone.Adb(args.serial)
    screen = Screen(adb)
    local = Path(args.local_dir) / args.file
    sha = hashlib.sha256(local.read_bytes()).hexdigest() if local.exists() else None
    steps: list[dict[str, Any]] = []
    started = time.monotonic()

    def step(name: str, action: Any) -> Any:
        begin = time.monotonic()
        try:
            said = action()
            steps.append(
                {
                    "step": name,
                    "seconds": round(time.monotonic() - begin, 1),
                    "ok": True,
                    "said": said,
                }
            )
            print(f"{name}: {steps[-1]['seconds']} s · {said}", flush=True)
            return said
        except Exception as error:
            steps.append(
                {
                    "step": name,
                    "seconds": round(time.monotonic() - begin, 1),
                    "ok": False,
                    "said": str(error)[:200],
                }
            )
            print(f"{name}: FAILED · {error}", flush=True)
            raise

    result: dict[str, Any] = {
        "file": args.file,
        "sha256": sha,
        "workspace": args.workspace,
        "agreed": args.agree,
        "app": adb.package_version(phone.PACKAGE),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "steps": steps,
    }
    try:
        if adb.foreground() == phone.LIVE_PACKAGE:
            raise SystemExit("Sales X-Ray Live is in front: another session's phone")
        step("clean start", screen.reset)
        step("open the app", lambda: screen.wait("Add a lead, a call or a task", seconds=30)[2])
        if args.workspace:

            def switch() -> str:
                current = screen.wait("Switch workspace", seconds=10)[2]
                if args.workspace.lower() in current.lower():
                    return current
                screen.tap_text("Switch workspace")
                time.sleep(1.5)
                screen.tap_text(args.workspace, seconds=10)
                time.sleep(1.5)
                # The row asks "Switch to <workspace>?"; a second tap confirms.
                confirm = screen.find(f"Switch to {args.workspace}?")
                if confirm:
                    screen.tap(confirm)
                time.sleep(3)
                return screen.wait(f"Workspace: {args.workspace}", seconds=20)[2]

            step("workspace", switch)
            time.sleep(3)
        step("open +", lambda: screen.tap_text("Add a lead, a call or a task"))
        step(
            "Add a call",
            lambda: screen.tap_text("Record or upload a call for analysis", "Add a call"),
        )
        step("Choose a file", lambda: screen.tap_text("Choose a file", seconds=30, exact=True))

        def pick() -> str:
            # Android's picker opens where it was last; go to the folder unless the file shows.
            time.sleep(2)
            if adb.foreground() == phone.PACKAGE:
                raise TimeoutError("the file picker didn't open")
            if not screen.find(args.file, exact=True):
                screen.tap_text("Show roots", seconds=15, exact=True)
                time.sleep(1)
                screen.tap_text("Downloads", seconds=10, exact=True)
                time.sleep(1.5)
                screen.tap_text(FOLDER, seconds=10, exact=True)
                time.sleep(1.5)
            # The name itself: "Preview the file <name>" would open it in a player instead.
            return screen.tap_text(args.file, seconds=10, exact=True)

        step("pick the file", pick)
        added = step("file added", lambda: screen.wait("file added", "files added", seconds=30)[2])
        detail = screen.find(" KB · ", " MB · ")
        result["file_line"] = detail[2] if detail else added

        def terms_on_screen() -> tuple[dict[str, Any], dict[str, Any]]:
            for _ in range(6):
                found = terms_controls(screen.full())
                if found:
                    return found
                screen.scroll_down()
                time.sleep(1.2)
            raise TimeoutError(
                "the Terms checkbox and Analyse my call never came above the tab bar"
            )

        box, button = step(
            "Terms on screen",
            lambda: terms_on_screen(),
        )
        result["terms_at"] = {
            "checkbox": [box["x"], box["y"]],
            "analyse": [button["x"], button["y"]],
        }
        if not args.agree:
            result["stopped"] = "before the Terms tick (rehearsal, nothing ticked or uploaded)"
            return result

        def agree() -> str:
            for _ in range(2):
                found = terms_controls(screen.full())
                if found and found[0]["checked"]:
                    return "ticked"
                target = found[0] if found else box
                adb.sh(f"input tap {target['x']} {target['y']}")
                time.sleep(1)
            found = terms_controls(screen.full())
            if found and found[0]["checked"]:
                return "ticked"
            raise TimeoutError("the Terms checkbox didn't tick")

        step("tick the Terms", agree)

        def analyse() -> str:
            found = terms_controls(screen.full())
            target = found[1] if found else button
            adb.sh(f"input tap {target['x']} {target['y']}")
            return target["label"]

        step("Analyse my call", analyse)
        step("report on screen", lambda: screen.wait(*REPORT_WORDS, seconds=args.wait * 60)[2])
    finally:
        if not args.agree or not all(s["ok"] for s in steps):
            # Leave the phone clean for the next run (and never half-picked).
            try:
                result["left"] = screen.reset()
            except Exception as error:  # noqa: BLE001 - best effort, recorded
                result["left"] = f"reset failed: {error}"
        result["total_seconds"] = round(time.monotonic() - started, 1)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        name = f"upload-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{Path(args.file).stem}.json"
        (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
        print("saved", out / name)
    if sha and args.agree:
        rows = check.remote_sql(
            check.status_sql([sha], datetime.fromisoformat(result["started_at"]).replace(minute=0)),
            env="production",
            name="ctp-upload-check",
            purpose=(
                "read-only: report state and section counts of one synthetic upload-check file, "
                "by SHA-256"
            ),
        )
        result["server"] = rows[0] if rows else None
        if rows:
            row = rows[0]
            result["verdict"] = {
                "report": bool(row.get("report")),
                "coaching": bool(row.get("focus")) and (row.get("strengths") or 0) >= 1,
                "capture_source": row.get("capture_source"),
                "gaps": check.report_gaps(row),
            }
            print("server:", json.dumps(result["verdict"]))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--file", required=True)
    parser.add_argument("--workspace", default="")
    parser.add_argument(
        "--agree", action="store_true", help="tick the Terms and upload (owner's approval)"
    )
    parser.add_argument("--serial", default="7505cec")
    parser.add_argument("--wait", type=float, default=10, help="minutes to wait for the report")
    parser.add_argument(
        "--local-dir", default=str(Path.home() / "ac-call-testing" / "upload-check")
    )
    parser.add_argument(
        "--out", default=str(Path.home() / "ac-call-testing" / "upload-check" / "runs")
    )
    args = parser.parse_args(argv)
    result = run(args)
    ok = all(s["ok"] for s in result["steps"]) and (
        not args.agree or (result.get("verdict") or {}).get("report")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
