"""Brand B "Insight" art for tutorials v2: the stage behind the phone, title cards that
move, chapter lower-thirds, the reel hook, and thumbnails. Everything is HTML drawn by the
pipeline's Chromium (capture.mjs cards/motion), in Hind, with the brand pack's logo and symbol.

Palette (brand pack, 23 Oct 2026): Deep teal #0B4A44, Mint #3DEBB0, Paper #F6FAF8, Ink #0C1A18,
Sky #1F6FD1, Sun #FFC857. Headline second lines in light mint #7CF7CF (7.7:1 on Deep teal).
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

DEEP, MINT, PAPER, INK, SKY, SUN, MINT_LIGHT = (
    "#0B4A44",
    "#3DEBB0",
    "#F6FAF8",
    "#0C1A18",
    "#1F6FD1",
    "#FFC857",
    "#7CF7CF",
)
TAGLINE = "Every call, coached."
WEIGHTS = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}

# YouTube stage, drawn at 1.5x of 1080p so a 1.5x zoom on the phone is still sharp.
STAGE_W, STAGE_H = 2880, 1620
# The phone screen on that stage (a 9:16 screen, 390x693 CSS px captures) and its corner radius.
PHONE_HOLE = {"x": 1036, "y": 90, "w": 808, "h": 1436, "r": 58}

GRAIN = (
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
    "width='240' height='240'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' "
    "stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 .07 0'/>"
    "</filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")"
)
GROUND = (
    f"radial-gradient(60% 55% at 50% 42%,rgba(61,235,176,.20),transparent 70%),"
    f"linear-gradient(160deg,#11695E 0%,{DEEP} 48%,#05302B 100%)"
)


class Kit:
    """Fonts and logo files for cards. `fonts` holds hind/Hind-*.ttf; `logos` the brand pack's svg
    folder."""

    def __init__(self, fonts: Path, logos: Path) -> None:
        self.fonts, self.logos = fonts, logos
        self._css = ""

    def font_css(self) -> str:
        if not self._css:
            faces = []
            for weight, name in WEIGHTS.items():
                ttf = self.fonts / "hind" / f"Hind-{name}.ttf"
                if ttf.exists():
                    data = base64.b64encode(ttf.read_bytes()).decode()
                    faces.append(
                        f"@font-face{{font-family:'Hind';font-weight:{weight};"
                        f"src:url(data:font/ttf;base64,{data}) format('truetype');}}"
                    )
            self._css = "".join(faces)
        return self._css

    def svg(self, name: str) -> str:
        """An inline logo, e.g. 'horizontal-mono-white', 'symbol-on-dark', 'stacked-dark'."""
        path = self.logos / f"sales-xray-{name}.svg"
        return path.read_text(encoding="utf-8") if path.exists() else "<b>Sales X-Ray</b>"

    def page(self, body: str, css: str, w: int, h: int, transparent: bool = False) -> str:
        _SYMBOL_IDS[0] = 0
        bg = "transparent" if transparent else DEEP
        base = (
            "*{box-sizing:border-box;margin:0;padding:0}"
            f"html,body{{width:{w}px;height:{h}px;overflow:hidden;background:{bg};"
            "font-family:'Hind','Noto Sans Devanagari','DejaVu Sans',sans-serif;color:#fff;"
            "-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}"
            f".ground{{position:absolute;inset:0;background:{GROUND}}}"
            f".grain{{position:absolute;inset:0;background-image:{GRAIN};opacity:.9;"
            "mix-blend-mode:overlay}"
            ".svgfit svg{width:100%;height:auto;display:block}"
        )
        head = f'<meta charset="utf-8"><style>{self.font_css()}{base}{css}</style>'
        return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


_SYMBOL_IDS = [0]  # gradient ids per page; each *_html() starts again from 0 so cards cache by HTML
# The brand pack's symbol (sales-xray-symbol-on-dark.svg, 100x100): four mint listening bars,
# the white "i" stem and dot of insight, and a mint glow behind the dot.
# (centre x, top, bottom, tone) per bar.
_SYMBOL_BARS = (
    (17, 43, 67, "m"),
    (33.5, 33, 77, "m"),
    (50, 44, 82, "w"),
    (66.5, 33, 77, "m"),
    (83, 43, 67, "m"),
)


def _bars(cls: str = "bars") -> str:
    """The symbol as inline SVG whose bars grow and whose dot pops (class 'still' keeps it
    static)."""
    _SYMBOL_IDS[0] += 1
    n = _SYMBOL_IDS[0]
    defs = (
        f"<linearGradient id='m{n}' gradientUnits='userSpaceOnUse' "
        "x1='0' y1='22.66' x2='0' y2='82'>"
        "<stop offset='0' stop-color='#7CF7CF'/>"
        "<stop offset='1' stop-color='#18C08C'/></linearGradient>"
        f"<linearGradient id='w{n}' gradientUnits='userSpaceOnUse' "
        "x1='0' y1='22.66' x2='0' y2='82'>"
        "<stop offset='0' stop-color='#FFFFFF'/>"
        "<stop offset='1' stop-color='#D3F7EA'/></linearGradient>"
        f"<radialGradient id='g{n}' cx='50' cy='29.7' r='22.53' gradientUnits='userSpaceOnUse'>"
        "<stop offset='0' stop-color='#3DEBB0' stop-opacity='.55'/>"
        "<stop offset='1' stop-color='#3DEBB0' stop-opacity='0'/></radialGradient>"
    )
    rects = "".join(
        f"<rect class='a' x='{cx - 5.5}' y='{top}' width='11' height='{bottom - top}' rx='5.5' "
        f"fill='url(#{tone}{n})' style='animation-delay:{0.07 * i:.2f}s'/>"
        for i, (cx, top, bottom, tone) in enumerate(_SYMBOL_BARS)
    )
    return (
        f"<svg class='{cls}' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'><defs>"
        f"{defs}</defs>"
        f"<circle class='gl' cx='50' cy='29.7' r='22.53' fill='url(#g{n})'/>{rects}"
        f"<circle class='d' cx='50' cy='29.7' r='7.04' fill='url(#w{n})'/></svg>"
    )


BARS_CSS = (
    ".bars{display:block;width:100%;height:100%;overflow:visible}"
    ".bars rect.a,.bars circle{transform-box:fill-box;transform-origin:50% 50%}"
    ".bars rect.a{animation:grow .62s cubic-bezier(.2,.9,.25,1.25) both}"
    ".bars circle.d{animation:pop .42s .4s cubic-bezier(.2,.9,.3,1.6) both}"
    ".bars circle.gl{animation:fade .6s .5s both}"
    ".bars.still rect.a,.bars.still circle{animation:none}"
    "@keyframes grow{from{transform:scaleY(.08);opacity:0}to{transform:scaleY(1);opacity:1}}"
    "@keyframes pop{from{transform:scale(0)}to{transform:scale(1)}}"
    "@keyframes rise{from{transform:translateY(46px);opacity:0}to{transform:none;opacity:1}}"
    "@keyframes fade{from{opacity:0}to{opacity:1}}"
    "@keyframes draw{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
)


def stage_html(kit: Kit) -> str:
    """The YouTube stage at 2880x1620: brand ground, a graphite phone with a light rim and
    soft shadow, and a transparent screen hole the clip shows through."""
    h = PHONE_HOLE
    x, y, w, hh, r = h["x"], h["y"], h["w"], h["h"], h["r"]
    bezel = 22
    hole = (
        f"M0 0H{STAGE_W}V{STAGE_H}H0Z M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}"
        f"V{y + hh - r}A{r} {r} 0 0 1 {x + w - r} {y + hh}H{x + r}A{r} {r} 0 0 1 {x} {y + hh - r}"
        f"V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z"
    )
    mask_svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{STAGE_W}' height='{STAGE_H}'>"
        f"<path fill-rule='evenodd' d='{hole}'/></svg>"
    )
    mask = "url(data:image/svg+xml;base64," + base64.b64encode(mask_svg.encode()).decode() + ")"
    css = (
        f".all{{position:absolute;inset:0;-webkit-mask:{mask};mask:{mask}}}"
        f".rim{{position:absolute;left:{x - bezel}px;top:{y - bezel}px;width:{w + 2 * bezel}px;"
        f"height:{hh + 2 * bezel}px;border-radius:{r + bezel}px;background:#141B1A;"
        "box-shadow:0 0 0 3px rgba(255,255,255,.16),0 60px 140px rgba(0,0,0,.45),"
        "0 0 220px rgba(61,235,176,.18)}"
        ".motif{position:absolute;opacity:.07;width:520px;height:520px}"
    )
    body = (
        "<div class='all'><div class='ground'></div><div class='grain'></div>"
        f"<div class='motif' style='left:150px;top:840px'>{_bars('bars still')}</div>"
        f"<div class='motif' style='right:150px;top:120px'>{_bars('bars still')}</div>"
        "<div class='rim'></div></div>"
    )
    return kit.page(body, BARS_CSS + css, STAGE_W, STAGE_H, transparent=True)


def intro_html(kit: Kit, number: str, title: str, kicker: str) -> str:
    """16:9 opening card, 1920x1080: the mark builds, the title rises, a mint line draws."""
    css = BARS_CSS + (
        ".logo{position:absolute;left:150px;top:118px;display:flex;align-items:center;gap:26px}"
        ".logo .mk{width:96px;height:96px}"
        ".logo .wm{width:330px;animation:fade .5s .45s both}"
        ".blk{position:absolute;left:150px;top:350px;width:1180px}"
        ".k{font-weight:600;font-size:34px;letter-spacing:.14em;"
        f"text-transform:uppercase;color:{MINT_LIGHT};animation:rise .55s .55s both}}"
        ".t{margin-top:22px;font-weight:700;font-size:112px;line-height:1.02;letter-spacing:-.02em;"
        "text-wrap:balance;animation:rise .65s .7s both}"
        ".u{margin-top:44px;margin-left:4px;width:220px;height:12px;border-radius:6px;"
        f"background:{MINT};transform-origin:0 50%;animation:draw .5s 1.15s both}}"
        ".tag{position:absolute;left:150px;bottom:110px;font-weight:500;font-size:38px;opacity:.86;"
        "animation:fade .6s 1.35s both}"
        ".big{position:absolute;right:-60px;top:170px;width:760px;height:760px;opacity:.12}"
    )
    body = (
        "<div class='ground'></div><div class='grain'></div>"
        f"<div class='big'>{_bars()}</div>"
        f"<div class='logo'><div class='mk'>{_bars()}</div>"
        f"<div class='wm svgfit'>{kit.svg('wordmark-mono-white')}</div></div>"
        f"<div class='blk'><div class='k'>{escape(kicker)} · {escape(number)}</div>"
        f"<div class='t'>{escape(title)}</div><div class='u'></div></div>"
        f"<div class='tag'>{TAGLINE}</div>"
    )
    return kit.page(body, css, 1920, 1080)


def outro_html(kit: Kit, headline: str, next_label: str, next_title: str) -> str:
    """16:9 closing card: a short headline, the next tutorial, the logo and tagline."""
    css = BARS_CSS + (
        ".h{position:absolute;left:150px;top:250px;width:1000px;font-weight:700;font-size:118px;"
        "line-height:1.02;letter-spacing:-.02em;animation:rise .6s .1s both}"
        ".n{position:absolute;right:150px;top:270px;width:600px;padding:44px 48px;"
        "border-radius:36px;"
        "background:rgba(255,255,255,.08);box-shadow:inset 0 0 0 2px rgba(124,247,207,.45);"
        "animation:rise .6s .45s both}"
        ".n small{display:block;font-weight:600;font-size:28px;letter-spacing:.12em;"
        f"color:{MINT_LIGHT};"
        "text-transform:uppercase}"
        ".n div{margin-top:16px;font-weight:700;font-size:54px;line-height:1.1}"
        ".foot{position:absolute;left:150px;right:150px;bottom:110px;display:flex;"
        "align-items:center;"
        "justify-content:space-between;animation:fade .6s .8s both}"
        ".foot .lk{display:flex;align-items:center;gap:22px}.foot .mk{width:78px;height:78px}"
        ".foot .wm{width:280px}.foot .tag{font-weight:500;font-size:38px;opacity:.86}"
    )
    nxt = (
        f"<div class='n'><small>{escape(next_label)}</small><div>{escape(next_title)}</div></div>"
        if next_title
        else ""
    )
    body = (
        "<div class='ground'></div><div class='grain'></div>"
        f"<div class='h'>{escape(headline)}</div>{nxt}"
        f"<div class='foot'><div class='lk'><div class='mk'>{_bars()}</div>"
        f"<div class='wm svgfit'>{kit.svg('wordmark-mono-white')}</div></div>"
        f"<div class='tag'>{TAGLINE}</div></div>"
    )
    return kit.page(body, css, 1920, 1080)


def reel_end_html(kit: Kit, title: str, cta: str) -> str:
    """9:16 end card, 1080x1920: the mark builds, the logo, what the reel showed, the tagline."""
    css = BARS_CSS + (
        ".mk{position:absolute;left:390px;top:520px;width:300px;height:300px}"
        ".wm{position:absolute;left:190px;top:880px;width:700px;animation:fade .45s .4s both}"
        ".t{position:absolute;left:110px;right:110px;top:1080px;text-align:center;font-weight:700;"
        "font-size:66px;line-height:1.1;animation:rise .5s .5s both}"
        ".c{position:absolute;left:110px;right:110px;top:1330px;text-align:center;"
        f"color:{MINT_LIGHT};"
        "font-weight:600;font-size:44px;animation:fade .5s .75s both}"
    )
    body = (
        "<div class='ground'></div><div class='grain'></div>"
        f"<div class='mk'>{_bars()}</div><div class='wm svgfit'>"
        f"{kit.svg('wordmark-mono-white')}</div>"
        f"<div class='t'>{escape(title)}</div><div class='c'>{escape(cta)}</div>"
    )
    return kit.page(body, css, 1080, 1920)


def lower_third_html(kit: Kit, number: int, title: str) -> str:
    """A chapter tag for the 16:9 tutorial (transparent PNG, cropped by the box): a numbered mint
    disc and the chapter title on Deep teal."""
    css = (
        ".lt{position:absolute;left:0;top:0;display:inline-flex;align-items:center;gap:22px;"
        "padding:18px 40px 16px 20px;border-radius:999px;background:rgba(11,74,68,.94);"
        "box-shadow:0 14px 40px rgba(0,0,0,.28),inset 0 0 0 2px rgba(124,247,207,.35)}"
        f".no{{width:58px;height:58px;border-radius:50%;background:{MINT};color:{INK};display:grid;"
        "place-items:center;font-weight:700;font-size:34px;padding-top:4px}"
        ".tx{font-weight:600;font-size:40px;white-space:nowrap;padding-top:4px}"
    )
    body = (
        f"<div class='lt'><div class='no'>{number}</div><div class='tx'>{escape(title)}</div></div>"
    )
    return kit.page(body, css, 1400, 140, transparent=True)


def hook_html(kit: Kit, text: str, accent: str = "") -> str:
    """The reel's opening line (transparent PNG, 1080 wide): white on Deep teal, the accent words in
    light mint."""
    shown = escape(text)
    if accent and accent in text:
        a = escape(accent)
        shown = shown.replace(a, f"<em>{a}</em>", 1)
    css = (
        ".hk{position:absolute;left:60px;right:60px;top:0;padding:34px 44px 28px;"
        "border-radius:40px;"
        "background:rgba(11,74,68,.95);box-shadow:0 24px 60px rgba(0,0,0,.30),"
        "inset 0 0 0 3px rgba(124,247,207,.4);font-weight:700;font-size:74px;line-height:1.06;"
        "text-align:center;letter-spacing:-.01em}"
        f".hk em{{font-style:normal;color:{MINT_LIGHT}}}"
    )
    return kit.page(f"<div class='hk'>{shown}</div>", css, 1080, 420, transparent=True)


def logo_bug_html(kit: Kit) -> str:
    """A small white logo for the corner of the 16:9 tutorial (transparent PNG)."""
    css = ".b{position:absolute;left:0;top:0;width:250px;opacity:.92}"
    body = f"<div class='b svgfit'>{kit.svg('horizontal-mono-white')}</div>"
    return kit.page(body, css, 250, 80, transparent=True)


def thumbnail_html(kit: Kit, title: str, accent: str, badge: str, screen_png: Path) -> str:
    """YouTube thumbnail, 1280x720: a bold title (accent words in mint), the phone screen, the
    logo."""
    shown = escape(title)
    if accent and accent in title:
        a = escape(accent)
        shown = shown.replace(a, f"<em>{a}</em>", 1)
    shot = base64.b64encode(screen_png.read_bytes()).decode()
    css = (
        ".t{position:absolute;left:64px;top:160px;width:660px;font-weight:700;font-size:88px;"
        "line-height:1.0;letter-spacing:-.02em;text-wrap:balance}"
        f".t em{{font-style:normal;color:{MINT_LIGHT}}}"
        f".bd{{position:absolute;left:64px;top:64px;padding:10px 22px 6px;border-radius:999px;"
        f"background:{MINT};color:{INK};font-weight:700;font-size:30px}}"
        ".ph{position:absolute;right:90px;top:46px;width:356px;height:633px;border-radius:44px;"
        "border:12px solid #141B1A;overflow:hidden;transform:rotate(4deg);"
        "box-shadow:0 0 0 3px rgba(255,255,255,.18),0 30px 80px rgba(0,0,0,.5),"
        "0 0 120px rgba(61,235,176,.25)}"
        ".ph img{width:100%;height:100%;object-fit:cover;object-position:top}"
        ".lg{position:absolute;left:64px;bottom:52px;width:300px}"
    )
    body = (
        "<div class='ground'></div><div class='grain'></div>"
        f"<div class='bd'>{escape(badge)}</div><div class='t'>{shown}</div>"
        f"<div class='ph'><img src='data:image/png;base64,{shot}'></div>"
        f"<div class='lg svgfit'>{kit.svg('horizontal-mono-white')}</div>"
    )
    return kit.page(body, css, 1280, 720)
