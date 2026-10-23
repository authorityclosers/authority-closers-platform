#!/usr/bin/env python3
"""Google Play listing art for Sales X-Ray, from real screens on the dev review fixtures.

    play_listing.py stills   screenshots of the screens below (phone 3x, computer 2x)
    play_listing.py art      phone and tablet screenshots, feature graphic and 512 px icon
    play_listing.py all      both

Outputs go to $SXTUT_OUT/play/ (default ~/sx-tutorials/play). Re-run after a UI change; only
Chromium on ac is used. `--icon <png|svg>` gives the launcher artwork for the 512 px store icon.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from sxtut import render  # noqa: E402

OUT = Path(os.environ.get("SXTUT_OUT") or str(Path.home() / "sx-tutorials")) / "play"
REPORT = "/review-fixture/report/story?example=coach&clean=1"
GOT_IT = {"do": "tap", "target": {"role": "button", "name": "Got it"}, "ms": 400, "optional": True}

# Screens, in Play order for the phone set (the first ones show in search results).
PHONE = [
    (
        "report-score",
        "BRAIN 4.0",
        "An AI coaching score on every call",
        [
            {"do": "goto", "url": REPORT},
            {
                "do": "scrollto",
                "target": {"text": "2. AI Coaching Score"},
                "offset": 128,
                "parent": True,
                "ms": 700,
            },
        ],
    ),
    (
        "leads",
        "LEADS",
        "Every lead to call today, late ones first",
        [{"do": "goto", "url": "/review-fixture/leads"}, GOT_IT],
    ),
    (
        "lead-call",
        "ONE TAP",
        "Call, WhatsApp or SMS your lead",
        [
            {"do": "goto", "url": "/review-fixture/leads"},
            GOT_IT,
            {"do": "tap", "target": {"role": "button", "name": "Open Asha Fictional"}, "ms": 1400},
        ],
    ),
    (
        "start-calling",
        "START CALLING",
        "Next lead and your opener, ready",
        [{"do": "goto", "url": "/review-fixture/cold-calling"}],
    ),
    (
        "coaching",
        "COACHING",
        "Your strength and the one thing to fix",
        [
            {"do": "goto", "url": REPORT},
            {
                "do": "scrollto",
                "target": {"text": "Biggest Strength"},
                "offset": 112,
                "parent": True,
                "ms": 700,
            },
        ],
    ),
    ("home", "HOME", "Your sales, at a glance", [{"do": "goto", "url": "/review-fixture/home"}]),
    (
        "chats",
        "CHATS",
        "WhatsApp, Messenger and Instagram in one inbox",
        [{"do": "goto", "url": "/review-fixture/chats"}],
    ),
    (
        "team",
        "TEAM",
        "Bring your whole team in",
        [{"do": "goto", "url": "/review-fixture/settings?section=team"}],
    ),
]
TABLET = [
    ("desk-home", "Your whole team at a glance", [{"do": "goto", "url": "/review-fixture/home"}]),
    (
        "desk-leads",
        "All your leads in one table",
        [
            {"do": "goto", "url": "/review-fixture/leads?tab=all&pipelines=2"},
            {"do": "tap", "target": {"text": "Table", "exact": True}, "ms": 900, "optional": True},
        ],
    ),
    (
        "desk-report",
        "A clear Report for every call",
        [
            {"do": "goto", "url": REPORT},
            {
                "do": "scrollto",
                "target": {"text": "Rated by AI on", "exact": False},
                "offset": 260,
                "ms": 700,
            },
        ],
    ),
    (
        "desk-organisation",
        "Your team and your company domain",
        [{"do": "goto", "url": "/review-fixture/settings?section=organisation"}],
    ),
]
INK, TEAL, TEAL2 = render.INK, render.TEAL, render.TEAL2
css = render._css  # style="" text from keyword arguments, as the tutorial stage cards use


def node(*args: str) -> None:
    render.wait_for_headroom()
    cmd = [*render.NICE, "node", str(HERE / "capture.mjs"), *args]
    subprocess.run(cmd, check=True, cwd=REPO, env=render.safe_env(), stdin=subprocess.DEVNULL)  # noqa: S603


def cmd_stills(_: argparse.Namespace) -> None:
    frost = {"do": "frost"}
    spec = [{"name": n, "device": "phone", "setup": [*s, frost]} for n, _k, _h, s in PHONE]
    spec += [{"name": n, "device": "desktop", "setup": [*s, frost]} for n, _h, s in TABLET]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stills.json").write_text(json.dumps(spec), encoding="utf-8")
    node("stills", str(OUT / "stills.json"), str(OUT / "stills"))


def data_uri(path: Path) -> str:
    kind = "svg+xml" if path.suffix == ".svg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def page(font_css: str, w: int, h: int, body: str) -> str:
    css = (
        "*{box-sizing:border-box;margin:0;padding:0}"
        f"html,body{{width:{w}px;height:{h}px;overflow:hidden;"
        "font-family:'SXBrand','Plus Jakarta Sans','DejaVu Sans',sans-serif;"
        "-webkit-font-smoothing:antialiased}"
    )
    head = f'<meta charset="utf-8"><style>{font_css}{css}</style>'
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def div(style: str, inner: str = "") -> str:
    return f"<div style='{style}'>{inner}</div>"


def img(src: Path, style: str) -> str:
    return f"<img src='{data_uri(src)}' style='{style}'>"


def framed(
    shot: Path, left: int, top: int, width: int, bezel: int, radius: int, extra: str = ""
) -> str:
    """A phone screenshot in a dark bezel."""
    height = round(width * 2532 / 1170)
    frame = css(
        position="absolute",
        left=left,
        top=top,
        width=width + 2 * bezel,
        height=height + 2 * bezel,
        border_radius=radius + bezel,
        background="#111827",
        padding=bezel,
        box_shadow="0 40px 90px rgba(15,23,42,.30),0 10px 30px rgba(15,23,42,.18)",
    )
    screen = css(display="block", width=width, height=height, border_radius=radius)
    return div(frame + extra, img(shot, screen))


GROUND = (
    "radial-gradient(900px 700px at 90% 8%,rgba(14,116,144,.20),transparent 70%),"
    "radial-gradient(800px 800px at 0% 100%,rgba(15,118,110,.16),transparent 70%),"
    "linear-gradient(160deg,#f6fbfa,#e8f3f1)"
)


FULL = css(position="absolute", inset=0)


def phone_html(font_css: str, shot: Path, kicker: str, headline: str) -> str:
    w, h, pw, bezel = 1080, 1920, 720, 18
    top = css(position="absolute", left=90, right=90, top=120, text_align="center")
    kick = css(font_weight=800, font_size=30, letter_spacing=".12em", color=TEAL)
    big = css(
        margin_top=22,
        font_weight=800,
        font_size=68,
        line_height="1.1",
        letter_spacing="-.03em",
        color=INK,
    )
    body = (
        div(f"{FULL};background:{GROUND}")
        + div(top, div(kick, escape(kicker)) + div(big, escape(headline)))
        + framed(shot, (w - pw) // 2 - bezel, 430, pw, bezel, 64)
    )
    return page(font_css, w, h, body)


def tablet_html(font_css: str, shot: Path, headline: str) -> str:
    w, h, sw = 1920, 1080, 1500
    sh = round(sw * 1800 / 2880)
    title = css(
        position="absolute",
        left=0,
        right=0,
        top=56,
        text_align="center",
        font_weight=800,
        font_size=58,
        letter_spacing="-.03em",
        color=INK,
    )
    window = css(
        position="absolute",
        left=(w - sw) // 2,
        top=170,
        width=sw,
        height=sh,
        border_radius=22,
        overflow="hidden",
        border="2px solid rgba(15,23,42,.12)",
        box_shadow="0 40px 90px rgba(15,23,42,.25)",
    )
    body = (
        div(f"{FULL};background:{GROUND}")
        + div(title, escape(headline))
        + div(window, img(shot, css(display="block", width=sw, height=sh)))
    )
    return page(font_css, w, h, body)


def feature_html(font_css: str, shot: Path, icon: Path | None) -> str:
    w, h, pw, bezel = 1024, 500, 250, 8
    ground = (
        "radial-gradient(700px 400px at 85% 0%,rgba(255,255,255,.18),transparent 60%),"
        f"linear-gradient(135deg,{TEAL},{TEAL2} 60%,#155e75)"
    )
    mark = ""
    if icon:
        mark = img(icon, css(width=64, height=64, border_radius=16, margin_right=16))
    brand = css(display="flex", align_items="center", font_weight=800, font_size=30)
    big = css(margin_top=34, font_weight=800, font_size=54, line_height="1.08")
    sub = css(margin_top=22, font_weight=600, font_size=22, line_height="1.4", opacity=".92")
    text = div(
        css(position="absolute", left=64, top=70, width=560, color="#fff"),
        div(brand, mark + "Sales X-Ray")
        + div(big + ";letter-spacing:-.03em", "Every sales call, coached by AI")
        + div(sub, "Calls, leads and Brain 4.0 coaching in one app"),
    )
    phone = framed(shot, w - pw - 110, 56, pw, bezel, 30, ";transform:rotate(-4deg)")
    return page(font_css, w, h, div(f"{FULL};background:{ground}") + text + phone)


def icon_html(icon: Path) -> str:
    return page("", 512, 512, img(icon, css(display="block", width=512, height=512)))


def cmd_art(args: argparse.Namespace) -> None:
    font_css = render.brand_font_css(REPO)
    st = OUT / "stills"
    icon = Path(args.icon) if args.icon else None
    cards = []
    for i, (name, kicker, headline, _s) in enumerate(PHONE, 1):
        cards.append(
            {
                "name": f"phone/{i:02d}-{name}",
                "width": 1080,
                "height": 1920,
                "html": phone_html(font_css, st / f"{name}.png", kicker, headline),
            }
        )
    for i, (name, headline, _s) in enumerate(TABLET, 1):
        html = tablet_html(font_css, st / f"{name}.png", headline)
        cards.append(
            {"name": f"tablet-7in/{i:02d}-{name}", "width": 1920, "height": 1080, "html": html}
        )
        cards.append(
            {
                "name": f"tablet-10in/{i:02d}-{name}",
                "width": 1920,
                "height": 1080,
                "scale": 4 / 3,
                "html": html,
            }
        )
    cards.append(
        {
            "name": "feature-graphic-1024x500",
            "width": 1024,
            "height": 500,
            "jpeg": True,
            "html": feature_html(font_css, st / "report-score.png", icon),
        }
    )
    if icon:
        cards.append({"name": "icon-512", "width": 512, "height": 512, "html": icon_html(icon)})
    for sub in ("phone", "tablet-7in", "tablet-10in"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    (OUT / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    node("cards", str(OUT / "cards.json"), str(OUT))
    (OUT / "cards.json").unlink()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("step", choices=["stills", "art", "all"])
    p.add_argument("--icon", help="launcher icon artwork (PNG or SVG) for the 512 px store icon")
    a = p.parse_args()
    if a.step in ("stills", "all"):
        cmd_stills(a)
    if a.step in ("art", "all"):
        cmd_art(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
