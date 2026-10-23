"""Stage art (title, end and framing cards, drawn by Chromium) and the ffmpeg steps that stitch it.

Picture: each shot sits in a phone or window frame on a 1920x1080 stage; the frame PNG is the whole
stage with a transparent rounded hole, laid over the clip. Every ffmpeg call is niced, idle-I/O,
two threads, and waits while the server's load average is above 4.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import subprocess
import time
from html import escape
from pathlib import Path

W, H = 1920, 1080
# Phone screen hole (390x844 viewport at 3x: 1170x2532 clips); window hole (1440x900 at 2x).
PHONE = {"x": 424, "y": 70, "w": 434, "h": 940, "r": 46}
DESKTOP = {"x": 208, "y": 18, "w": 1504, "h": 940, "r": 18}
TEAL, TEAL2, INK = "#0f766e", "#0e7490", "#0f172a"
LOAD_LIMIT = float(os.environ.get("SXTUT_LOAD_LIMIT", "4"))
NICE = ["nice", "-n", "19", "ionice", "-c3"]


def safe_env() -> dict[str, str]:
    """The environment for child processes: never the ElevenLabs key (they do not need it)."""
    return {k: v for k, v in os.environ.items() if k != "ELEVENLABS_API_KEY"}


def wait_for_headroom() -> None:
    while os.getloadavg()[0] > LOAD_LIMIT:
        time.sleep(15)


def run(cmd: list[str]) -> None:
    # Fixed tool argument lists (ffmpeg, node) built here, never from outside input.
    wait_for_headroom()
    subprocess.run([*NICE, *cmd], check=True, env=safe_env(), stdin=subprocess.DEVNULL)  # noqa: S603


def fresh(out: Path, key: str) -> bool:
    """True when `out` was made from exactly these inputs before (its .key file matches)."""
    k = out.with_name(out.name + ".key")
    return out.exists() and k.exists() and k.read_text(encoding="utf-8") == key


def stamp(out: Path, key: str) -> None:
    out.with_name(out.name + ".key").write_text(key, encoding="utf-8")


def mtime(path: Path | None) -> str:
    return f"{path.stat().st_mtime_ns}" if path is not None and path.exists() else "-"


def probe_seconds(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout  # noqa: S603
    return float(json.loads(out)["format"]["duration"])


def brand_font_css(repo: Path) -> str:
    """Plus Jakarta Sans from the dev build, embedded so cards need no network or installed font."""
    pattern = "apps/sales-xray-web/.next/**/media/plus-jakarta-sans-latin-wght-normal*.woff2"
    hits = sorted(glob.glob(str(repo / pattern), recursive=True))
    if not hits:
        return ""
    data = base64.b64encode(Path(hits[0]).read_bytes()).decode()
    src = f"url(data:font/woff2;base64,{data}) format('woff2')"
    return f"@font-face{{font-family:'SXBrand';src:{src};font-weight:200 800;}}"


def _hole_svg(h: dict) -> str:
    x, y, w, hh, r = h["x"], h["y"], h["w"], h["h"], h["r"]
    arc = f"A{r} {r} 0 0 1"
    path = (
        f"M0 0H{W}V{H}H0Z M{x + r} {y}H{x + w - r}{arc} {x + w} {y + r}V{y + hh - r}"
        f"{arc} {x + w - r} {y + hh}H{x + r}{arc} {x} {y + hh - r}V{y + r}{arc} {x + r} {y}Z"
    )
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}'>"
        f"<path fill-rule='evenodd' d='{path}'/></svg>"
    )
    return 'url("data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode() + '")'


def _css(**props: str | int) -> str:
    """style="" text from keyword arguments: margin_top=18 -> margin-top:18px."""
    out = []
    for k, v in props.items():
        px = isinstance(v, int) and v != 0 and k not in ("font_weight", "z_index")
        value = f"{v}px" if px else str(v)
        out.append(f"{k.replace('_', '-')}:{value}")
    return ";".join(out)


PAGE_CSS = (
    "*{box-sizing:border-box;margin:0;padding:0}"
    f"html,body{{width:{W}px;height:{H}px;background:transparent;overflow:hidden;"
    "font-family:'SXBrand','Plus Jakarta Sans','DejaVu Sans',sans-serif;"
    "-webkit-font-smoothing:antialiased}"
    ".ground{position:absolute;inset:0;background:"
    "radial-gradient(900px 600px at 85% 15%,rgba(14,116,144,.16),transparent 70%),"
    "radial-gradient(800px 700px at 10% 90%,rgba(15,118,110,.14),transparent 70%),"
    "linear-gradient(135deg,#f4f8f8,#eef2f7)}"
    ".mark{position:absolute;right:72px;bottom:44px;font-weight:800;font-size:28px;"
    f"letter-spacing:-.02em;color:{INK};opacity:.85}}"
    f".mark b{{color:{TEAL}}}"
    ".brand{position:absolute;right:80px;bottom:56px;font-weight:800;font-size:40px;"
    "color:#fff;letter-spacing:-.02em}"
)


def _page(font_css: str, body: str) -> str:
    head = f'<meta charset="utf-8"><style>{font_css}{PAGE_CSS}</style>'
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def frame_html(font_css: str, device: str, label: str, step: str) -> str:
    h = PHONE if device == "phone" else DESKTOP
    mask = _hole_svg(h)
    bezel = 16 if device == "phone" else 2
    edge = "#111827" if device == "phone" else "rgba(15,23,42,.18)"
    ring = _css(
        position="absolute",
        left=h["x"] - bezel,
        top=h["y"] - bezel,
        width=h["w"] + 2 * bezel,
        height=h["h"] + 2 * bezel,
        border_radius=h["r"] + bezel,
        border=f"{bezel}px solid {edge}",
        box_shadow="0 30px 80px rgba(15,23,42,.28),0 8px 24px rgba(15,23,42,.14)",
    )
    side = ""
    if device == "phone" and label:
        kicker = _css(
            font_weight=700,
            font_size=26,
            color=TEAL,
            letter_spacing=".02em",
            text_transform="uppercase",
        )
        big = _css(
            margin_top=18,
            font_weight=800,
            font_size=72,
            line_height="1.08",
            letter_spacing="-.03em",
            color=INK,
        )
        bar = _css(
            margin_top=30,
            width=120,
            height=8,
            border_radius=4,
            background=f"linear-gradient(90deg,{TEAL},{TEAL2})",
        )
        side = (
            f"<div style='{_css(position='absolute', left=1010, top=250, width=800)}'>"
            f"<div style='{kicker}'>{escape(step)}</div>"
            f"<div style='{big}'>{escape(label)}</div><div style='{bar}'></div></div>"
        )
    mark = "<div class='mark'>Sales <b>X-Ray</b></div>" if device == "phone" else ""
    ground = f"<div class='ground' style='-webkit-mask:{mask};mask:{mask}'></div>"
    return _page(font_css, f"{ground}<div style='{ring}'></div>{side}{mark}")


def title_html(font_css: str, number: str, title: str, kicker: str) -> str:
    ground = _css(
        position="absolute",
        inset=0,
        background="radial-gradient(1100px 700px at 80% 10%,rgba(255,255,255,.16),"
        f"transparent 60%),linear-gradient(135deg,{TEAL},{TEAL2} 60%,#155e75)",
    )
    block = _css(position="absolute", left=150, top=300, width=1500, color="#fff")
    kick = _css(
        font_weight=700,
        font_size=30,
        letter_spacing=".04em",
        text_transform="uppercase",
        opacity=".85",
    )
    big = _css(
        margin_top=22,
        font_weight=800,
        font_size=96,
        line_height="1.04",
        letter_spacing="-.035em",
    )
    pill = _css(
        margin_top=44,
        display="inline-block",
        padding="12px 26px",
        border_radius=999,
        background="rgba(255,255,255,.16)",
        font_weight=700,
        font_size=30,
    )
    return _page(
        font_css,
        f"<div style='{ground}'></div><div style='{block}'>"
        f"<div style='{kick}'>{escape(kicker)}</div><div style='{big}'>{escape(title)}</div>"
        f"<div style='{pill}'>Tutorial {escape(number)}</div></div>"
        "<div class='brand'>Sales X-Ray</div>",
    )


def end_html(font_css: str, headline: str, next_title: str) -> str:
    ground = _css(
        position="absolute",
        inset=0,
        background=f"linear-gradient(135deg,{TEAL2},{TEAL} 55%,#115e59)",
    )
    block = _css(position="absolute", left=150, top=360, width=1600, color="#fff")
    big = _css(font_weight=800, font_size=110, letter_spacing="-.04em")
    nxt = ""
    if next_title:
        small = _css(margin_top=40, font_weight=600, font_size=34, opacity=".9")
        nxt = f"<div style='{small}'>Next: {escape(next_title)}</div>"
    return _page(
        font_css,
        f"<div style='{ground}'></div><div style='{block}'>"
        f"<div style='{big}'>{escape(headline)}</div>{nxt}</div>"
        "<div class='brand'>Sales X-Ray</div>",
    )


def render_cards(repo: Path, cards: list[dict], out: Path) -> None:
    """cards: [{name, html, transparent}] -> out/<name>.png through capture.mjs (one Chromium)."""
    out.mkdir(parents=True, exist_ok=True)
    keys = {c["name"]: hashlib.sha256(c["html"].encode()).hexdigest() for c in cards}
    cards = [c for c in cards if not fresh(out / f"{c['name']}.png", keys[c["name"]])]
    if not cards:
        return
    spec = out / "cards.json"
    spec.write_text(json.dumps(cards), encoding="utf-8")
    wait_for_headroom()
    cmd = [*NICE, "node", str(repo / "scripts/tutorials/capture.mjs"), "cards", str(spec), str(out)]
    subprocess.run(  # noqa: S603
        cmd, check=True, cwd=repo, env=safe_env(), stdin=subprocess.DEVNULL
    )
    for c in cards:
        stamp(out / f"{c['name']}.png", keys[c["name"]])
    spec.unlink()


X264 = ["-c:v", "libx264", "-preset", "medium", "-threads", "2", "-pix_fmt", "yuv420p"]


def segment_video(
    out: Path,
    dur: float,
    frame_png: Path | None,
    clip: Path | None,
    device: str,
    card_png: Path | None = None,
) -> None:
    common = [*X264, "-crf", "17", "-r", "30", "-an", "-movflags", "+faststart"]
    length = f"{dur:.3f}"
    if card_png is not None:
        still = ["-loop", "1", "-framerate", "30", "-i", str(card_png)]
        vf = f"scale={W}:{H},format=yuv420p"
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                *still,
                "-t",
                length,
                "-vf",
                vf,
                *common,
                str(out),
            ]
        )
        return
    h = PHONE if device == "phone" else DESKTOP
    fc = (
        f"[1:v]fps=30,scale={h['w']}:{h['h']}:flags=lanczos,setsar=1,"
        f"tpad=stop_mode=clone:stop_duration={length}[c];"
        f"[0:v][c]overlay={h['x']}:{h['y']}:eof_action=repeat[b];[2:v]format=rgba[f];"
        f"[b][f]overlay=0:0,trim=duration={length},format=yuv420p[v]"
    )
    inputs = [
        *("-f", "lavfi", "-i", f"color=c=0x0f172a:s={W}x{H}:r=30:d={length}"),
        *("-i", str(clip)),
        *("-loop", "1", "-framerate", "30", "-i", str(frame_png)),
    ]
    run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[v]"]
        + ["-t", length, *common, str(out)]
    )


def concat(parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
        + ["-c", "copy", "-movflags", "+faststart", str(out)]
    )
    lst.unlink()


def voice_mix(lines: list[tuple[Path, float]], total: float, out: Path) -> None:
    """Places each voice line at its start second, then normalises the track to -16 LUFS."""
    args, chains = [], []
    for i, (p, at) in enumerate(lines):
        args += ["-i", str(p)]
        ms = int(round(at * 1000))
        chains.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(lines)))
    fc = (
        ";".join(chains)
        + f";{mix}amix=inputs={len(lines)}:normalize=0:dropout_transition=0,"
        + f"apad=whole_dur={total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[out]"
    )
    run(
        ["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex", fc, "-map", "[out]"]
        + ["-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(out)]
    )


def narrated(silent: Path, wav: Path, ass_file: Path | None, fonts: Path, out: Path) -> None:
    vf = ["-vf", f"ass={ass_file}:fontsdir={fonts}"] if ass_file else []
    vcodec = [*X264, "-crf", "19"] if ass_file else ["-c:v", "copy"]
    run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav), *vf, *vcodec]
        + ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
    )
