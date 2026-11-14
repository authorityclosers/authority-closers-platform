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
