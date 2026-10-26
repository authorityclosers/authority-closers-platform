"""Sales X-Ray's characters: friendly, gender-neutral animal faces for people without a photo.

Owner, 26 Oct 2026 (#32): a cute character where there is no photo, never guessed from a
name. Each character is drawn once, from the shapes below, as an SVG source and as the
256 x 256 WebP the server ships (packages/python/ac_platform/identity/characters/). The
manifest's order picks a person's default: characters[int(person_id_hex[:8], 16) % len].

A key's file never changes once it ships (a chosen character is stored as the person's
photo): a new look gets a new key.
Run: uv run python scripts/characters/make_characters.py [out_dir]
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
SCALE = 4  # drawn four times larger, then scaled down for smooth edges
DARK = "#2B2B2B"
WHITE = "#FFFFFF"

Shape = tuple

# Each character: its label, its soft background, and its shapes in a 256 x 256 frame,
# back to front.
CHARACTERS: dict[str, tuple[str, str, list[Shape]]] = {
    "fox": (
        "Fox",
        "#FFE8D6",
        [
            ("poly", [(66, 58), (104, 118), (52, 126)], "#F28C38"),
            ("poly", [(190, 58), (152, 118), (204, 126)], "#F28C38"),
            ("poly", [(74, 88), (92, 114), (66, 117)], "#FFF3E6"),
            ("poly", [(182, 88), (164, 114), (190, 117)], "#FFF3E6"),
            ("ellipse", 128, 150, 80, 70, "#F28C38"),
            ("ellipse", 100, 172, 34, 26, "#FFF8F0"),
            ("ellipse", 156, 172, 34, 26, "#FFF8F0"),
            ("circle", 100, 142, 8, DARK),
            ("circle", 156, 142, 8, DARK),
            ("ellipse", 128, 170, 10, 8, DARK),
        ],
    ),
    "owl": (
        "Owl",
        "#E6EEFF",
        [
            ("poly", [(60, 96), (80, 56), (100, 98)], "#8C6A4F"),
            ("poly", [(196, 96), (176, 56), (156, 98)], "#8C6A4F"),
            ("ellipse", 128, 150, 82, 78, "#8C6A4F"),
            ("ellipse", 128, 152, 66, 58, "#E9D6C2"),
            ("circle", 104, 142, 22, WHITE),
            ("circle", 152, 142, 22, WHITE),
            ("circle", 104, 142, 10, DARK),
            ("circle", 152, 142, 10, DARK),
            ("poly", [(119, 160), (137, 160), (128, 178)], "#F2A33A"),
        ],
    ),
    "panda": (
        "Panda",
        "#E6F4E8",
        [
            ("circle", 76, 86, 26, DARK),
            ("circle", 180, 86, 26, DARK),
            ("ellipse", 128, 150, 82, 74, WHITE),
            ("ellipse", 100, 144, 20, 26, DARK),
            ("ellipse", 156, 144, 20, 26, DARK),
            ("circle", 102, 140, 6, WHITE),
            ("circle", 154, 140, 6, WHITE),
            ("ellipse", 128, 172, 11, 8, DARK),
        ],
    ),
    "cat": (
        "Cat",
        "#F1E6FF",
        [
            ("poly", [(64, 66), (106, 104), (60, 124)], "#9AA0A6"),
            ("poly", [(192, 66), (150, 104), (196, 124)], "#9AA0A6"),
            ("poly", [(70, 84), (96, 106), (68, 116)], "#F6B8C8"),
            ("poly", [(186, 84), (160, 106), (188, 116)], "#F6B8C8"),
            ("ellipse", 128, 152, 80, 70, "#9AA0A6"),
            ("ellipse", 102, 146, 8, 11, DARK),
            ("ellipse", 154, 146, 8, 11, DARK),
            ("poly", [(119, 166), (137, 166), (128, 175)], "#F28FA8"),
            ("line", 58, 170, 96, 174, 3, "#5F6368"),
            ("line", 58, 184, 96, 181, 3, "#5F6368"),
            ("line", 198, 170, 160, 174, 3, "#5F6368"),
            ("line", 198, 184, 160, 181, 3, "#5F6368"),
        ],
    ),
    "bear": (
        "Bear",
        "#FFF2D2",
        [
            ("circle", 76, 88, 26, "#9C6B43"),
            ("circle", 180, 88, 26, "#9C6B43"),
            ("circle", 76, 88, 13, "#D9B48F"),
            ("circle", 180, 88, 13, "#D9B48F"),
            ("ellipse", 128, 152, 82, 74, "#9C6B43"),
            ("ellipse", 128, 174, 36, 28, "#D9B48F"),
            ("circle", 100, 142, 8, DARK),
            ("circle", 156, 142, 8, DARK),
            ("ellipse", 128, 164, 12, 9, DARK),
        ],
    ),
    "rabbit": (
        "Rabbit",
        "#FFE2EB",
        [
            ("ellipse", 100, 72, 17, 48, "#F4F4F4"),
            ("ellipse", 156, 72, 17, 48, "#F4F4F4"),
            ("ellipse", 100, 74, 8, 34, "#F6B8C8"),
            ("ellipse", 156, 74, 8, 34, "#F6B8C8"),
            ("ellipse", 128, 162, 74, 66, "#F4F4F4"),
            ("circle", 104, 154, 8, DARK),
            ("circle", 152, 154, 8, DARK),
            ("poly", [(121, 174), (135, 174), (128, 182)], "#F28FA8"),
            ("circle", 94, 180, 9, "#F9C9D6"),
            ("circle", 162, 180, 9, "#F9C9D6"),
        ],
    ),
    "penguin": (
        "Penguin",
        "#DDF2F7",
        [
            ("ellipse", 128, 150, 82, 78, "#2F3A45"),
            ("ellipse", 106, 160, 32, 40, WHITE),
            ("ellipse", 150, 160, 32, 40, WHITE),
            ("circle", 108, 150, 8, DARK),
            ("circle", 148, 150, 8, DARK),
            ("poly", [(117, 168), (139, 168), (128, 184)], "#F5A623"),
        ],
    ),
    "koala": (
        "Koala",
        "#E7F1E1",
        [
            ("circle", 66, 110, 34, "#8E9AA6"),
            ("circle", 190, 110, 34, "#8E9AA6"),
            ("circle", 66, 110, 19, "#D7DEE5"),
            ("circle", 190, 110, 19, "#D7DEE5"),
            ("ellipse", 128, 154, 76, 70, "#8E9AA6"),
            ("circle", 104, 146, 7, DARK),
            ("circle", 152, 146, 7, DARK),
            ("ellipse", 128, 168, 15, 19, "#3A3F45"),
        ],
    ),
}


def svg_for(key: str) -> str:
    label, background, shapes = CHARACTERS[key]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
        f'width="{SIZE}" height="{SIZE}" role="img" aria-label="{label}">',
        f'<rect width="{SIZE}" height="{SIZE}" fill="{background}"/>',
    ]
    for shape in shapes:
        kind = shape[0]
        if kind == "circle":
            _, cx, cy, r, fill = shape
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>')
        elif kind == "ellipse":
            _, cx, cy, rx, ry, fill = shape
            parts.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}"/>')
        elif kind == "poly":
            _, points, fill = shape
            joined = " ".join(f"{x},{y}" for x, y in points)
            parts.append(f'<polygon points="{joined}" fill="{fill}"/>')
        elif kind == "line":
            _, x1, y1, x2, y2, width, stroke = shape
            parts.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                f'stroke-width="{width}" stroke-linecap="round"/>'
            )
        else:
            raise ValueError(f"unknown shape {kind}")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def webp_for(key: str) -> bytes:
    _, background, shapes = CHARACTERS[key]
    big = SIZE * SCALE
    image = Image.new("RGB", (big, big), background)
    draw = ImageDraw.Draw(image)

    def s(value: float) -> int:
        return round(value * SCALE)

    for shape in shapes:
        kind = shape[0]
        if kind == "circle":
            _, cx, cy, r, fill = shape
            draw.ellipse((s(cx - r), s(cy - r), s(cx + r), s(cy + r)), fill=fill)
        elif kind == "ellipse":
            _, cx, cy, rx, ry, fill = shape
            draw.ellipse((s(cx - rx), s(cy - ry), s(cx + rx), s(cy + ry)), fill=fill)
        elif kind == "poly":
            _, points, fill = shape
            draw.polygon([(s(x), s(y)) for x, y in points], fill=fill)
        elif kind == "line":
            _, x1, y1, x2, y2, width, stroke = shape
            draw.line((s(x1), s(y1), s(x2), s(y2)), fill=stroke, width=s(width))
            for x, y in ((x1, y1), (x2, y2)):
                half = width / 2
                draw.ellipse((s(x - half), s(y - half), s(x + half), s(y + half)), fill=stroke)
    small = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    small.save(out, "WEBP", quality=90, method=6)
    return out.getvalue()


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "characters": []}
    for key, (label, _, _) in CHARACTERS.items():
        (out_dir / f"{key}.svg").write_text(svg_for(key), encoding="utf-8")
        target = out_dir / f"{key}.webp"
        data = webp_for(key)
        if target.exists() and target.read_bytes() != data:
            # A shipped key never changes: a chosen character is stored as the
            # person's photo.
            raise SystemExit(
                f"{target} already ships with other bytes; give the new look a new key"
            )
        target.write_bytes(data)
        manifest["characters"].append({"key": key, "label": label})
        print(f"{key}: {len(data)} bytes")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    default = (
        Path(__file__).resolve().parents[2] / "packages/python/ac_platform/identity/characters"
    )
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else default)
