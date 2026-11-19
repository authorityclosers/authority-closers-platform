"""scripts/phone_smoke.py: it only looks, and stops unless the phone is in the QA TEST workspace."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "phone_smoke.py"
spec = importlib.util.spec_from_file_location("phone_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
phone_smoke = importlib.util.module_from_spec(spec)
sys.modules["phone_smoke"] = phone_smoke
spec.loader.exec_module(phone_smoke)

PACKAGE = "com.authorityclosers.salesxray"
BAR = (
    '<node text="Home" bounds="[0,2200][216,2340]"/>'
    '<node text="Leads" bounds="[216,2200][432,2340]"/>'
    '<node text="Calls" bounds="[432,2200][648,2340]"/>'
)


def screen(*words: str, bar: bool = True) -> str:
    body = "".join(
        f'<node text="{w}" bounds="[40,{200 + 80 * i}][1040,{260 + 80 * i}]"/>'
        for i, w in enumerate(words)
    )
    return f"<hierarchy>{body}{BAR if bar else ''}</hierarchy>"


HOME = screen("T· TEST · SAHYADRI HOMES", "Good morning", "4 leads to call", "Today")


class FakePhone:
    """An adb that answers from canned replies and records every command."""

    def __init__(self, xml: str = HOME, focus: str = PACKAGE) -> None:
        self.xml = xml
        self.focus = focus
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], timeout: float = 60) -> bytes:
        self.calls.append(args)
        words = " ".join(args)
        if "get-state" in words:
            return b"device\n"
        if "dumpsys window" in words:
            focus = f"{self.focus}/{self.focus}.MainActivity"
            return f"  mCurrentFocus=Window{{4f2a u0 {focus}}}\n".encode()
        if "dumpsys package" in words:
            return (
                f"Packages:\n  Package [{PACKAGE}] (abc):\n"
                "    versionCode=10099 minSdk=26\n    versionName=1.0.99\n"
            ).encode()
        if "pm list packages" in words:
            return f"package:{PACKAGE}\n".encode()
        if "wm size" in words:
            return b"Physical size: 1080x2340\n"
        if " cat " in words:
            return self.xml.encode()
        if "screencap" in words:
            return b"\x89PNG-fake"
        return b""

    def taps(self) -> list[list[str]]:
        return [call for call in self.calls if "input" in call and "tap" in call]


def run(fake: FakePhone, tmp_path: Path, monkeypatch) -> tuple[int, dict]:
    monkeypatch.setattr(phone_smoke.phone_capture, "find_adb", lambda: "adb")
    monkeypatch.setattr(phone_smoke.time, "sleep", lambda _s: None)
    code = phone_smoke.main(["7505cec", "--out", str(tmp_path)], run=fake)
    return code, json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))


def test_nodes_and_bar_items() -> None:
    found = phone_smoke.nodes(HOME)
    assert [n["text"] for n in phone_smoke.bar_items(found, 2340)] == ["Home", "Leads", "Calls"]
    # A "Leads" heading up the page is not the bar's item.
    top = phone_smoke.nodes('<node text="Leads" bounds="[0,100][200,160]"/>')
    assert phone_smoke.bar_items(top, 2340) == []


def test_verdict_reads_what_a_person_would_see() -> None:
    fine = phone_smoke.nodes(HOME)
    assert phone_smoke.verdict(fine) is None
    assert phone_smoke.verdict(fine[:2]) == "a blank screen"
    assert (
        phone_smoke.verdict(phone_smoke.nodes(screen("A", "B", "Owner: undefined", "C")))
        == "junk on screen"
    )
    assert (
        phone_smoke.verdict(phone_smoke.nodes(screen("A", "B", "Something went wrong", "C")))
        == "an error page"
    )


def test_green_run_presses_only_the_bottom_bar(tmp_path: Path, monkeypatch) -> None:
    fake = FakePhone()
    code, result = run(fake, tmp_path, monkeypatch)
    assert code == 0
    assert [s["name"] for s in result["screens"]] == ["Home", "Leads", "Calls"]
    assert result["ok"] is True
    # Three taps, each in the bottom bar (y of its items), and nothing typed, swiped or dialled.
    assert [tap[-1] for tap in fake.taps()] == ["2270", "2270", "2270"]
    joined = [" ".join(call) for call in fake.calls]
    assert not any("input text" in c or "swipe" in c or "tel:" in c or "CALL" in c for c in joined)
    assert (tmp_path / "home.png").exists()


def test_signed_out_stops_with_its_own_code(tmp_path: Path, monkeypatch) -> None:
    fake = FakePhone(
        xml=screen("Sales X-Ray", "Continue with Google", "Terms", "Privacy", bar=False)
    )
    code, result = run(fake, tmp_path, monkeypatch)
    assert code == phone_smoke.EXIT_SIGNED_OUT
    assert "not signed in" in result["note"]
    assert fake.taps() == []


def test_a_real_workspace_is_never_touched(tmp_path: Path, monkeypatch) -> None:
    fake = FakePhone(xml=screen("A· AUTHORITY CLOSERS", "Good morning", "4 leads to call", "Today"))
    code, result = run(fake, tmp_path, monkeypatch)
    assert code == phone_smoke.EXIT_NOT_TEST
    assert "never test as a real seller" in result["note"]
    assert fake.taps() == []


def test_the_live_design_app_in_front_means_busy(tmp_path: Path, monkeypatch) -> None:
    fake = FakePhone(focus=phone_smoke.LIVE_APP)
    code, result = run(fake, tmp_path, monkeypatch)
    assert code == phone_smoke.EXIT_BUSY
    assert not any("force-stop" in call for call in fake.calls)
    assert fake.taps() == []


def test_a_failed_screen_fails_the_smoke(tmp_path: Path, monkeypatch) -> None:
    fake = FakePhone(
        xml=screen("T· TEST · SAHYADRI HOMES", "Good morning", "Due in NaN days", "Today")
    )
    code, result = run(fake, tmp_path, monkeypatch)
    assert code == phone_smoke.EXIT_FAILED
    assert result["screens"][0]["note"] == "junk on screen"
