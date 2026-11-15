"""The phone side of a release run: dialler file names, call times inside work hours, unique
bytes per run, and a thin adb wrapper for the Redmi 13.

What the Android app expects of a dialler recording (proven on the Redmi 13, 2-3 Nov 2026;
memory ``reference-dialler-capture-sim``):

- the Xiaomi recorder's name, ``<number>(<number>)_yyyyMMddHHmmss.mp3``, with the lead's number;
- the time in the name inside the workspace's work hours, after the lead was created
  (otherwise the server answers 409 and the app skips the file without a word);
- the file's saved time after that moment and at most 4 h 3 min later, and at least a minute
  old when the app's worker looks.

Pure Python (standard library only): it runs on the laptop that has the phone on USB.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# India has no daylight saving: a fixed offset needs no time-zone database (Windows Python).
IST = timezone(timedelta(hours=5, minutes=30), "IST")
PACKAGE = "com.authorityclosers.salesxray"
LIVE_PACKAGE = "com.authorityclosers.salesxray.live"
QA_FOLDER = "/sdcard/SalesXray-QA-empty"
DIALLER_FOLDER = "/sdcard/MIUI/sound_recorder/call_rec"
MAX_SAVE_DELAY = timedelta(hours=4, seconds=180)


@dataclass(frozen=True, slots=True)
class WorkHours:
    days: tuple[int, ...]  # 0 is Monday
    start: time
    end: time


def parse_hours(config: Mapping[str, Any] | None) -> WorkHours | None:
    """The workspace's work hours from its lead-desk config, by the server's rule
    (``lead_desk/hours.py``): None when unset, which means every hour counts."""
    raw = (config or {}).get("work_hours")
    if not isinstance(raw, Mapping):
        return None
    try:
        start = time.fromisoformat(str(raw.get("start"))).replace(second=0, microsecond=0)
        end = time.fromisoformat(str(raw.get("end"))).replace(second=0, microsecond=0)
    except ValueError:
        return None
    days = raw.get("days")
    if not isinstance(days, list) or start >= end:
        return None
    picked = tuple(sorted({d for d in days if isinstance(d, int) and 0 <= d <= 6}))
    return WorkHours(picked, start, end) if picked else None


def dialler_number(number: str) -> str:
    """The number as the Xiaomi recorder writes it in a file name. Seen on the Redmi 13: an
    Indian toll-free number as dialled, without the country code
    (``18008899999(18008899999)_…``, 31 Oct to 10 Nov 2026), and other Indian numbers in
    the international form with 00 (``0091…``, 2 Nov 2026)."""
    digits = re.sub(r"\D", "", number)
    if number.strip().startswith("+") and digits.startswith("91") and len(digits) >= 12:
        national = digits[2:]
        digits = national if national.startswith("1800") else "0091" + national
    if not 6 <= len(digits) <= 16:
        raise ValueError("number")
    return digits


def dialler_name(number: str, stamp: datetime) -> str:
    """The Xiaomi call recorder's file name for a call to ``number`` at ``stamp`` (India time)."""
    digits = dialler_number(number)
    local = stamp.astimezone(IST)
    return f"{digits}({digits})_{local:%Y%m%d%H%M%S}.mp3"


def _windows(hours: WorkHours | None, day: date) -> tuple[datetime, datetime] | None:
    if hours is None:
        return (
            datetime.combine(day, time(0, 0), IST),
            datetime.combine(day, time(23, 59, 59), IST),
        )
    if day.weekday() not in hours.days:
        return None
    return datetime.combine(day, hours.start, IST), datetime.combine(day, hours.end, IST)


def plan_slots(
    durations: Sequence[float],
    hours: WorkHours | None,
    now: datetime,
    *,
    used: Iterable[tuple[datetime, datetime]] = (),
    gap_seconds: float = 180,
    min_age_seconds: float = 150,
    not_before: datetime | None = None,
    days_back: int = 7,
) -> list[datetime]:
    """Start times for the calls, back to back in order, as late as possible.

    The whole block sits inside one working window, ends at least ``min_age_seconds`` before
    ``now`` (so every file is a minute old when the app looks), starts after ``not_before``
    (the lead's creation) and overlaps no earlier run's block (``used``); one seller never has
    two calls at once. Raises ValueError when nothing fits within ``days_back`` days.
    """
    if not durations:
        return []
    gap = timedelta(seconds=gap_seconds)
    lengths = [timedelta(seconds=max(1.0, float(d))) for d in durations]
    total = sum(lengths, timedelta()) + gap * (len(lengths) - 1)
    blocked = sorted((a.astimezone(IST), b.astimezone(IST)) for a, b in used)
    latest_end = now.astimezone(IST) - timedelta(seconds=min_age_seconds)
    floor = not_before.astimezone(IST) if not_before else None
    today = latest_end.date()
    for back in range(days_back + 1):
        window = _windows(hours, today - timedelta(days=back))
        if window is None:
            continue
        start_limit, end = window
        end = min(end, latest_end)
        if floor is not None:
            start_limit = max(start_limit, floor + timedelta(seconds=60))
        while end - start_limit >= total:
            begin = end - total
            clash = [b for b in blocked if b[0] - gap < end and begin < b[1] + gap]
            if not clash:
                starts, cursor = [], begin
                for length in lengths:
                    starts.append(cursor.replace(microsecond=0))
                    cursor += length + gap
                return starts
            end = min(b[0] for b in clash) - gap
    raise ValueError("no working window fits these calls in the last week")


