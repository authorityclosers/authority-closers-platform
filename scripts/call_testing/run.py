"""The release call check: synthetic calls go in through the Play app on the Redmi 13, the
server analyses them, and a one-page result says whether reports work on this release.

    python scripts/call_testing/run.py release [--set smoke|full|R01,R10] [--live-ivr]
    python scripts/call_testing/run.py release --dry-run      # preflight and plan, no push
    python scripts/call_testing/run.py check <run-dir>        # read back again, rewrite the page
    python scripts/call_testing/run.py fetch                  # copy the rendered audio from ac

Runs on the laptop that has the phone on USB (adb) and ``ssh ac``. Standard library only.
Audio is rendered once per library version on ac (``generate.py``); each run makes its files'
bytes unique, names them like the Xiaomi recorder for the QA lead, stamps them inside work
hours and pushes them into the production app's recordings folder, where only test recordings
live. The checker reads results through ac's logged, read-only query path, by file hash.
Exit code 0 only when every pipeline gate passes and the app didn't crash (``--strict`` adds
the sales-or-not detection).
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SERIAL = "7505cec"  # the Redmi 13 (automated QA only)
QA_LEAD = "85957539-12bd-44da-be7c-8f44c807ba1d"  # "QA Redmi 10 Nov - test", production
IVR_NUMBER = "18008899999"  # Jio's toll-free customer care: a real call with nobody to bother
REMOTE_AUDIO = "/home/acdev/simlab/call-testing"
MANIFEST_URL = "https://salesxray.authorityclosers.com/v1/app-web/manifest.json"
# Measured on production (13 Nov 2026): a report Rs 3.3 a call, a hold about Rs 0.3.
REPORT_RUPEES, HOLD_RUPEES = 3.5, 0.3


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


scenarios = _load("scenarios")
phone = _load("phone")
check = _load("check")
page = _load("page")


def say(*parts: Any) -> None:
    print(datetime.now().strftime("%H:%M:%S"), *parts, flush=True)


def fetch(cache: Path, host: str = "ac") -> Path:
    """The rendered audio for this library version, copied from ac into ``cache``."""
    version = scenarios.library_sha256()[:12]
    local = cache / version
    manifest = local / "manifest.json"
    wanted = {call["id"] for call in scenarios.library()}
    if manifest.exists():
        have = json.loads(manifest.read_text("utf-8")).get("scenarios", {})
        if wanted <= set(have) and all((local / have[s]["file"]).exists() for s in wanted):
            return local
    local.mkdir(parents=True, exist_ok=True)
    remote = f"{REMOTE_AUDIO}/{version}"
    listing = subprocess.run(  # noqa: S603
        [  # noqa: S607 - the lab is acdev's; the ssh user reads it through sudo
            "ssh",
            host,
            f"sudo -n -u acdev sh -c 'cd {remote} && tar cf - manifest.json R*.mp3' | base64 -w0",
        ],
        capture_output=True,
        timeout=300,
        check=False,
    )
    if listing.returncode != 0 or not listing.stdout:
        raise SystemExit(
            f"no rendered audio for library {version} on {host}:{remote}; "
            "run generate.py there first"
        )
    archive = local / "audio.tar"
    archive.write_bytes(base64.b64decode(listing.stdout))
    subprocess.run(["tar", "xf", archive.name], cwd=local, check=True)  # noqa: S603, S607
    archive.unlink()
    have = json.loads(manifest.read_text("utf-8"))["scenarios"]
    import hashlib

    for sid, entry in have.items():
        data = (local / entry["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SystemExit(f"{sid}: the copied audio doesn't match its manifest")
    return local


def web_version() -> dict[str, Any]:
    """The live web bundle the app loads (version and sha), from the public manifest."""
    import urllib.request

    # The edge refuses Python's default client name (403), so name ours.
    request = urllib.request.Request(  # noqa: S310 - a fixed https URL of our own
        MANIFEST_URL, headers={"User-Agent": "ac-call-testing/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - our own https URL
            body = json.loads(response.read().decode("utf-8"))
        payload = body.get("payload")
        if isinstance(payload, str):
            # A signed JSON text (sx-web-bundle/1); older manifests carried base64.
            try:
                payload = json.loads(payload)
            except ValueError:
                padded = payload + "=" * (-len(payload) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        payload = payload if isinstance(payload, dict) else body
        return {"version": payload.get("version"), "sha": payload.get("sha")}
    except Exception as error:  # noqa: BLE001 - the page just says unknown
        return {"version": None, "error": str(error)[:120]}


def used_blocks(pre: dict[str, Any], runs: Path) -> list[tuple[datetime, datetime]]:
    blocks = []
    for call in pre.get("calls") or []:
        try:
            start = datetime.fromisoformat(str(call["at"]).replace("Z", "+00:00"))
            seconds = float(call.get("seconds") or 0)
        except (KeyError, ValueError):
            continue
        blocks.append((start, start + timedelta(seconds=max(seconds, 60))))
    for old in runs.glob("*/run.json"):
        for row in json.loads(old.read_text("utf-8")).get("results", []):
            if row.get("stamp") and row.get("sha256"):  # pushed, not a dry run
                start = datetime.fromisoformat(row["stamp"])
                blocks.append((start, start + timedelta(seconds=float(row.get("seconds") or 60))))
    return blocks


def estimate(rows: list[dict[str, Any]]) -> float:
    return sum(
        REPORT_RUPEES if r["expect"]["outcome"] in {"report", "any"} else HOLD_RUPEES for r in rows
    )


SPEND_SCRIPT = r"""
import json, sys
ids = set(sys.argv[1:])
d = json.load(open("/srv/authority-closers/metrics/production/usage.json"))
rates = {"gemini-3.8-flash": (0.75, 3.75), "gemini-3.1-flash-lite": (0.50, 1.50)}
rs, unknown, billed = 0.0, set(), 0
calls = {c["id"]: c for c in d["calls"] if c["id"] in ids}
for c in calls.values():
    billed += c.get("billed_s") or 0
