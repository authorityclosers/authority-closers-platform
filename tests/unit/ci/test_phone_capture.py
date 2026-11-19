"""scripts/phone_capture.py: the facts come off the phone, the build is never typed in."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "phone_capture.py"
spec = importlib.util.spec_from_file_location("phone_capture", SCRIPT)
assert spec is not None and spec.loader is not None
phone_capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone_capture)

APP = "com.authorityclosers.salesxray"
PACKAGES = f"package:{APP}\npackage:{APP}.staging\npackage:com.other.app\n"
DUMP = (
    f"Packages:\n  Package [{APP}] (abc):\n"
    "    versionCode=10084 minSdk=26 targetSdk=35\n    versionName=1.0.84\n"
)
FOCUS = f"  mCurrentFocus=Window{{4f2a u0 {APP}/{APP}.MainActivity}}\n"
XML = (
    '<hierarchy><node text="Help &amp; support"/>'
    '<node text="Build 3b08990 &#183; App 1.0.84"/></hierarchy>'
)


class FakePhone:
    """An adb that answers from a table of canned replies, by the words of the command."""

    def __init__(self, xml: str = XML) -> None:
        self.xml = xml
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], timeout: float = 60) -> bytes:
        self.calls.append(args)
        words = " ".join(args)
        if "get-state" in words:
            return b"device\n"
        if "pm list packages" in words:
            return PACKAGES.encode()
        if "dumpsys window" in words:
            return FOCUS.encode()
        if "dumpsys package" in words:
            return DUMP.encode()
        if "getprop ro.product.model" in words:
            return b"Redmi Note 8 Pro\n"
        if "getprop ro.product.manufacturer" in words:
            return b"Xiaomi\n"
        if "getprop ro.build.version.release" in words:
            return b"11\n"
        if "getprop ro.build.version.sdk" in words:
            return b"30\n"
        if "wm size" in words:
            return b"Physical size: 1080x2340\n"
        if "exec-out cat" in words:
            return self.xml.encode()
        if "screencap" in words:
            return b"\x89PNG-fake"
        if " pull " in words:
            Path(args[-1]).write_bytes(b"mp4-fake")
        return b""


def test_parsers() -> None:
    assert phone_capture.parse_installed(PACKAGES) == [
        "com.authorityclosers.salesxray",
        "com.authorityclosers.salesxray.staging",
    ]
    assert phone_capture.parse_package_dump(DUMP) == {
        "versionName": "1.0.84",
        "versionCode": "10084",
    }
    assert phone_capture.parse_package_dump("nothing") == {"versionName": None, "versionCode": None}
    assert phone_capture.parse_focus(FOCUS) == "com.authorityclosers.salesxray"
    assert phone_capture.find_build_line(XML) == "Build 3b08990 · App 1.0.84"
    assert phone_capture.find_build_line('<node text="Build dev"/>') == "Build dev"
    assert phone_capture.find_build_line('<node text="Builder"/>') is None


@pytest.mark.parametrize("label", ["3b08990", "3b08990ab12cd34", "A" * 62, "", "has space", "-x"])
def test_bad_labels_are_refused(label: str) -> None:
    with pytest.raises(ValueError):
        phone_capture.check_label(label)


def test_screenshot_writes_media_and_json_beside_it(tmp_path: Path) -> None:
    code = phone_capture.main(["SER123", "home-after-fix", "--out", str(tmp_path)], run=FakePhone())
    assert code == 0
    (png,) = tmp_path.glob("*.png")
    (proof,) = tmp_path.glob("*.json")
    assert png.stem == proof.stem and png.stem.startswith("home-after-fix-")
    data = json.loads(proof.read_text("utf-8"))
    assert data["serial"] == "SER123"
    assert data["model"] == "Redmi Note 8 Pro"
    assert data["kind"] == "screenshot"
    assert data["app"] == {
        "package": "com.authorityclosers.salesxray",
        "versionName": "1.0.84",
        "versionCode": "10084",
    }
    assert data["web_build"] == "Build 3b08990 · App 1.0.84"
    assert data["utc"].endswith("Z")
    assert data["media"] == png.name
    assert len(data["media_sha256"]) == 64


def test_recording_pulls_the_file_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phone_capture.time, "sleep", lambda _s: None)
    fake = FakePhone()
    code = phone_capture.main(
        ["SER123", "scroll", "--record", "5", "--out", str(tmp_path)], run=fake
    )
    assert code == 0
    (mp4,) = tmp_path.glob("*.mp4")
    assert mp4.read_bytes() == b"mp4-fake"
    assert json.loads(next(tmp_path.glob("*.json")).read_text("utf-8"))["seconds"] == 5
    assert any("screenrecord" in " ".join(call) and "--time-limit" in call for call in fake.calls)
    assert any(call[-3:-1] == ["rm", "-f"] for call in fake.calls)


def test_no_build_line_on_screen_is_said_not_guessed(tmp_path: Path) -> None:
    code = phone_capture.main(
        ["S", "x", "--out", str(tmp_path)], run=FakePhone('<node text="Home"/>')
    )
    assert code == 0
    data = json.loads(next(tmp_path.glob("*.json")).read_text("utf-8"))
    assert data["web_build"] is None
    assert "no build line" in data["web_build_note"]


def test_a_commit_as_label_or_a_bad_length_exits_without_touching_the_phone(tmp_path: Path) -> None:
    fake = FakePhone()
    assert phone_capture.main(["S", "3b08990", "--out", str(tmp_path)], run=fake) == 2
    assert phone_capture.main(["S", "ok", "--record", "2", "--out", str(tmp_path)], run=fake) == 2
    assert phone_capture.main(["S", "ok", "--record", "181", "--out", str(tmp_path)], run=fake) == 2
    assert fake.calls == []
    assert not list(tmp_path.iterdir())


def test_the_script_has_no_option_for_a_build_or_commit() -> None:
    source = SCRIPT.read_text("utf-8")
    assert "--sha" not in source
    assert "--build" not in source
    assert "--commit" not in source
