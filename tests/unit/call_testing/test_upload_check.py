"""The upload check reads the Play app's New analysis screen the way it really is (Redmi 13,
15 Nov 2026): the Terms box is an unlabelled CheckBox beside its "I agree to the" text, the page
sits under a header and above a tab bar, and off-screen controls report zero height
(scripts/call_testing/upload_check.py)."""

import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):  # type: ignore[no-untyped-def]
    key = f"call_testing_{name}"
    found = importlib.util.spec_from_file_location(
        key, ROOT / "scripts/call_testing" / f"{name}.py"
    )
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[key] = module
    found.loader.exec_module(module)
    return module


upload = _load("upload_check")


def _node(cls: str, bounds: str, text: str = "", checked: bool = False) -> str:
    return (
        f'<node index="0" text="{text}" resource-id="" class="android.widget.{cls}" '
        f'package="com.authorityclosers.salesxray" content-desc="" checkable="false" '
        f'checked="{str(checked).lower()}" clickable="true" bounds="{bounds}" />'
    )


def _screen(box: str, label: str, button: str, checked: bool = False) -> str:
    return (
        "<hierarchy>"
        + "".join(
            (
                _node("View", "[92,775][368,852]", "1 file added"),
                _node("CheckBox", box, checked=checked),
                _node("TextView", label, "I agree to the"),
                _node("Button", button, "Analyse my call"),
            )
        )
        + "</hierarchy>"
    )


def test_off_screen_controls_are_not_ready() -> None:
    # Below the screen: uiautomator reports them at the bottom edge with no height.
    nodes = upload.parse_full(
        _screen("[154,2047][211,2047]", "[238,2047][553,2047]", "[148,2047][913,2047]")
    )
    assert upload.terms_controls(nodes) is None
    # The checkbox shows, but the button is still under the tab bar.
    nodes = upload.parse_full(
        _screen("[154,1795][211,1852]", "[238,1795][553,1861]", "[148,1950][913,2047]")
    )
    assert upload.terms_controls(nodes) is None


def test_the_unlabelled_checkbox_and_the_button_are_found_once_on_screen() -> None:
    nodes = upload.parse_full(
        _screen("[154,1153][211,1209]", "[238,1150][553,1218]", "[148,1305][913,1441]")
    )
    found = upload.terms_controls(nodes)
    assert found is not None
    box, button = found
    assert (box["x"], box["y"], box["label"], box["checked"]) == (182, 1181, "", False)
    assert (button["x"], button["y"]) == (530, 1373)
    ticked = upload.parse_full(
        _screen(
            "[154,1153][211,1209]", "[238,1150][553,1218]", "[148,1305][913,1441]", checked=True
        )
    )
    assert upload.terms_controls(ticked)[0]["checked"] is True


def test_labelled_nodes_keep_their_centres() -> None:
    nodes = upload.parse_nodes(
        _screen("[154,1153][211,1209]", "[238,1150][553,1218]", "[148,1305][913,1441]")
    )
    assert (230, 813, "1 file added") in nodes
    assert all(label for _, _, label in nodes)  # the unlabelled checkbox isn't listed
    assert upload.HEADER_BOTTOM < 400 < upload.SAFE_BOTTOM


def _raw(
    width: int, height: int, teal: tuple[int, int, int, int] | None, header: int = 16
) -> bytes:
    """An Android raw screencap: white, with a teal square where a ticked box is drawn."""
    pixels = bytearray(b"\xff\xff\xff\xff" * width * height)
    if teal:
        x0, y0, x1, y1 = teal
        for y in range(y0, y1):
            for x in range(x0, x1):
                at = (y * width + x) * 4
                pixels[at : at + 4] = bytes((0, 125, 121, 255))
    head = struct.pack("<III", width, height, 1) + (b"\0\0\0\0" if header == 16 else b"")
    return head + bytes(pixels)


# The box as uiautomator reported it on 15 Nov 2026: 888-945, drawn at 867-916.
BOX = {"x": 182, "y": 916, "top": 888, "bottom": 945}


def test_a_ticked_box_is_seen_in_the_pixels_not_uiautomator() -> None:
    ticked = _raw(300, 1100, (156, 867, 207, 916))
    assert upload.box_ticked(ticked, BOX) is True
    assert upload.box_ticked(_raw(300, 1100, (156, 867, 207, 916), header=12), BOX) is True
    assert upload.box_ticked(_raw(300, 1100, None), BOX) is False
    # Teal elsewhere (the + button, the steps below) doesn't count.
    assert upload.box_ticked(_raw(300, 1100, (20, 100, 120, 200)), BOX) is False


def test_a_screen_that_shows_the_tick_late_is_waited_out_never_tapped_again() -> None:
    frames = [_raw(300, 1100, None)] * 3 + [_raw(300, 1100, (156, 867, 207, 916))]
    taken = []

    def capture() -> bytes:
        taken.append(1)
        return frames[min(len(taken) - 1, len(frames) - 1)]

    now = [0.0]
    shown = upload.tick_shown(
        capture,
        BOX,
        seconds=8,
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert shown is True and len(taken) == 4


def test_a_box_that_never_ticks_is_given_up_after_the_wait() -> None:
    now = [0.0]
    shown = upload.tick_shown(
        lambda: _raw(300, 1100, None),
        BOX,
        seconds=8,
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert shown is False and now[0] >= 8


def test_the_terms_box_is_tapped_once() -> None:
    source = (ROOT / "scripts/call_testing/upload_check.py").read_text("utf-8")
    agree = source[source.index("def agree()") : source.index('step("tick the Terms"')]
    assert agree.count("input tap") == 1
    assert "for _ in range" not in agree
