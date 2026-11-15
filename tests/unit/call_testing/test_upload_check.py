"""The upload check reads the Play app's New analysis screen the way it really is (Redmi 13,
15 Nov 2026): the Terms box is an unlabelled CheckBox beside its "I agree to the" text, the page
sits under a header and above a tab bar, and off-screen controls report zero height
(scripts/call_testing/upload_check.py)."""

import importlib.util
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


class _Reads:
    """A screen whose accessibility tree lags: it reads "unchecked" ``stale`` times first."""

    def __init__(self, stale: int, ticks: bool = True) -> None:
        self.stale, self.ticks, self.reads = stale, ticks, 0

    def full(self):  # type: ignore[no-untyped-def]
        self.reads += 1
        checked = self.ticks and self.reads > self.stale
        return upload.parse_full(
            _screen(
                "[154,888][211,945]", "[238,885][481,954]", "[148,1040][931,1177]", checked=checked
            )
        )


def _clock():  # type: ignore[no-untyped-def]
    now = [0.0]
    return now, (lambda: now[0]), (lambda seconds: now.__setitem__(0, now[0] + seconds))


def test_a_lagging_tree_is_waited_out_never_tapped_again() -> None:
    # 15 Nov 2026: a second tap on a stale "unchecked" read unticked the box again.
    screen = _Reads(stale=3)
    _, clock, sleep = _clock()
    found = upload.tick_seen(screen, seconds=8, sleep=sleep, clock=clock)
    assert found is not None and found[0]["checked"] is True
    assert screen.reads == 4


def test_a_box_that_never_ticks_is_given_up_after_the_wait() -> None:
    screen = _Reads(stale=0, ticks=False)
    now, clock, sleep = _clock()
    found = upload.tick_seen(screen, seconds=8, sleep=sleep, clock=clock)
    assert found is not None and found[0]["checked"] is False
    assert now[0] >= 8


def test_the_terms_box_is_tapped_once() -> None:
    source = (ROOT / "scripts/call_testing/upload_check.py").read_text("utf-8")
    agree = source[source.index("def agree()") : source.index('step("tick the Terms"')]
    assert agree.count("input tap") == 1
    assert "for _ in range" not in agree
