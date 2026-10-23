#!/usr/bin/env python3
"""Google Play listing art for Sales X-Ray, from real screens on the dev review fixtures.

    play_listing.py stills --theme light|dark   screenshots of the screens below
    play_listing.py art --theme light|dark      phone and tablet shots, feature graphic, icon
    play_listing.py all --theme light|dark      both
    play_listing.py captures --theme light|dark clean key screens, phone/tablet/computer, no styling

Bold store style: brand gradient (teal to navy), a short white headline, the real screen in one
device frame, and one glowing element per shot. Demo names are swapped for realistic made-up ones
(store art only; the fixtures keep theirs). Outputs go to $SXTUT_OUT/play/<theme>/ (default
~/sx-tutorials/play). `--icon <png|svg>` gives the launcher artwork for the 512 px store icon.
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
TEAL, NAVY, INK = "#2DD4BF", "#0B1220", render.INK
css = render._css  # style="" text from keyword arguments, as the tutorial stage cards use

# Made-up people and company for store art (no customers): the fixtures' names stay as they are.
NAMES = {
    "Fictional Homes": "Skyline Realty",
    "fictionalhomes.in": "skylinerealty.in",
    "Sample Realty": "Harbour Homes",
    "Sample Digital Studio": "Brightline Digital",
    "Asha Fictional": "Asha Kulkarni",
    "Ravi Sample": "Ravi Deshmukh",
    "Meera Fictional": "Meera Joshi",
    "Neha Fictional": "Neha Patil",
    "Karan Example": "Karan Mehta",
    "Sample Buyer": "Sanjay Bhosale",
    "Swamini Fictional": "Swamini Gokhale",
    "Rahul Example": "Rahul Kadam",
    "Priya Sample": "Priya Nair",
    "Vikram Example": "Vikram Shinde",
    "Anil Example": "Anil Pawar",
    "AF": "AK",
    "RS": "RD",
    "MF": "MJ",
    "NF": "NP",
    "KE": "KM",
    "SF": "SG",
    "RE": "RK",
    "PS": "PN",
    "VE": "VS",
    "FH": "SR",
}
GOT_IT = {"do": "tap", "target": {"role": "button", "name": "Got it"}, "ms": 400, "optional": True}
JARGON = [
    {"do": "hide", "target": {"text": "18 sales skills in 3 areas"}, "collapse": True},
    {"do": "hide", "target": {"text": "Rated by AI on the coaching lead"}, "collapse": True},
]


def glow(target: dict, up: int = 0, card: bool = False) -> dict:
    return {"do": "glow", "target": target, "up": up, "card": card, "optional": True}


# (name, kicker, headline, setup before the swap, glow) in Play order.
PHONE = [
    (
        "report-score",
        "BRAIN 4.0",
        "Every call, scored by AI",
        [
            {"do": "goto", "url": REPORT},
            {"do": "tap", "target": {"text": "Coaching score", "exact": True}, "ms": 1500},
            *JARGON,
        ],
        glow({"text": "Starting the Call", "exact": True}, card=True),
    ),
    (
        "start-calling",
        "START CALLING",
        "Next lead, opener ready",
        [{"do": "goto", "url": "/review-fixture/cold-calling"}],
        glow({"role": "button", "name": "Call Priya"}),
    ),
    (
        "leads",
        "LEADS",
        "Your day's calls, sorted",
        [{"do": "goto", "url": "/review-fixture/leads"}, GOT_IT],
        glow({"role": "tab", "name": "To call"}),
    ),
    (
        "after-call",
        "AFTER THE CALL",
        "Log a call in two taps",
        [
            {"do": "goto", "url": "/review-fixture/leads"},
            GOT_IT,
            {"do": "tap", "target": {"role": "button", "name": "Open Asha Fictional"}, "ms": 1400},
            {"do": "tap", "target": {"text": "Log a call"}, "ms": 1200},
            {"do": "tap", "target": {"role": "button", "name": "We talked"}, "ms": 1200},
        ],
        glow({"role": "button", "name": "Site visit booked"}),
    ),
    (
        "coaching",
        "COACHING",
        "Know the one thing to fix",
        [
            {"do": "goto", "url": REPORT},
            {"do": "tap", "target": {"role": "button", "name": "Coaching view"}, "ms": 1500},
        ],
        glow({"text": "What You Should Work On Now"}, up=1),
    ),
    (
        "home",
        "HOME",
        "Your sales at a glance",
        [{"do": "goto", "url": "/review-fixture/home"}],
        glow({"text": "Won", "exact": True}, up=2),
    ),
    (
        "chats",
        "CHATS",
        "Every chat, one inbox",
        [{"do": "goto", "url": "/review-fixture/chats"}],
        glow({"role": "button", "name": "Waiting"}),
    ),
    (
        "team",
        "TEAM",
        "Bring your whole team",
        [{"do": "goto", "url": "/review-fixture/settings?section=team"}],
        glow({"role": "button", "name": "Invite", "exact": True}),
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
        "Every call, scored by AI",
        [
            {"do": "goto", "url": REPORT},
            {
                "do": "scrollto",
                "target": {"text": "2. AI Coaching Score"},
                "offset": 52,
                "parent": True,
                "ms": 700,
            },
            *JARGON,
        ],
    ),
    (
        "desk-organisation",
        "Your team, your company",
        [{"do": "goto", "url": "/review-fixture/settings?section=organisation"}],
    ),
]


def node(*args: str) -> None:
    render.wait_for_headroom()
    cmd = [*render.NICE, "node", str(HERE / "capture.mjs"), *args]
    subprocess.run(cmd, check=True, cwd=REPO, env=render.safe_env(), stdin=subprocess.DEVNULL)  # noqa: S603


def cmd_stills(out: Path, theme: str) -> None:
    store = [{"do": "marketing", "names": NAMES, "me": "VS"}, {"do": "frost"}]
    spec = [
        {"name": n, "device": "phone", "theme": theme, "setup": [*s, *store, g]}
        for n, _k, _h, s, g in PHONE
    ]
    spec += [
        {"name": n, "device": "desktop", "theme": theme, "setup": [*s, *store]}
        for n, _h, s in TABLET
    ]
    out.mkdir(parents=True, exist_ok=True)
    (out / "stills.json").write_text(json.dumps(spec), encoding="utf-8")
    node("stills", str(out / "stills.json"), str(out / "stills"))
    (out / "stills.json").unlink()


# Key screens as clean captures for a brand designer: the phone setup, and where a wider screen
# needs another path (icon-only tabs, the Report's own scroller), the setup for tablet and computer.
WIDE = {
    "report-score": [
        {"do": "goto", "url": REPORT},
        {
            "do": "scrollto",
            "target": {"text": "2. AI Coaching Score"},
            "offset": 52,
            "parent": True,
        },
        *JARGON,
    ],
    "leads-table": [
        {"do": "goto", "url": "/review-fixture/leads?tab=all&pipelines=2"},
        {"do": "tap", "target": {"text": "Table", "exact": True}, "ms": 900, "optional": True},
    ],
}


def cmd_captures(theme: str) -> None:
    store = [{"do": "marketing", "names": NAMES, "me": "VS"}, {"do": "frost"}]
    spec = []
    for name, _k, _h, setup, _g in PHONE:
        spec.append(
            {"name": f"phone/{name}", "device": "phone", "theme": theme, "setup": [*setup, *store]}
        )
        wide = WIDE.get(name, setup)
        for device in ("tablet", "desktop"):
            spec.append(
                {
                    "name": f"{device}/{name}",
                    "device": device,
                    "theme": theme,
                    "setup": [*wide, *store],
                }
            )
    for device in ("tablet", "desktop"):
        spec.append(
            {
                "name": f"{device}/leads-table",
                "device": device,
                "theme": theme,
                "setup": [*WIDE["leads-table"], *store],
            }
        )
    out = OUT.parent / "captures" / theme
    for sub in ("phone", "tablet", "desktop"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    node("stills", str(out / "spec.json"), str(out))
    (out / "spec.json").unlink()


def data_uri(path: Path) -> str:
    kind = "svg+xml" if path.suffix == ".svg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def page(font_css: str, w: int, h: int, body: str) -> str:
    style = (
        "*{box-sizing:border-box;margin:0;padding:0}"
        f"html,body{{width:{w}px;height:{h}px;overflow:hidden;"
        "font-family:'SXBrand','Plus Jakarta Sans','DejaVu Sans',sans-serif;"
        "-webkit-font-smoothing:antialiased}"
    )
    head = f'<meta charset="utf-8"><style>{font_css}{style}</style>'
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def div(style: str, inner: str = "") -> str:
    return f"<div style='{style}'>{inner}</div>"


def img(src: Path, style: str) -> str:
    return f"<img src='{data_uri(src)}' style='{style}'>"


# Brand gradient: teal light from the top corner into deep navy.
GROUND = (
    "radial-gradient(900px 700px at 85% 0%,rgba(45,212,191,.55),transparent 65%),"
    "radial-gradient(700px 700px at 0% 30%,rgba(14,116,144,.45),transparent 70%),"
    f"linear-gradient(165deg,#14b8a6 0%,#0f766e 34%,#0b3a4a 64%,{NAVY} 100%)"
)
FULL = css(position="absolute", inset=0)


def framed(shot: Path, left: int, top: int, width: int, extra: str = "") -> str:
    """A phone screenshot in the one device frame every store image uses."""
    bezel, radius = round(width / 40), round(width * 0.09)
    height = round(width * 2532 / 1170)
    frame = css(
        position="absolute",
        left=left,
        top=top,
        width=width + 2 * bezel,
        height=height + 2 * bezel,
        border_radius=radius + bezel,
        background="#05080f",
        padding=bezel,
        box_shadow="0 0 0 2px rgba(255,255,255,.14),0 50px 110px rgba(0,0,0,.45)",
    )
    screen = css(display="block", width=width, height=height, border_radius=radius)
    return div(frame + extra, img(shot, screen))


def kicker_and_headline(kicker: str, headline: str, top: int, size: int) -> str:
    box = css(position="absolute", left=80, right=80, top=top, text_align="center", color="#fff")
    kick = css(font_weight=800, font_size=round(size * 0.36), letter_spacing=".16em", opacity=".8")
    big = css(
        margin_top=18, font_weight=800, font_size=size, line_height="1.05", text_wrap="balance"
    )
    return div(
        box, div(kick, escape(kicker)) + div(big + ";letter-spacing:-.035em", escape(headline))
    )


def phone_html(font_css: str, shot: Path, kicker: str, headline: str) -> str:
    w, h, pw = 1080, 1920, 720
    body = (
        div(f"{FULL};background:{GROUND}")
        + kicker_and_headline(kicker, headline, 110, 92)
        + framed(shot, (w - pw) // 2 - round(pw / 40), 450, pw)
    )
    return page(font_css, w, h, body)


def tablet_html(font_css: str, shot: Path, headline: str) -> str:
    w, h, sw = 1920, 1080, 1460
    sh = round(sw * 1800 / 2880)
    title = css(
        position="absolute",
        left=0,
        right=0,
        top=46,
        text_align="center",
        font_weight=800,
        font_size=64,
        color="#fff",
    )
    window = css(
        position="absolute",
        left=(w - sw) // 2,
        top=170,
        width=sw,
        height=sh,
        border_radius=22,
        overflow="hidden",
        box_shadow="0 0 0 2px rgba(255,255,255,.16),0 50px 110px rgba(0,0,0,.45)",
    )
    body = (
        div(f"{FULL};background:{GROUND}")
        + div(title + ";letter-spacing:-.03em", escape(headline))
        + div(window, img(shot, css(display="block", width=sw, height=sh)))
    )
    return page(font_css, w, h, body)


def feature_html(font_css: str, shot: Path, icon: Path | None) -> str:
    w, h, pw = 1024, 500, 250
    mark = ""
    if icon:
        mark = img(icon, css(width=64, height=64, border_radius=16, margin_right=16))
    brand = css(display="flex", align_items="center", font_weight=800, font_size=30)
    big = css(margin_top=36, font_weight=800, font_size=62, line_height="1.04", text_wrap="balance")
    sub = css(margin_top=22, font_weight=600, font_size=23, line_height="1.4", opacity=".9")
    text = div(
        css(position="absolute", left=64, top=64, width=580, color="#fff"),
        div(brand, mark + "Sales X-Ray")
        + div(big + ";letter-spacing:-.035em", "Every call, scored by AI")
        + div(sub, "Calls, leads and AI coaching in one app"),
    )
    phone = framed(shot, w - pw - 100, 48, pw, ";transform:rotate(-5deg)")
    return page(font_css, w, h, div(f"{FULL};background:{GROUND}") + text + phone)


def icon_html(icon: Path) -> str:
    return page("", 512, 512, img(icon, css(display="block", width=512, height=512)))


def cmd_art(out: Path, icon: Path | None) -> None:
    font_css = render.brand_font_css(REPO)
    st = out / "stills"
    cards = []
    for i, (name, kicker, headline, _s, _g) in enumerate(PHONE, 1):
        html = phone_html(font_css, st / f"{name}.png", kicker, headline)
        cards.append({"name": f"phone/{i:02d}-{name}", "width": 1080, "height": 1920, "html": html})
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
    feature = feature_html(font_css, st / "report-score.png", icon)
    cards.append(
        {
            "name": "feature-graphic-1024x500",
            "width": 1024,
            "height": 500,
            "jpeg": True,
            "html": feature,
        }
    )
    if icon:
        cards.append({"name": "icon-512", "width": 512, "height": 512, "html": icon_html(icon)})
    for sub in ("phone", "tablet-7in", "tablet-10in"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    node("cards", str(out / "cards.json"), str(out))
    (out / "cards.json").unlink()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("step", choices=["stills", "art", "all", "captures"])
    p.add_argument("--theme", choices=["light", "dark"], default="light")
    p.add_argument("--icon", help="launcher icon artwork (PNG or SVG) for the 512 px store icon")
    a = p.parse_args()
    out = OUT / a.theme
    if a.step == "captures":
        cmd_captures(a.theme)
        return 0
    if a.step in ("stills", "all"):
        cmd_stills(out, a.theme)
    if a.step in ("art", "all"):
        cmd_art(out, Path(a.icon) if a.icon else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
