"""acdev dev server nightly restart: stop, clear the Turbopack cache above its cap, start, wait for
the first compile, delete the old cache; a unit stopped on purpose stays stopped (21 Oct 2026).
The Sales Xray dev server's recorded units point it at its own cache and the watchdog's probe."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "infra/application/development"
SCRIPT = DEV / "acdev-dev-restart.sh"
XRAY = DEV / "acdev-xray-dev"
UNIT = "acdev-xray-dev.service"
URL = "http://127.0.0.1:3026/login"
HOST = "salesxray-dev.authorityclosers.com"
NOW = 1_792_620_000


def _fake(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


def _cache(tmp_path: Path, mib: int) -> Path:
    cache = tmp_path / "app/.next/dev/cache/turbopack"
    (cache / "v16.3.8-b0fad0d4").mkdir(parents=True)
    (cache / "v16.3.8-b0fad0d4/00000001.sst").write_bytes(b"\0" * (mib * 1_048_576))
    return cache


def _run(
    tmp_path: Path,
    cache: Path,
    cap: int,
    *,
    state: str = "active",
    codes: tuple[str, ...] = ("000", "200"),
    start_ok: bool = True,
    extra: tuple[str, ...] = (URL, HOST),
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    calls = tmp_path / "calls.txt"
    (tmp_path / "codes.txt").write_text("".join(f"{code}\n" for code in codes))
    systemctl = _fake(
        tmp_path,
        "systemctl",
        f"""case "$2" in
  is-active) printf '%s\\n' '{state}'; [[ '{state}' == active ]] ;;
  show) [[ "$4" == MemoryPeak ]] && printf '%s\\n' 3192516608 || printf '%s\\n' 536870912 ;;
  start)
    [[ -e '{cache}' ]] && seen=present || seen=absent
    printf 'start %s cache=%s\\n' "$3" "$seen" >> '{calls}'
    {"exit 0" if start_ok else "exit 1"} ;;
  *) printf '%s %s\\n' "$2" "$3" >> '{calls}' ;;
esac
""",
    )
    curl = _fake(
        tmp_path,
        "curl",
        f"""old=('{cache}'.old-*)