def saved_time(stamp: datetime, seconds: float) -> datetime:
    """When the recorder would have finished writing the file: the call's end plus a moment."""
    saved = stamp + timedelta(seconds=float(seconds) + 2)
    if not stamp < saved <= stamp + MAX_SAVE_DELAY:
        raise ValueError("saved time")
    return saved


def unique_bytes(audio: bytes, run_id: str, scenario_id: str) -> bytes:
    """The same audio with an ID3v1 tag naming the run at the end, so each run's file has its
    own SHA-256 (the server never dedupes it against an earlier run) and decoders ignore it."""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,30}", run_id) or not re.fullmatch(r"R\d{2}", scenario_id):
        raise ValueError("run id or scenario id")
    if len(audio) >= 128 and audio[-128:-125] == b"TAG":
        audio = audio[:-128]

    def field(text: str, size: int) -> bytes:
        return text.encode("ascii")[:size].ljust(size, b"\0")

    tag = (
        b"TAG"
        + field(f"AC call test {scenario_id}", 30)
        + field("Authority Closers QA", 30)
        + field("synthetic", 30)
        + field("2026", 4)
        + field(run_id, 30)
        + bytes([255])  # no genre
    )
    return audio + tag


def registered_jobs(dumpsys: str, package: str) -> list[tuple[str, str]]:
    """(namespace, job id) of ``package``'s registered jobs in ``dumpsys jobscheduler``.
    Android 16 names WorkManager's jobs with a namespace
    (``JOB androidx.work.systemjobscheduler:u0a354/363: 5f2a131 @…@<package>/…``);
    older Android has none (``JOB #u0a354/363: 5f2a131 <package>/…``)."""
    head = dumpsys.split("Recently completed jobs:")[0]
    pattern = rf"JOB (?:#|([\w.]+):)u\d+a?\d*/(\d+): \S+ (?:@[\w.]+@)?{re.escape(package)}/"
    return sorted(set(re.findall(pattern, head)), key=lambda job: int(job[1]))


def call_log_seconds(content_query: str) -> int | None:
    """The longest ``duration=`` in ``content query`` rows of the call log, or None."""
    found = [int(v) for v in re.findall(r"\bduration=(\d+)", content_query)]
    return max(found) if found else None


class AdbError(RuntimeError):
    pass


