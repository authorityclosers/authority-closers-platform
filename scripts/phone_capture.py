"""Phone proof in one command: a screenshot or a recording, with a JSON of what the phone ran.

    python scripts/phone_capture.py SERIAL LABEL [--record SECONDS] [--package PACKAGE] [--out DIR]

SERIAL is the phone's adb serial (`adb devices`). LABEL names the shot ("home-after-fix"). With
--record the phone's screen is recorded for that many seconds (3 to 180); without it a screenshot is
taken. The media file and `<same name>.json` land in DIR (default docs/evidence/phone, next to the
repo root).

The JSON holds the serial, the device model, the UTC time, the installed Sales X-Ray app's
versionName and versionCode from `dumpsys package`, and the web build the page shows (the "Build
3b08990 · App 1.0.84" line at the foot of Settings, Help & support), read off the screen with
`uiautomator dump` when that line is visible. Every fact is read from the phone. There is no option
to type a build or a commit in, and a LABEL that looks like a commit is refused: proof names the
build the phone is running, not the one somebody says it runs.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "evidence" / "phone"
PACKAGE_PREFIX = "com.authorityclosers.salesxray"
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
LOOKS_LIKE_A_COMMIT = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
BUILD_LINE = re.compile(r"^Build ([0-9a-f]{7}|dev|[\w.-]+)(?: · App ([\w.-]+))?$")
MIN_SECONDS = 3
MAX_SECONDS = 180  # screenrecord's own limit


class Runner(Protocol):
    def __call__(self, args: list[str], timeout: float = ...) -> bytes: ...


def real_runner(args: list[str], timeout: float = 60) -> bytes:
    result = subprocess.run(  # noqa: S603
        args, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()[:200]
        raise RuntimeError(f"{' '.join(args[:4])} failed ({result.returncode}): {detail}")
    return result.stdout


def find_adb() -> str:
    found = os.environ.get("ADB") or shutil.which("adb")
    if found:
        return found
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")):
        for name in ("adb", "adb.exe"):
            if root and (Path(root) / "platform-tools" / name).exists():
                return str(Path(root) / "platform-tools" / name)
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe").exists():
        return str(Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    raise RuntimeError("adb was not found: put it on PATH or set ADB to its path")


def check_label(label: str) -> str:
    if LOOKS_LIKE_A_COMMIT.match(label):
        raise ValueError(
            "the label looks like a commit; the build is read from the phone, never typed in"
        )
    if not LABEL.match(label):
        raise ValueError("the label is letters, digits, dot, dash and underscore, 1 to 61 long")
    return label


def parse_installed(text: str) -> list[str]:
    """`pm list packages` lines -> the Sales X-Ray packages, in the order listed."""
    names = [line.strip().removeprefix("package:") for line in text.splitlines()]
    return [name for name in names if name.startswith(PACKAGE_PREFIX)]


def parse_package_dump(text: str) -> dict[str, str | None]:
    """`dumpsys package <name>`: the first versionName and versionCode it lists."""
    name = re.search(r"versionName=(\S+)", text)
    code = re.search(r"versionCode=(\d+)", text)
    return {
        "versionName": name.group(1) if name else None,
        "versionCode": code.group(1) if code else None,
    }


def parse_focus(text: str) -> str | None:
    """`dumpsys window` -> the package that has focus."""
    found = re.search(r"mCurrentFocus=Window\{[^}]*? u\d+ ([\w.]+)/", text)
    return found.group(1) if found else None


def find_build_line(xml: str) -> str | None:
    """`uiautomator dump` XML -> the build line ("Build 3b08990 · App 1.0.84") if on screen."""
    for raw in re.findall(r'text="([^"]*)"', xml):
        text = html.unescape(raw).strip()
        if BUILD_LINE.match(text) and text.startswith("Build "):
            return text
    return None


class Phone:
    def __init__(self, adb: str, serial: str, run: Runner = real_runner) -> None:
        self.adb = adb
        self.serial = serial
        self.run = run

    def shell(self, *args: str, timeout: float = 30) -> str:
        out = self.run([self.adb, "-s", self.serial, "shell", *args], timeout)
        return out.decode("utf-8", "replace").replace("\r", "")

    def prop(self, name: str) -> str:
        return self.shell("getprop", name).strip()

    def state(self) -> str:
        return self.run([self.adb, "-s", self.serial, "get-state"], 15).decode().strip()

    def screenshot(self) -> bytes:
        return self.run([self.adb, "-s", self.serial, "exec-out", "screencap", "-p"], 60)

    def pull(self, remote: str, local: Path) -> None:
        self.run([self.adb, "-s", self.serial, "pull", remote, str(local)], 120)


def facts(phone: Phone, package: str | None) -> dict[str, object]:
    installed = parse_installed(phone.shell("pm", "list", "packages", PACKAGE_PREFIX))
    focus = parse_focus(phone.shell("dumpsys", "window", timeout=30))
    chosen = package or (focus if focus in installed else (installed[0] if installed else None))
    app: dict[str, str | None] = {"package": chosen, "versionName": None, "versionCode": None}
    if chosen:
        app.update(parse_package_dump(phone.shell("dumpsys", "package", chosen, timeout=60)))
    size = phone.shell("wm", "size").strip().removeprefix("Physical size: ").splitlines() or [""]
    return {
        "app": app,
        "installed": installed,
        "foreground": focus,
        "model": phone.prop("ro.product.model"),
        "manufacturer": phone.prop("ro.product.manufacturer"),
        "android": phone.prop("ro.build.version.release"),
        "sdk": phone.prop("ro.build.version.sdk"),
        "screen": size[0],
    }


def web_build(phone: Phone) -> tuple[str | None, str]:
    """The build line on screen, read with uiautomator; (None, why) when it cannot be read."""
    remote = "/sdcard/sx-capture-window.xml"
    try:
        phone.shell("uiautomator", "dump", remote, timeout=45)
        xml = phone.run([phone.adb, "-s", phone.serial, "exec-out", "cat", remote], 30).decode(
            "utf-8", "replace"
        )
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        return None, f"screen not readable: {str(error)[:80]}"
    finally:
        with contextlib.suppress(RuntimeError, subprocess.TimeoutExpired):
            phone.shell("rm", "-f", remote)
    line = find_build_line(xml)
    if line:
        return line, "read from the screen"
    return None, "no build line on screen (Settings, Help & support shows it)"


def capture(
    phone: Phone, label: str, out: Path, record: int | None, package: str | None, now: datetime
) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    stem = f"{label}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    info = facts(phone, package)
    build, note = web_build(phone)  # before the recording starts: the screen as it was
    if record is None:
        media = out / f"{stem}.png"
        media.write_bytes(phone.screenshot())
        kind = "screenshot"
    else:
        media = out / f"{stem}.mp4"
        remote = f"/sdcard/sx-capture-{stamp}.mp4"
        try:
            phone.shell("screenrecord", "--time-limit", str(record), remote, timeout=record + 30)
            time.sleep(1)  # the encoder closes the file a moment after screenrecord returns
            phone.pull(remote, media)
        finally:
            with contextlib.suppress(RuntimeError, subprocess.TimeoutExpired):
                phone.shell("rm", "-f", remote)
        kind = "recording"
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    proof = {
        "label": label,
        "serial": phone.serial,
        "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "seconds": record,
        "media": media.name,
        "media_sha256": digest,
        **info,
        "web_build": build,
        "web_build_note": note,
    }
    (out / f"{stem}.json").write_text(
        json.dumps(proof, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    return media


def main(argv: list[str] | None = None, run: Runner = real_runner) -> int:
    parser = argparse.ArgumentParser(
        description="Screenshot or screen recording with a JSON of what the phone runs."
    )
    parser.add_argument("serial", help="the phone's adb serial (adb devices)")
    parser.add_argument("label", help="what the shot shows, e.g. home-after-fix")
    parser.add_argument(
        "--record", type=int, metavar="SECONDS", help="record the screen instead (3 to 180)"
    )
    parser.add_argument(
        "--package",
        help=f"the app's package (default: the focused one, else the first {PACKAGE_PREFIX}*)",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="folder for the media and the JSON"
    )
    args = parser.parse_args(argv)
    try:
        label = check_label(args.label)
        if args.record is not None and not MIN_SECONDS <= args.record <= MAX_SECONDS:
            raise ValueError(f"--record takes {MIN_SECONDS} to {MAX_SECONDS} seconds")
        phone = Phone(find_adb() if run is real_runner else "adb", args.serial, run)
        if phone.state() != "device":
            raise RuntimeError(f"{args.serial} is not a ready device")
        media = capture(phone, label, args.out, args.record, args.package, datetime.now(UTC))
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"phone_capture: {error}", file=sys.stderr)
        return 2
    print(media)
    print(media.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
