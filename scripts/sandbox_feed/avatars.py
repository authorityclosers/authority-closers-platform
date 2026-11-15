"""Drawn portraits for the dev sandbox's fictional sellers (flat illustrations made here with
Pillow, never a photo of a real person), so Home and Team show faces instead of initials.

    python avatars.py <out folder>   writes <alias>.png for every look, to check by eye
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw

SIZE = 256
DRAW = 1024  # drawn large, then scaled down: smooth edges


class Look(NamedTuple):
    background: str
    skin: str
    hair: str
    style: str  # short, side, curly, long, bun, scarf
    top: str  # shirt, kurta or scarf colour
    glasses: bool = False
    beard: bool = False
    moustache: bool = False
    bindi: bool = False
    earrings: bool = False


LOOKS: dict[str, Look] = {
    "ac.priya": Look("#F7D9C4", "#C68A62", "#2B1B14", "long", "#1F7A7A", bindi=True, earrings=True),
    "ac.rohan": Look("#CFE3F6", "#B97E55", "#1E1A18", "short", "#27406B", beard=True),
    "ac.sneha": Look(
        "#E3D7F3", "#D19C74", "#3A2418", "bun", "#8C2F46", glasses=True, earrings=True
    ),
    "ac.aditya": Look("#D3EEDF", "#C28C66", "#231C17", "side", "#C9922E", glasses=True),
    "ac.farah": Look("#F6D6DF", "#C99272", "#000000", "scarf", "#9C5B6E"),
    "ac.venkatesh": Look("#EFE3C8", "#8E5B3C", "#16120F", "curly", "#3D6FA8", moustache=True),
}
DEFAULT = Look("#DDE3EA", "#C08A64", "#221A15", "short", "#4A5A70")


def _shade(colour: str, factor: float) -> str:
    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(
        *(max(0, min(255, round(c * factor))) for c in (red, green, blue))
    )


def draw(look: Look) -> Image.Image:
    s = DRAW
    cx = s // 2
    image = Image.new("RGB", (s, s), look.background)
    d = ImageDraw.Draw(image)
    skin_dark = _shade(look.skin, 0.85)
    dark = "#1B1410"
    # Behind the head: long hair, or the scarf's drape.
    if look.style == "long":
        d.rounded_rectangle((cx - 245, 300, cx + 245, 880), radius=210, fill=look.hair)
    if look.style == "scarf":
        d.ellipse((cx - 265, 190, cx + 265, 760), fill=look.top)
        d.polygon(
            [(cx - 265, 480), (cx + 265, 480), (cx + 360, 1024), (cx - 360, 1024)], fill=look.top
        )
    # Shoulders and top.
    d.ellipse(
        (cx - 390, 770, cx + 390, 1330),
        fill=look.top if look.style != "scarf" else _shade(look.top, 0.8),
    )
    # Neck, with the V of the neckline.
    if look.style != "scarf":
        d.rounded_rectangle((cx - 78, 600, cx + 78, 830), radius=36, fill=skin_dark)
        d.polygon([(cx - 105, 790), (cx, 905), (cx + 105, 790)], fill=skin_dark)
    # Ears.
    if look.style not in ("scarf",):
        d.ellipse((cx - 218, 430, cx - 158, 545), fill=look.skin)
        d.ellipse((cx + 158, 430, cx + 218, 545), fill=look.skin)
        if look.earrings:
            d.ellipse((cx - 205, 545, cx - 177, 573), fill="#E0B23A")
            d.ellipse((cx + 177, 545, cx + 205, 573), fill="#E0B23A")
    # Face.
    d.ellipse((cx - 190, 255, cx + 190, 705), fill=look.skin)
    # Hair on top.
    if look.style in ("short", "side", "long", "bun"):
        d.chord((cx - 205, 215, cx + 205, 495), 180, 360, fill=look.hair)
        d.rectangle((cx - 200, 350, cx - 172, 455), fill=look.hair)
        d.rectangle((cx + 172, 350, cx + 200, 455), fill=look.hair)
    if look.style == "side":
        d.polygon(
            [(cx - 196, 360), (cx + 30, 292), (cx + 200, 372), (cx + 200, 320), (cx - 70, 232)],
            fill=look.hair,
        )
    if look.style == "long":
        d.polygon([(cx - 8, 238), (cx - 196, 430), (cx - 196, 330)], fill=look.hair)
        d.polygon([(cx + 8, 238), (cx + 196, 430), (cx + 196, 330)], fill=look.hair)
        d.line((cx, 232, cx, 300), fill=_shade(look.skin, 0.9), width=8)
    if look.style == "bun":
        d.ellipse((cx - 95, 140, cx + 95, 300), fill=look.hair)
    if look.style == "curly":
        for x, y, r in (
            (-150, 330, 70),
            (-90, 280, 75),
            (-20, 262, 78),
            (55, 268, 76),
            (125, 300, 72),
            (170, 360, 58),
            (-185, 390, 50),
            (0, 300, 70),
        ):
            d.ellipse((cx + x - r, y - r, cx + x + r, y + r), fill=look.hair)
    if look.style == "scarf":
        # The scarf's front edge framing the face.
        d.chord((cx - 225, 200, cx + 225, 640), 180, 360, fill=look.top)
        d.arc((cx - 200, 250, cx + 200, 720), 150, 390, fill=_shade(look.top, 0.75), width=22)
    # Brows, eyes, nose, mouth.
    brow = look.hair if look.style != "scarf" else dark
    d.line((cx - 120, 428, cx - 55, 418), fill=brow, width=16)
    d.line((cx + 55, 418, cx + 120, 428), fill=brow, width=16)
    d.ellipse((cx - 100, 462, cx - 66, 500), fill=dark)
    d.ellipse((cx + 66, 462, cx + 100, 500), fill=dark)
    d.ellipse((cx - 90, 468, cx - 80, 478), fill="#FFFFFF")
    d.ellipse((cx + 76, 468, cx + 86, 478), fill="#FFFFFF")
    d.arc((cx - 28, 500, cx + 28, 570), 20, 160, fill=skin_dark, width=10)
    if look.beard:
        stubble = _shade(look.skin, 0.55)
        d.chord((cx - 182, 440, cx + 182, 712), 8, 172, fill=stubble)
        d.ellipse((cx - 66, 588, cx + 66, 640), fill=look.skin)
    if look.moustache:
        d.chord((cx - 70, 565, cx + 70, 625), 180, 360, fill=look.hair)
    d.arc((cx - 62, 560, cx + 62, 642), 25, 155, fill="#8E3B3B", width=13)
    if look.bindi:
        d.ellipse((cx - 14, 392, cx + 14, 420), fill="#C0262D")
    if look.glasses:
        frame = "#2A2A2A"
        d.rounded_rectangle((cx - 140, 440, cx - 30, 525), radius=26, outline=frame, width=11)
        d.rounded_rectangle((cx + 30, 440, cx + 140, 525), radius=26, outline=frame, width=11)
        d.line((cx - 30, 470, cx + 30, 470), fill=frame, width=10)
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def portrait(alias: str) -> bytes:
    """The seller's portrait as PNG bytes (256 px square)."""
    output = io.BytesIO()
    draw(LOOKS.get(alias, DEFAULT)).save(output, format="PNG", optimize=True)
    return output.getvalue()


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    folder.mkdir(parents=True, exist_ok=True)
    for alias in LOOKS:
        (folder / f"{alias}.png").write_bytes(portrait(alias))
    print(sorted(LOOKS))