class Adb:
    """adb against one phone, always with ``-s``; never the Note 8 Pro."""

    FORBIDDEN = ("192.168.1.5",)

    def __init__(self, serial: str, adb: str = "adb", timeout: float = 60) -> None:
        if any(serial.startswith(bad) for bad in self.FORBIDDEN):
            raise AdbError("that phone is the owner's design phone: never driven by tests")
        self.serial = serial
        self.adb = adb
        self.timeout = timeout

    def run(self, *args: str, check: bool = True, timeout: float | None = None) -> str:
        done = subprocess.run(  # noqa: S603 - adb with fixed verbs and our own paths
            [self.adb, "-s", self.serial, *args],
            capture_output=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        out = done.stdout.decode("utf-8", "replace")
        if check and done.returncode != 0:
            raise AdbError(
                f"adb {' '.join(args[:2])}: {done.stderr.decode('utf-8', 'replace')[:300]}"
            )
        return out

    def sh(self, command: str, *, check: bool = True, timeout: float | None = None) -> str:
        return self.run("shell", command, check=check, timeout=timeout)

    def online(self) -> bool:
        return self.run("get-state", check=False).strip() == "device"

    def foreground(self) -> str:
        """The package of the activity on screen, or ''."""
        text = self.sh(
            "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity'",
            check=False,
        )
        found = re.search(r"\s([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.$]+", text)
        return found.group(1) if found else ""

    def package_version(self, package: str = PACKAGE) -> dict[str, str]:
        text = self.sh(
            f"dumpsys package {package} | grep -E 'versionName|versionCode|lastUpdateTime'",
            check=False,
        )
        out: dict[str, str] = {}
        for key in ("versionName", "versionCode", "lastUpdateTime"):
            found = re.search(rf"{key}=([^\s]+(?: [0-9:]+)?)", text)
            if found:
                out[key] = found.group(1)
        return out

    def pid(self, package: str = PACKAGE) -> str:
        return self.sh(f"pidof {package}", check=False).strip()

    def epoch(self) -> int:
        return int(self.sh("date +%s").strip())

    def listing(self, folder: str, prefix: str = "") -> list[tuple[str, int, int]]:
        """(name, bytes, mtime) of files in ``folder`` whose name starts with ``prefix``. Only
        matching names are printed, so the real recordings beside them are never listed."""
        if not re.fullmatch(r"/sdcard/[A-Za-z0-9_./-]+", folder) or not re.fullmatch(
            r"[0-9]*", prefix
        ):
            raise AdbError("folder or prefix")
        text = self.sh(
            f"cd {folder} 2>/dev/null && stat -c '%n|%s|%Y' {prefix}*.mp3 2>/dev/null", check=False
        )
        rows = []
        for line in text.splitlines():
            parts = line.strip().rsplit("|", 2)
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                rows.append((parts[0], int(parts[1]), int(parts[2])))
        return rows

    def push(self, local: str, remote: str) -> None:
        self.run("push", local, remote, timeout=120)

    def set_mtime(self, remote: str, epoch: int) -> int:
        """Set the file's saved time and read it back (toybox ``touch -d @epoch``)."""
        self.sh(f"touch -m -d @{int(epoch)} '{remote}'", check=False)
        got = self.sh(f"stat -c %Y '{remote}'").strip()
        if not got.isdigit() or abs(int(got) - int(epoch)) > 1:
            raise AdbError(f"could not set the saved time of {remote}")
        return int(got)

    def sha256(self, remote: str) -> str:
        return self.sh(f"sha256sum '{remote}'").split()[0]

    def remove(self, remote: str) -> None:
        self.sh(f"rm -f '{remote}'")

    def crash_lines(self, package: str, since_epoch: int) -> list[str]:
        """Android crash-buffer lines naming ``package`` since ``since_epoch``."""
        text = self.sh("logcat -b crash -d -v epoch", check=False, timeout=30)
        lines = []
        for line in text.splitlines():
            stamp = re.match(r"\s*(\d+)\.\d+", line)
            if stamp and int(stamp.group(1)) >= since_epoch and package in line:
                lines.append(line.strip()[:300])
        return lines

    def call_seconds(self, number: str, since_epoch: int) -> int | None:
        """How long the phone's call history says the call to ``number`` lasted, for calls
        since ``since_epoch``. Only rows for that one test number are read."""
        if not re.fullmatch(r"\d{6,15}", number):
            raise AdbError("number")
        text = self.sh(
            "content query --uri content://call_log/calls --projection number:duration:date "
            f"--where \"number='{number}' AND date>={int(since_epoch) * 1000}\"",
            check=False,
        )
        return call_log_seconds(text)

    def bring_forward(self, package: str = PACKAGE) -> None:
        self.sh(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", check=False)

    def nudge_capture(self, package: str = PACKAGE) -> list[str]:
        """Run the app's scheduled background jobs now (WorkManager's), so the capture scan
        doesn't wait up to 15 minutes. Returns the job ids that were run."""
        text = self.sh(f"dumpsys jobscheduler {package}", check=False, timeout=30)
        jobs = registered_jobs(text, package)
        for namespace, job in jobs:
            flag = f"-n {namespace} " if namespace else ""
            self.sh(f"cmd jobscheduler run -f {flag}{package} {job}", check=False)
        return [f"{namespace}:{job}" if namespace else job for namespace, job in jobs]

    def our_notifications(self, package: str = PACKAGE) -> list[str]:
        """Titles and texts of this app's notifications only."""
        text = self.sh("dumpsys notification --noredact", check=False, timeout=30)
        out: list[str] = []
        for block in text.split("NotificationRecord(")[1:]:
            if f"pkg={package} " not in block[:400]:
                continue
            for key in ("android.title", "android.text"):
                found = re.search(rf"{key}=String \((.*?)\)\n", block)
                if found:
                    out.append(found.group(1)[:160])
        return out
