"""Stage art (title, end and framing cards, drawn by Chromium) and the ffmpeg steps that stitch a tutorial.

Picture: each shot sits in a phone or window frame on a 1920x1080 stage; the frame PNG is the whole stage with a
transparent rounded hole, laid over the clip. Every ffmpeg call is niced, idle-I/O, two threads, and waits while the
server's load average is above 4.
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
# Phone screen hole (390x844 viewport at 3x -> 1170x2532 clip) and desktop window hole (1440x900 at 2x).
PHONE = {"x": 424, "y": 70, "w": 434, "h": 940, "r": 46}
DESKTOP = {"x": 208, "y": 18, "w": 1504, "h": 940, "r": 18}
TEAL, TEAL2, INK = "#0f766e", "#0e7490", "#0f172a"
LOAD_LIMIT = float(os.environ.get("SXTUT_LOAD_LIMIT", "4"))


def safe_env() -> dict[str, str]:
    """The environment for child processes: never the ElevenLabs key (Chromium and ffmpeg do not need it)."""
    return {k: v for k, v in os.environ.items() if k != "ELEVENLABS_API_KEY"}


def wait_for_headroom() -> None:
    while os.getloadavg()[0] > LOAD_LIMIT:
        time.sleep(15)


def run(cmd: list[str]) -> None:
    wait_for_headroom()
    subprocess.run(["nice", "-n", "19", "ionice", "-c3", *cmd], check=True, env=safe_env(), stdin=subprocess.DEVNULL)


def fresh(out: Path, key: str) -> bool:
    """True when `out` was made from exactly these inputs before (its .key file matches), so it can be kept."""
    k = out.with_name(out.name + ".key")
    return out.exists() and k.exists() and k.read_text(encoding="utf-8") == key


def stamp(out: Path, key: str) -> None:
    out.with_name(out.name + ".key").write_text(key, encoding="utf-8")


def mtime(path: Path | None) -> str:
    return f"{path.stat().st_mtime_ns}" if path is not None and path.exists() else "-"


def probe_seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def brand_font_css(repo: Path) -> str:
    """Plus Jakarta Sans from the dev build, embedded so cards need no network and no installed font."""
    hits = sorted(glob.glob(str(repo / "apps/sales-xray-web/.next/**/media/plus-jakarta-sans-latin-wght-normal*.woff2"),
                        recursive=True))
    if not hits:
        return ""
    data = base64.b64encode(Path(hits[0]).read_bytes()).decode()
    return (f"@font-face{{font-family:'SXBrand';src:url(data:font/woff2;base64,{data}) format('woff2');"
            "font-weight:200 800;}")


def _hole_svg(h: dict) -> str:
    x, y, w, hh, r = h["x"], h["y"], h["w"], h["h"], h["r"]
    path = (f"M0 0H{W}V{H}H0Z M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}V{y + hh - r}"
            f"A{r} {r} 0 0 1 {x + w - r} {y + hh}H{x + r}A{r} {r} 0 0 1 {x} {y + hh - r}V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z")
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}'><path fill-rule='evenodd' d='{path}'/></svg>"
    return "url(\"data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode() + "\")"


def _page(font_css: str, body: str, extra_css: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{font_css}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{H}px;background:transparent;overflow:hidden;
  font-family:'SXBrand','Plus Jakarta Sans','DejaVu Sans',sans-serif;-webkit-font-smoothing:antialiased}}
.ground{{position:absolute;inset:0;background:
  radial-gradient(900px 600px at 85% 15%,rgba(14,116,144,.16),transparent 70%),
  radial-gradient(800px 700px at 10% 90%,rgba(15,118,110,.14),transparent 70%),
  linear-gradient(135deg,#f4f8f8,#eef2f7)}}
.mark{{position:absolute;right:72px;bottom:44px;font-weight:800;font-size:28px;letter-spacing:-.02em;color:{INK};opacity:.85}}
.mark b{{color:{TEAL}}}
{extra_css}</style></head><body>{body}</body></html>"""


def frame_html(font_css: str, device: str, label: str, step: str) -> str:
    h = PHONE if device == "phone" else DESKTOP
    mask = _hole_svg(h)
    bezel = 16 if device == "phone" else 2
    ring = (f"<div style='position:absolute;left:{h['x'] - bezel}px;top:{h['y'] - bezel}px;width:{h['w'] + 2 * bezel}px;"
            f"height:{h['h'] + 2 * bezel}px;border-radius:{h['r'] + bezel}px;border:{bezel}px solid "
            f"{'#111827' if device == 'phone' else 'rgba(15,23,42,.18)'};"
            f"box-shadow:0 30px 80px rgba(15,23,42,.28),0 8px 24px rgba(15,23,42,.14)'></div>")
    side = ""
    if device == "phone" and label:
        side = (f"<div style='position:absolute;left:1010px;top:250px;width:800px'>"
                f"<div style='font-weight:700;font-size:26px;color:{TEAL};letter-spacing:.02em;text-transform:uppercase'>{escape(step)}</div>"
                f"<div style='margin-top:18px;font-weight:800;font-size:72px;line-height:1.08;letter-spacing:-.03em;color:{INK}'>{escape(label)}</div>"
                f"<div style='margin-top:30px;width:120px;height:8px;border-radius:4px;background:linear-gradient(90deg,{TEAL},{TEAL2})'></div></div>")
    mark = "<div class='mark'>Sales <b>X-Ray</b></div>" if device == "phone" else ""
    return _page(font_css, f"<div class='ground' style='-webkit-mask:{mask};mask:{mask}'></div>{ring}{side}{mark}")


