# ruff: noqa: E501, S603, S607
# (fixed ffmpeg argument list)
"""YouTube channel art in brand B: banner 2560x1440 (logo and tagline inside the 1546x423 safe area that every
device shows) and an 800x800 avatar. Writes PNGs into <out>."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "scripts/tutorials")
from sxtut import brand, render  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
v2 = Path("/home/acdev/sx-tutorials/v2")
kit = brand.Kit(Path("/home/acdev/sx-tutorials/fonts"), v2 / "brand" / "logo" / "svg")
css = brand.BARS_CSS + (
    ".safe{position:absolute;left:507px;top:508px;width:1546px;height:423px;display:flex;"
    "flex-direction:column;align-items:center;justify-content:center;gap:26px}"
    ".lg{width:900px}"
    f".tg{{font-weight:600;font-size:64px;color:{brand.MINT_LIGHT}}}"
    ".ln{font-weight:500;font-size:40px;opacity:.88}"
    ".m1{position:absolute;left:120px;top:300px;width:520px;height:520px;opacity:.08}"
    ".m2{position:absolute;right:120px;top:640px;width:520px;height:520px;opacity:.08}"
)
body = (
    "<div class='ground'></div><div class='grain'></div>"
    f"<div class='m1'>{brand._bars('bars still')}</div><div class='m2'>{brand._bars('bars still')}</div>"
    f"<div class='safe'><div class='lg svgfit'>{kit.svg('horizontal-mono-white')}</div>"
    f"<div class='tg'>{brand.TAGLINE}</div>"
    "<div class='ln'>How-to videos in English · हिंदी · मराठी</div></div>"
)
cards = [
    {
        "name": "youtube-banner-2560x1440",
        "width": 2560,
        "height": 1440,
        "html": kit.page(body, css, 2560, 1440),
    }
]
render.render_cards(Path.cwd(), cards, out)
icon = v2 / "brand" / "icon" / "sales-xray-icon-1024.png"
subprocess.run(
    [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(icon),
        "-vf",
        "scale=800:800",
        str(out / "youtube-avatar-800x800.png"),
    ],
    check=True,
)
for f in out.glob("*.key"):
    f.unlink()
print(sorted(p.name for p in out.iterdir()))