for s in d["steps"]:
    if s.get("call") not in ids or s.get("status") != "succeeded":
        continue
    u = s.get("usage") or {}
    p = u.get("promptTokenCount", 0)
    t = u.get("totalTokenCount", p + u.get("candidatesTokenCount", 0))
    r = rates.get(s.get("model"))
    if r is None:
        unknown.add(s.get("model")); continue
    rs += (p * r[0] + (t - p) * r[1]) / 1e6 * 100
for w in d.get("ai_work") or []:
    if w.get("call") in ids:
        rs += float(w.get("cost_inr") or 0)
print(json.dumps({"generated_at": d["generated_at"], "found": len(calls), "rupees": round(rs, 2),
                  "billed_seconds": billed, "unpriced_models": sorted(m for m in unknown if m)}))
"""


def measured_spend(recording_ids: list[str], first: bool, host: str = "ac") -> dict[str, Any]:
    ids = [i for i in recording_ids if check.UUID.fullmatch(i or "")]
    if not ids:
        return {}
    log = ""
    if first:
        log = (
            'echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ctp-spend production usage export '
            "(read-only: tokens and rupees of the synthetic test calls of this run only, "
            'by recording id) by laptop call-testing"'
            " >> /home/suyash/costq/QUERY-LOG.txt; "
        )
    done = subprocess.run(  # noqa: S603
        ["ssh", host, f"{log}python3 - {' '.join(ids)}"],  # noqa: S607
        input=SPEND_SCRIPT.encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    try:
        return json.loads(done.stdout.decode().strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"error": done.stderr.decode("utf-8", "replace")[:200]}


def live_ivr_call(adb: Any, seconds: int, folder: str) -> dict[str, Any]:
    """One real call from the phone's SIM to the Jio IVR, hung up on the phone itself after
    ``seconds``; its recording (the dialler's own file for that number, nothing else) is copied
    into the QA folder for the app to pick up."""
    start = adb.epoch()
    adb.sh(
        f"nohup sh -c 'sleep {int(seconds)}; input keyevent KEYCODE_ENDCALL' >/dev/null 2>&1 & "
        f"am start -a android.intent.action.CALL -d tel:{IVR_NUMBER}"
    )
    time.sleep(seconds + 25)
    adb.sh("input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard", check=False)
    for _ in range(3):
        adb.sh("input keyevent KEYCODE_BACK", check=False)
        time.sleep(1)
    live: dict[str, Any] = {
        "number": IVR_NUMBER,
        "seconds": seconds,
        "called_epoch": start,
        "call_log_seconds": adb.call_seconds(IVR_NUMBER, start - 5),
        "name": None,
    }
    files = [f for f in adb.listing(phone.DIALLER_FOLDER, IVR_NUMBER) if f[2] >= start]
    if files:
        name, size, mtime = sorted(files, key=lambda f: f[2])[-1]
        adb.sh(f"cp -p '{phone.DIALLER_FOLDER}/{name}' '{folder}/{name}'")
        live.update(name=name, bytes=size, saved_epoch=mtime, sha256=adb.sha256(f"{folder}/{name}"))
    return live


def poll(run: dict[str, Any], run_dir: Path, *, wait_minutes: float, adb: Any | None) -> None:
    library = {call["id"]: call for call in scenarios.library()}
    library["L01"] = LIVE_SCENARIO
    since = datetime.fromisoformat(run["started_at"]) - timedelta(minutes=5)
    deadline = time.monotonic() + wait_minutes * 60
    nudged_at = time.monotonic()
    first = not run.get("status_logged")
    while True:
        rows = check.remote_sql(
            check.status_sql([r["sha256"] for r in run["results"]], since),
            env=run["environment"],
            name=f"ctp-status-{run['run_id'].lower()}",
            purpose=(
                f"read-only: plan state, hold code and report section counts of the "
                f"{len(run['results'])} synthetic test calls, matched by file SHA-256 only; "
                "repeated each minute while the run waits"
            )
            if first
            else None,
            host=run["host"],
        )
        first = False
        run["status_logged"] = True
        by_sha = {row["sha"]: row for row in rows}
        final = time.monotonic() >= deadline
        for result in run["results"]:
            result.update(
                check.judge(library[result["id"]], by_sha.get(result["sha256"]), final=final)
            )
            result["row"] = by_sha.get(result["sha256"])
        done = all(check.is_terminal(r["outcome"]) for r in run["results"])
        save(run, run_dir)
        states = ", ".join(f"{r['id']} {r['outcome']}" for r in run["results"])
        say(states)
        if done or final:
            if not final:
                for result in run["results"]:
                    result.update(check.judge(library[result["id"]], result.get("row"), final=True))
            return
        if adb is not None and time.monotonic() - nudged_at > 300:
            if adb.foreground() not in {phone.LIVE_PACKAGE}:
                adb.nudge_capture()
            nudged_at = time.monotonic()
        time.sleep(60)


LIVE_SCENARIO = {
    "id": "L01",
    "title": "Live call from the phone's SIM to an IVR (Jio customer care)",
    "persona": (
        "a real call over the network; the far side is a recorded menu, nobody speaks for us"
    ),
    "expect": {"outcome": "any", "sales": False, "purpose": ["support", "unclear"]},
}


def save(run: dict[str, Any], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=1, default=str), "utf-8"
    )
    (run_dir / "index.html").write_text(page.render(run), "utf-8")


def release(args: argparse.Namespace) -> int:
    started = datetime.now(UTC)
    run_id = f"{started.astimezone(phone.IST):%Y%m%d-%H%M}-{secrets.token_hex(2)}"
    runs = Path(args.runs)
    run_dir = runs / run_id
    adb = phone.Adb(args.serial)
    if not adb.online():
        raise SystemExit(f"phone {args.serial} is not connected")
    front = adb.foreground()
    if front == phone.LIVE_PACKAGE:
        raise SystemExit(
            "Sales X-Ray Live is in front: another session is driving this phone. Wait."
        )
    app = adb.package_version(phone.PACKAGE)
    if not app.get("versionName"):
        raise SystemExit(f"{phone.PACKAGE} is not installed on {args.serial}")
    say("phone", args.serial, "app", app, "in front:", front or "?")

    pre_rows = check.remote_sql(
        check.preflight_sql(args.lead),
        env=args.env,
        name="ctp-preflight",
        purpose=(
            "read-only: the QA lead workspace, phone and creation time, that workspace work hours, "
            "the QA seller minute account and own call times in the last 8 days; "
            "call-testing release run"
        ),
        host=args.host,
    )
    if not pre_rows:
        raise SystemExit(f"QA lead {args.lead} not found on {args.env}")
    pre = pre_rows[0]
    if not str(pre.get("name") or "").lower().startswith("qa "):
        raise SystemExit(f"lead {args.lead} isn't named as a QA lead; refusing to write to it")
    number = str(pre.get("phone") or "")
    hours = phone.parse_hours({"work_hours": pre.get("work_hours")})
    say("QA lead", pre.get("name"), "phone", number, "hours", hours)

    picked = scenarios.pick(args.set)
    audio = fetch(Path(args.cache), args.host)
    manifest = json.loads((audio / "manifest.json").read_text("utf-8"))["scenarios"]
    durations = [manifest[c["id"]]["seconds"] for c in picked]
    now = datetime.fromtimestamp(adb.epoch(), UTC)
    created = datetime.fromisoformat(str(pre["created_at"]).replace("Z", "+00:00"))
    stamps = phone.plan_slots(
        durations, hours, now, used=used_blocks(pre, runs), not_before=created
    )

    run: dict[str, Any] = {
        "schema": "ac.call-testing.run/1",
        "run_id": run_id,
        "environment": args.env,
        "host": args.host,
        "serial": args.serial,
        "set": args.set,
        "started_at": started.isoformat(timespec="seconds"),
        "app": app,
        "web": web_version(),
        "lead_id": args.lead,
        "lead_name": pre.get("name"),
        "library_sha256": scenarios.library_sha256(),
        "minutes": pre.get("minutes"),
        "folder": args.folder,
        "results": [],
    }
    for call, stamp, seconds in zip(picked, stamps, durations, strict=True):
        run["results"].append(
            {
                "id": call["id"],
                "title": call["title"],
                "persona": call["persona"],
                "expect": call["expect"],
                "seconds": seconds,
                "stamp": stamp.isoformat(),
                "file": phone.dialler_name(number, stamp),
                "outcome": "planned",
                "gate": "pending",
                "detect": "pending",
            }
        )
    run["spend_estimate"] = estimate(run["results"])
    for row in run["results"]:
        say(row["id"], row["file"], f"{row['seconds']:.0f} s", row["title"])
    say(f"estimated analysis spend about Rs {run['spend_estimate']:.0f}")
    if args.dry_run:
        run["note"] = "Dry run: planned only, nothing pushed."
        save(run, run_dir)
        say("dry run written to", run_dir / "index.html")
        return 0

    folder = args.folder
    staging = run_dir / "files"
    staging.mkdir(parents=True, exist_ok=True)
    import hashlib

    for row in run["results"]:
        source = audio / manifest[row["id"]]["file"]
        data = phone.unique_bytes(source.read_bytes(), run_id, row["id"])
        local = staging / row["file"]
        local.write_bytes(data)
        row["sha256"] = hashlib.sha256(data).hexdigest()
        row["bytes"] = len(data)
        remote = f"{folder}/{row['file']}"
        adb.push(str(local), remote)
        saved = phone.saved_time(datetime.fromisoformat(row["stamp"]), row["seconds"])
        adb.set_mtime(remote, int(saved.timestamp()))
        if adb.sha256(remote) != row["sha256"]:
            raise SystemExit(f"{row['id']}: the file on the phone doesn't match what was pushed")
        row["outcome"] = "pushed"
        say(row["id"], "pushed", remote)
    save(run, run_dir)

    if args.live_ivr:
        inside = hours is None or (
            datetime.now(phone.IST).weekday() in hours.days
            and hours.start <= datetime.now(phone.IST).time() < hours.end
        )
        if not inside:
            say("live IVR call skipped: outside work hours, the app wouldn't log it")
            run["note"] = "Live IVR call skipped: outside work hours."
        else:
            live = live_ivr_call(adb, args.live_ivr, folder)
            run["live"] = live
            if not live.get("name"):
                say("live IVR call: no recording found")
                run["note"] = "Live IVR call made, but the phone saved no recording for it."
            else:
                run["results"].append(
                    {
                        **LIVE_SCENARIO,
                        "seconds": live["seconds"],
                        "file": live["name"],
                        "sha256": live["sha256"],
                        "bytes": live["bytes"],
                        "outcome": "pushed",
                        "gate": "pending",
                        "detect": "pending",
                        "live": live,
                    }
                )
                say("L01 live IVR recording", live["name"])
    adb.bring_forward()
    time.sleep(5)
    jobs = adb.nudge_capture()
    say("app in front; ran its background jobs", jobs)
    save(run, run_dir)

    poll(run, run_dir, wait_minutes=args.wait, adb=adb)
    return finish(run, run_dir, adb=adb, strict=args.strict, start_epoch=int(started.timestamp()))


def finish(
    run: dict[str, Any], run_dir: Path, *, adb: Any | None, strict: bool, start_epoch: int
) -> int:
    crashes = adb.crash_lines(phone.PACKAGE, start_epoch) if adb else []
    alive = bool(adb.pid(phone.PACKAGE)) if adb else True
    if adb:
        run["notifications"] = adb.our_notifications(phone.PACKAGE)
    recordings = [r["row"]["recording_id"] for r in run["results"] if r.get("row")]
    spend = measured_spend(recordings, first=not run.get("spend_logged"), host=run["host"])
    run["spend_logged"] = True
    if spend.get("found"):
        spend["note"] = (
            f"{spend['found']} of {len(recordings)} calls in the usage export of "
            f"{spend.get('generated_at', '')[:16]}Z"
        )
        run["spend"] = spend
    run["steps"] = check.step_summary(run["results"], run.get("live"))
    run["verdict"] = check.run_verdict(
        run["results"], crashes=crashes, app_alive=alive, strict=strict
    )
    run["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    if adb and all(r.get("row") for r in run["results"]):
        for r in run["results"]:
            # Our pushed files, and the copy of the live call's recording (its original stays
            # in the dialler's own folder).
            adb.remove(f"{run.get('folder', phone.QA_FOLDER)}/{r['file']}")
        run["cleaned"] = True
    save(run, run_dir)
    v = run["verdict"]
    say(
        "RESULT",
        "PASS" if v["passed"] else "FAIL",
        "gates failed:",
        v["gate_failed"] or "none",
        "detection wrong:",
        v["detect_failed"] or "none",
        "crashes:",
        len(crashes),
        "app alive:",
        alive,
    )
    say("page:", run_dir / "index.html")
    return 0 if v["passed"] else 1


def recheck(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    run = json.loads((run_dir / "run.json").read_text("utf-8"))
    adb = phone.Adb(run["serial"]) if args.phone else None
    poll(run, run_dir, wait_minutes=args.wait, adb=adb)
    return finish(
        run,
        run_dir,
        adb=adb,
        strict=args.strict,
        start_epoch=int(datetime.fromisoformat(run["started_at"]).timestamp()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    default_runs = Path.home() / "ac-call-testing" / "runs"
    default_cache = Path.home() / "ac-call-testing" / "audio"

    rel = sub.add_parser("release", help="push the calls, wait for the reports, write the page")
    rel.add_argument("--set", default="smoke", help="smoke, full or a comma list of ids")
    rel.add_argument("--serial", default=DEFAULT_SERIAL)
    rel.add_argument("--env", default="production", choices=("production", "staging"))
    rel.add_argument("--lead", default=QA_LEAD)
    rel.add_argument("--folder", default=phone.QA_FOLDER)
    rel.add_argument("--host", default="ac")
    rel.add_argument("--wait", type=float, default=35, help="minutes to wait for every result")
    rel.add_argument(
        "--live-ivr",
        type=int,
        nargs="?",
        const=75,
        default=0,
        help="also place one real call to the Jio IVR for this many seconds (work hours only)",
    )
    rel.add_argument("--strict", action="store_true", help="sales-or-not detection also gates")
    rel.add_argument("--dry-run", action="store_true")
    rel.add_argument("--runs", default=str(default_runs))
    rel.add_argument("--cache", default=str(default_cache))

    chk = sub.add_parser("check", help="read an earlier run back again")
    chk.add_argument("run_dir")
    chk.add_argument("--wait", type=float, default=0)
    chk.add_argument("--phone", action="store_true", help="also read the phone (crashes, notices)")
    chk.add_argument("--strict", action="store_true")

    fet = sub.add_parser("fetch", help="copy the rendered audio from ac")
    fet.add_argument("--cache", default=str(default_cache))
    fet.add_argument("--host", default="ac")

    args = parser.parse_args(argv)
    if args.command == "release":
        return release(args)
    if args.command == "check":
        return recheck(args)
    print(fetch(Path(args.cache), args.host))
    return 0


if __name__ == "__main__":
    sys.exit(main())