[[ -e "${{old[0]}}" ]] && old=yes || old=no
printf 'curl %s old=%s\\n' "$*" "$old" >> '{calls}'
code="$(head -n 1 '{tmp_path / "codes.txt"}')"
[[ -n "$code" ]] && sed -i 1d '{tmp_path / "codes.txt"}' || code=000
printf '%s' "$code"
""",
    )
    sleep = _fake(tmp_path, "sleep", f"printf 'sleep %s\\n' \"$1\" >> '{calls}'\n")
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), UNIT, str(cache), str(cap), *extra],  # noqa: S607
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "RESTART_SYSTEMCTL": str(systemctl),
            "RESTART_CURL": str(curl),
            "RESTART_SLEEP": str(sleep),
            "RESTART_NOW": str(NOW),
            "RESTART_WATCHDOG_STATE_DIR": str(tmp_path / "watchdog"),
            "RESTART_WARMUP_TRIES": "3",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return result, lines


def _leftovers(cache: Path) -> list[str]:
    return sorted(path.name for path in cache.parent.iterdir() if path.name != "turbopack")


def test_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607


def test_a_cache_above_its_cap_is_gone_before_the_start_and_deleted_after_the_first_compile(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path, 3)
    result, calls = _run(tmp_path, cache, 1)
    assert result.returncode == 0, result.stderr
    assert calls[0] == f"stop {UNIT}"
    assert calls[1] == f"start {UNIT} cache=absent"
    # The old copy is still there while the first page compiles, and gone afterwards.
    assert [line for line in calls if line.startswith("curl")] == [
        f"curl -s -o /dev/null -m 60 -w %{{http_code}} -H Host: {HOST} {URL} old=yes"
    ] * 2
    assert not cache.exists()
    assert _leftovers(cache) == []
    assert re.fullmatch(
        rf"acdev-dev-restart: {UNIT} restarted \(memory peak since its last start 3044M\); "
        rf"cache [34]M above cap 1M, cleared; {URL} answered 200 after \d+s; memory 512M\n",
        result.stdout,
    ), result.stdout


def test_the_planned_restart_starts_the_watchdog_grace(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, _cache(tmp_path, 1), 2048)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "watchdog/acdev-xray-dev/last-restart").read_text() == f"{NOW}\n"


def test_a_cache_within_its_cap_is_kept(tmp_path: Path) -> None:
    cache = _cache(tmp_path, 1)
    result, calls = _run(tmp_path, cache, 2048, codes=("307",))
    assert result.returncode == 0, result.stderr
    assert calls[:2] == [f"stop {UNIT}", f"start {UNIT} cache=present"]
    assert (cache / "v16.3.8-b0fad0d4/00000001.sst").stat().st_size == 1_048_576
    assert re.search(r"; cache [12]M within cap 2048M, kept; .* answered 307 after", result.stdout)


def test_a_unit_stopped_on_purpose_stays_stopped_and_its_cache_is_still_capped(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path, 3)
    result, calls = _run(tmp_path, cache, 1, state="inactive")
    assert result.returncode == 0, result.stderr
    assert calls == []  # no stop, no start, no probe
    assert not cache.exists()
    assert _leftovers(cache) == []
    assert re.fullmatch(
        rf"acdev-dev-restart: {UNIT} was stopped on purpose and stays stopped; "
        r"cache [34]M above cap 1M, cleared\n",
        result.stdout,
    )
    assert not (tmp_path / "watchdog").exists()


def test_a_failed_unit_is_started(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, _cache(tmp_path, 1), 2048, state="failed")
    assert result.returncode == 0, result.stderr
    assert calls[:2] == [f"stop {UNIT}", f"start {UNIT} cache=present"]


def test_a_missing_cache_counts_as_empty(tmp_path: Path) -> None:
    cache = tmp_path / "app/.next/dev/cache/turbopack"
    result, calls = _run(tmp_path, cache, 2048)
    assert result.returncode == 0, result.stderr
    assert f"start {UNIT} cache=absent" in calls
    assert "; cache 0M within cap 2048M, kept;" in result.stdout


def test_old_copies_from_an_interrupted_run_are_deleted(tmp_path: Path) -> None:
    cache = _cache(tmp_path, 1)
    (cache.parent / "turbopack.old-1792500000/v16.3.8-b0fad0d4").mkdir(parents=True)
    result, _ = _run(tmp_path, cache, 2048)
    assert result.returncode == 0, result.stderr
    assert _leftovers(cache) == []
    assert cache.exists()


def test_the_wait_for_the_first_compile_gives_up_after_its_tries(tmp_path: Path) -> None:
    cache = _cache(tmp_path, 3)
    result, calls = _run(tmp_path, cache, 1, codes=("000", "502", "504", "200"))
    assert result.returncode == 0, result.stderr
    assert [line for line in calls if line.startswith(("curl", "sleep"))] == [
        line for _ in range(3) for line in (calls[2], "sleep 5")
    ]
    assert f"; {URL} answered 504 after" in result.stdout
    assert _leftovers(cache) == []  # deleted all the same


def test_a_failed_start_exits_1_and_still_deletes_the_old_cache(tmp_path: Path) -> None:
    cache = _cache(tmp_path, 3)
    result, calls = _run(tmp_path, cache, 1, start_ok=False)
    assert result.returncode == 1
    assert not [line for line in calls if line.startswith("curl")]
    assert "cleared; start failed; memory 512M" in result.stdout
    assert _leftovers(cache) == []


def test_without_a_probe_url_it_only_restarts(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, _cache(tmp_path, 1), 2048, extra=())
    assert result.returncode == 0, result.stderr
    assert calls == [f"stop {UNIT}", f"start {UNIT} cache=present"]
    assert re.search(r"within cap 2048M, kept; memory 512M\n$", result.stdout)


def test_only_a_turbopack_cache_directory_is_ever_moved_or_deleted(tmp_path: Path) -> None:
    other = tmp_path / "src"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    link = tmp_path / "app/.next/dev/cache/turbopack"
    link.parent.mkdir(parents=True)
    link.symlink_to(other)
    for bad in (
        other,
        tmp_path / "app/.next/dev/cache",
        Path("app/.next/dev/cache/turbopack"),
        tmp_path / "app/.next/dev/cache/../cache/turbopack",
        link,
    ):
        result, calls = _run(tmp_path, bad, 0)
        assert result.returncode == 2, bad
        assert calls == [], bad
    good = str(tmp_path / "a/.next/dev/cache/turbopack")
    for bad_args in (("x",), ("1", URL, HOST, "extra"), ("lots",), ("1", "ftp://x")):
        result = subprocess.run(  # noqa: S603
            ["bash", str(SCRIPT), UNIT, good, *bad_args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 2, bad_args
    assert (other / "keep.txt").read_text() == "keep"
    assert link.is_symlink()


def _directives(path: Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key: value for key, value in pairs if not key.startswith("#")}


def test_the_sales_xray_restart_unit_names_its_own_cache_cap_and_the_watchdog_probe() -> None:
    service = _directives(XRAY / "acdev-xray-dev-restart.service")
    workdir = _directives(XRAY / "acdev-xray-dev.service.d/zz-dev-live.conf")["WorkingDirectory"]
    probe = _directives(DEV / "acdev-dev-watchdog/acdev-xray-dev.env")
    assert service["ExecStart"].split() == [
        "%h/.local/bin/acdev-dev-restart",
        UNIT,
        f"{workdir}/apps/sales-xray-web/.next/dev/cache/turbopack",
        "2048",
        probe["PROBE_URL"],
        probe["PROBE_HOST"],
    ]
    assert probe["PROBE_URL"] == URL
    assert probe["PROBE_HOST"] == HOST
    assert (service["Type"], service["IOSchedulingClass"]) == ("oneshot", "idle")
    timer = _directives(XRAY / "acdev-xray-dev-restart.timer")
    assert timer["OnCalendar"] == "*-*-* 22:30:00 UTC"  # 04:00 IST
    assert timer["Persistent"] == "false"


def test_the_recorded_dev_server_unit_serves_the_probe_port_within_its_memory_bounds() -> None:
    unit = _directives(XRAY / UNIT)
    assert "--hostname 127.0.0.1 --port 3026" in unit["ExecStart"]
    memory = _directives(XRAY / "acdev-xray-dev.service.d/80-memory.conf")
    # 11 Oct: MemoryHigh 1700M throttled next dev into Cloudflare 524s; keep 3G or more.
    assert (memory["MemoryHigh"], memory["MemoryMax"], memory["MemorySwapMax"]) == (
        "3G",
        "3584M",
        "512M",
    )
    assert _directives(XRAY / "acdev-xray-dev.service.d/50-CPUQuota.conf")["CPUQuota"] == "75%"
    assert sorted(path.name for path in (XRAY / "acdev-xray-dev.service.d").iterdir()) == [
        "30-asset-version.conf",
        "50-CPUQuota.conf",
        "80-memory.conf",
        "85-api-origin.conf",
        "zz-dev-live.conf",
    ]