def title_html(font_css: str, number: str, title: str, kicker: str) -> str:
    return _page(font_css, f"""<div style="position:absolute;inset:0;background:
  radial-gradient(1100px 700px at 80% 10%,rgba(255,255,255,.16),transparent 60%),linear-gradient(135deg,{TEAL},{TEAL2} 60%,#155e75)"></div>
<div style="position:absolute;left:150px;top:300px;width:1500px;color:#fff">
  <div style="font-weight:700;font-size:30px;letter-spacing:.04em;text-transform:uppercase;opacity:.85">{escape(kicker)}</div>
  <div style="margin-top:22px;font-weight:800;font-size:96px;line-height:1.04;letter-spacing:-.035em">{escape(title)}</div>
  <div style="margin-top:44px;display:inline-block;padding:12px 26px;border-radius:999px;background:rgba(255,255,255,.16);
    font-weight:700;font-size:30px">Tutorial {escape(number)}</div>
</div>
<div style="position:absolute;right:80px;bottom:56px;font-weight:800;font-size:40px;color:#fff;letter-spacing:-.02em">Sales X-Ray</div>""")


def end_html(font_css: str, headline: str, next_title: str) -> str:
    nxt = (f"<div style='margin-top:40px;font-weight:600;font-size:34px;opacity:.9'>Next: {escape(next_title)}</div>"
           if next_title else "")
    return _page(font_css, f"""<div style="position:absolute;inset:0;background:linear-gradient(135deg,{TEAL2},{TEAL} 55%,#115e59)"></div>
<div style="position:absolute;left:150px;top:360px;width:1600px;color:#fff">
  <div style="font-weight:800;font-size:110px;letter-spacing:-.04em">{escape(headline)}</div>{nxt}
</div>
<div style="position:absolute;right:80px;bottom:56px;font-weight:800;font-size:40px;color:#fff;letter-spacing:-.02em">Sales X-Ray</div>""")


def render_cards(repo: Path, cards: list[dict], out: Path) -> None:
    """cards: [{name, html, transparent}] -> out/<name>.png through capture.mjs (one Chromium)."""
    out.mkdir(parents=True, exist_ok=True)
    keys = {c["name"]: hashlib.sha256(c["html"].encode()).hexdigest() for c in cards}
    cards = [c for c in cards if not fresh(out / f"{c['name']}.png", keys[c["name"]])]
    if not cards:
        return
    spec = out / "cards.json"
    spec.write_text(json.dumps(cards), encoding="utf-8")
    env = safe_env()
    wait_for_headroom()
    subprocess.run(["nice", "-n", "19", "ionice", "-c3", "node", str(repo / "scripts/tutorials/capture.mjs"), "cards",
                    str(spec), str(out)], check=True, cwd=repo, env=env, stdin=subprocess.DEVNULL)
    for c in cards:
        stamp(out / f"{c['name']}.png", keys[c["name"]])
    spec.unlink()


def segment_video(out: Path, dur: float, frame_png: Path | None, clip: Path | None, device: str,
                  card_png: Path | None = None) -> None:
    common = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-threads", "2", "-pix_fmt", "yuv420p", "-r", "30",
              "-an", "-movflags", "+faststart"]
    if card_png is not None:
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(card_png),
             "-t", f"{dur:.3f}", "-vf", f"scale={W}:{H},format=yuv420p", *common, str(out)])
        return
    h = PHONE if device == "phone" else DESKTOP
    fc = (f"[1:v]fps=30,scale={h['w']}:{h['h']}:flags=lanczos,setsar=1,tpad=stop_mode=clone:stop_duration={dur:.3f}[c];"
          f"[0:v][c]overlay={h['x']}:{h['y']}:eof_action=repeat[b];[2:v]format=rgba[f];"
          f"[b][f]overlay=0:0,trim=duration={dur:.3f},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x0f172a:s={W}x{H}:r=30:d={dur:.3f}",
         "-i", str(clip), "-loop", "1", "-framerate", "30", "-i", str(frame_png),
         "-filter_complex", fc, "-map", "[v]", "-t", f"{dur:.3f}", *common, str(out)])


def concat(parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])
    lst.unlink()


def voice_mix(lines: list[tuple[Path, float]], total: float, out: Path) -> None:
    """Places each voice line at its start second, then normalises the whole track to -16 LUFS."""
    args, chains = [], []
    for i, (p, at) in enumerate(lines):
        args += ["-i", str(p)]
        ms = int(round(at * 1000))
        chains.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(lines)))
    fc = ";".join(chains) + f";{mix}amix=inputs={len(lines)}:normalize=0:dropout_transition=0,apad=whole_dur={total:.3f}," \
         f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[out]"
    run(["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex", fc, "-map", "[out]", "-t", f"{total:.3f}",
         "-c:a", "pcm_s16le", str(out)])


def narrated(silent: Path, wav: Path, ass_file: Path | None, fonts: Path, out: Path) -> None:
    vf = ["-vf", f"ass={ass_file}:fontsdir={fonts}"] if ass_file else []
    vcodec = (["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-threads", "2", "-pix_fmt", "yuv420p"]
              if ass_file else ["-c:v", "copy"])
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav), *vf, *vcodec,
         "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)])
