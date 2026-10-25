"""Tutorials v2: brand B reels (9:16, 20-45 s) and YouTube tutorials (16:9, 2-5 min) from beat
storyboards (scripts/tutorials/v2/<id>.json, see README "v2").

A storyboard is a list of shots; a shot is one continuous screen recording; a beat is one
narration line and the actions seen while it plays. capture.mjs `take` records each shot and
logs when every beat starts and every tap or highlight lands, with its box. The editor here
cuts each language separately: each beat lasts as long as its own voice line needs (no dead
air), the clip is shifted so the tap lands as the narrator says it, the camera zooms toward
what is tapped, and the cards, chapter tags, hook and burned-in captions are brand B.

Per video it writes the MP4, captions in five tracks (en, hi, hi-Latn, mr, mr-Latn; SRT and
VTT), a transcript, a thumbnail (YouTube) and a manifest with title, description, chapters and tags.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import brand, camera, render, textprep, timing, tts

FPS = 30
LANGS = ("en", "hi", "mr")
LANG_LABEL = {"en": "English", "hi": "Hinglish", "mr": "Marathi-English"}
BADGE = {"en": "English", "hi": "Hinglish", "mr": "मराठी"}
TRACKS = ("en", "hi", "hi-Latn", "mr", "mr-Latn")
TRACK_LABEL = {
    "en": "English",
    "hi": "Hindi (Devanagari)",
    "hi-Latn": "Hinglish (Roman script)",
    "mr": "Marathi (Devanagari)",
    "mr-Latn": "Marathi (Roman script)",
}
FORMATS = {
    "reel": {"w": 1080, "h": 1920, "lead": 0.12, "tail": 0.22, "zmax": 1.6, "music": 0.16},
    "youtube": {"w": 1920, "h": 1080, "lead": 0.22, "tail": 0.38, "zmax": 1.9, "music": 0.11},
}
CARD = {"intro": (3.4, 0.7, 0.5), "outro": (4.0, 0.45, 0.8), "end": (1.8, 0.0, 0.0)}
REEL_CTA = {
    "en": "Full tutorial on our channel",
    "hi": "Poora tutorial hamare channel par",
    "mr": "Poorna tutorial aamchya channel var",
}
NEXT_LABEL = {"en": "Next tutorial", "hi": "Agla tutorial", "mr": "Pudhcha tutorial"}
X264 = ["-c:v", "libx264", "-preset", "medium", "-threads", "2", "-pix_fmt", "yuv420p"]


def frames(seconds: float) -> float:
    """Rounds up to whole frames."""
    return math.ceil(round(seconds * FPS, 6)) / FPS


def text(obj: dict, track: str) -> str:
    """A line in one track: en, hi, mr (what the voice reads; Devanagari for hi and mr) or hi-Latn,
    mr-Latn (the Roman-script caption)."""
    if track.endswith("-Latn"):
        return ((obj.get("latn") or {}).get(track[:2]) or "").strip()
    return ((obj.get("say") or {}).get(track) or "").strip()


def burned(lang: str) -> str:
    return "en" if lang == "en" else f"{lang}-Latn"


def local(obj: dict | str | None, lang: str) -> str:
    if isinstance(obj, dict):
        return obj.get(lang) or obj.get("en") or ""
    return obj or ""


def resolved(board: dict, names: dict) -> dict:
    """The storyboard as capture.mjs records it: every shot (and every screen a beat opens) gets the
    store demo names, coloured avatars and filled glass bars."""
    out = json.loads(json.dumps(board))
    store = [{"do": "frost"}]
    if board.get("store_names", True):
        store.insert(
            0, {"do": "marketing", "names": {**names, **board.get("names", {})}, "me": "VS"}
        )
    for shot in out["shots"]:
        shot["setup"] = [*shot.get("setup", []), *store]
        for beat in shot["beats"]:
            acts = []
            for a in beat.get("actions", []):
                acts.append(a)
                if a.get("do") == "goto":
                    acts += store
            beat["actions"] = acts
    return out


def library_index(root: Path) -> dict:
    """library.json and INDEX.md over every built video (for editors, YouTube and the website)."""
    videos = []
    for f in sorted((root / "library").glob("*/videos.json")):
        for v in json.loads(f.read_text(encoding="utf-8")):
            v = dict(v)
            v["folder"] = f"{f.parent.name}/{v['format']}"
            videos.append(v)
    index = {"version": "v2", "videos": videos}
    (root / "library" / "library.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines = ["# Sales X-Ray tutorials v2: asset library", ""]
    lines += [
        "Brand B. Each video has an MP4, captions (SRT and VTT in en, hi, hi-Latn, mr, mr-Latn), a "
        "transcript, a manifest (.json) and ready-to-paste YouTube text (.youtube.txt); the 16:9 "
        "tutorials also have a thumbnail. `editor/` holds the raw screen clips and every "
        "voice line.",
        "",
        "| Tutorial | Format | Language | Length | File |",
        "| --- | --- | --- | --- | --- |",
    ]
    for v in videos:
        lines.append(
            f"| {v['number']} {v['title']} | {v['format']} | {v['language_label']} | "
            f"{clock(v['seconds'])} | `{v['folder']}/{v['files']['video']}` |"
        )
    (root / "library" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index


# -------------------------------------------------------------------------------------------- voice


@dataclass
class Voiced:
    audio: Path
    spoken: str
    starts: list[float]
    ends: list[float]

    @property
    def speech(self) -> float:
        return float(self.ends[-1]) if self.ends else 0.0


def voice_line(say: str, lang: str, cast: dict, cache: Path, rules: dict) -> Voiced | None:
    if not say:
        return None
    spoken = textprep.spoken(say, lang, rules)
    language = cast["languages"][lang]
    line = tts.Line(
        text=spoken,
        lang=lang,
        language_code=language["language_code"],
        voice_id=language["voice_id"],
        model_id=cast["model_id"],
        output_format=cast["output_format"],
        voice_settings=tuple(sorted((k, float(v)) for k, v in cast["voice_settings"].items())),
    )
    audio, info = tts.synthesize(line, cache)
    al = info["alignment"]
    return Voiced(
        audio,
        spoken,
        [float(x) for x in al["character_start_times_seconds"]],
        [float(x) for x in al["character_end_times_seconds"]],
    )


def spoken_lines(board: dict) -> list[dict]:
    """Every text object that is spoken (intro, outro, hook, beats)."""
    out = [
        board.get("intro") or {},
        board.get("outro") or {},
        (board.get("reel") or {}).get("hook"),
    ]
    out += [b for s in board["shots"] for b in s["beats"]]
    out += [b["short"] for s in board["shots"] for b in s["beats"] if b.get("short")]
    return [o for o in out if o and o.get("say")]


def characters(board: dict, langs: list[str]) -> int:
    rules = textprep.load_pronounce()
    return sum(
        len(textprep.spoken(text(o, lang), lang, rules))
        for o in spoken_lines(board)
        for lang in langs
        if text(o, lang)
    )


def voice_all(board: dict, cast: dict, langs: list[str], cache: Path) -> dict:
    """{(id(obj), lang): Voiced}; cached lines cost nothing."""
    rules = textprep.load_pronounce()
    out = {}
    for o in spoken_lines(board):
        for lang in langs:
            v = voice_line(text(o, lang), lang, cast, cache, rules)
            if v:
                out[(id(o), lang)] = v
    return out


def word_times(words: list[str], v: Voiced) -> list[tuple[float, float]]:
    """Start and end of each caption word on the voice line. Exact when the caption has the
    same words as what was spoken; otherwise each word is placed by its share of the
    characters."""
    n = len(v.starts)
    if not words or not n:
        return []
    said = v.spoken.split()
    if len(said) == len(words) and n == len(v.spoken):
        out, pos = [], 0
        for w in said:
            a = v.spoken.find(w, pos)
            pos = a + len(w)
            out.append((v.starts[min(a, n - 1)], v.ends[min(pos - 1, n - 1)]))
        return out
    total = sum(len(w) + 1 for w in words) - 1
    out, acc = [], 0
    for w in words:
        a = acc / total
        b = (acc + len(w) - 1) / total
        acc += len(w) + 1
        out.append((v.starts[min(int(a * n), n - 1)], v.ends[min(int(b * n), n - 1)]))
    return out


# ----------------------------------------------------------------------------------------- sequence


@dataclass
class Item:
    kind: str  # intro | beat | step | hook | outro | end
    lines: dict  # the text object (say, latn) spoken over it
    spec: dict | None = None  # storyboard beat whose picture is shown
    shot: dict | None = None  # take manifest shot
    index: int = -1  # the beat's place in its shot (clip order)
    start: float = 0.0
    dur: float = 0.0
    voice: Voiced | None = None
    voice_at: float = 0.0
    src_in: float = 0.0
    src_out: float = 0.0
    head: float = 0.0
    keys: list = field(default_factory=list)


def sequence(board: dict, take: dict, fmt: str) -> list[Item]:
    """The items of one video. Shots with device "card" are step cards (things only a real phone
    shows); their beats become "step" items with no screen recording."""
    shots = {s["id"]: s for s in take["shots"]}
    where: dict[str, tuple[dict, dict | None, int]] = {}
    for sspec in board["shots"]:
        card = sspec["device"] == "card"
        if not card and sspec["id"] not in shots:
            raise KeyError(f"shot {sspec['id']} was not captured")
        for i, b in enumerate(sspec["beats"]):
            where[b["id"]] = (b, None if card else shots[sspec["id"]], i)

    def item(bid: str, lines: dict | None = None) -> Item:
        spec, shot, i = where[bid]
        return Item("step" if shot is None else "beat", lines or spec, spec, shot, i)

    order = [b["id"] for s in board["shots"] for b in s["beats"]]
    if fmt == "youtube":
        items = [Item("intro", board.get("intro") or {})]
        items += [item(bid) for bid in order if where[bid][0].get("youtube", True)]
        items.append(Item("outro", board.get("outro") or {}))
        return items
    reel = board["reel"]
    hook = reel["hook"]
    if hook.get("beat"):
        spec, shot, i = where[hook["beat"]]
        items = [Item("hook", hook, spec, shot, i)]
    else:
        # No screen to open on: a 9:16 title card carries the hook line.
        items = [Item("intro", hook)]
    for bid in order if reel.get("all") else reel["beats"]:
        # A beat may carry a shorter line for reels ("short": {"say", "latn"}).
        items.append(item(bid, where[bid][0].get("short")))
    items.append(Item("end", {}))
    return items


def _contiguous(a: Item, b: Item) -> bool:
    return a.kind == "beat" and b.kind == "beat" and a.shot is b.shot and b.index == a.index + 1


def _sync(spec: dict | None, lang: str, v: Voiced | None) -> float:
    word = ((spec or {}).get("sync") or {}).get(lang)
    if not word or not v:
        return 0.0
    i = v.spoken.lower().find(word.lower())
    return v.starts[min(i, len(v.starts) - 1)] if i >= 0 and v.starts else 0.0


ZOOM_KINDS = {"tap", "highlight", "focus", "type", "fill", "paste", "select", "hover"}


# Device frames (owner, 25 Oct 2026): shots captured on "phone2" (9:19.5) or "laptop" (16:10) sit in
# a drawn phone or laptop (brand.device_stage_html); reels keep a caption band above the phone and
# the camera moves only in the picture under it.
# (format, device) -> (stage art, width, height, hole)
FRAMED = {
    ("youtube", "phone2"): ("stage-phone2", brand.STAGE_W, brand.STAGE_H, brand.YT_PHONE_HOLE),
    ("youtube", "laptop"): ("stage-laptop", brand.STAGE_W, brand.STAGE_H, brand.YT_LAPTOP_HOLE),
    ("reel", "phone2"): ("reel-stage", brand.REEL_W, brand.REEL_PIC_H, brand.REEL_PHONE_HOLE),
}


def stage_art(fmt: str, shot: dict | None) -> list[str]:
    """The drawn art a recorded item sits in: its device stage, and the caption band in reels."""
    framed = FRAMED.get((fmt, shot["device"])) if shot else None
    if framed:
        return [framed[0], "band"] if fmt == "reel" else [framed[0]]
    return ["stage"] if fmt == "youtube" and shot and shot["device"] != "wide" else []


def geometry(fmt: str, shot: dict) -> tuple[int, int, object]:
    """The frame the camera moves in (width, height) and a box mapper from clip pixels into it."""
    framed = FRAMED.get((fmt, shot["device"]))
    if framed or (fmt == "youtube" and shot["device"] != "wide"):
        _, sw, sh, h = framed or ("stage", brand.STAGE_W, brand.STAGE_H, brand.PHONE_HOLE)
        s = h["w"] / shot["width"]

        def to_stage(b: dict) -> dict:
            return {
                "x": h["x"] + b["x"] * s,
                "y": h["y"] + b["y"] * s,
                "w": b["w"] * s,
                "h": b["h"] * s,
            }

        return sw, sh, to_stage
    return shot["width"], shot["height"], lambda b: b


def lay_out(items: list[Item], fmt: str, lang: str, voices: dict) -> float:
    """Sets every item's start, length, source span, voice time and camera; returns the total."""
    f = FORMATS[fmt]
    t = 0.0
    for it in items:
        it.voice = voices.get((id(it.lines), lang)) if it.lines else None
        speech = it.voice.speech if it.voice else 0.0
        if it.kind in CARD:
            least, at, after = CARD[it.kind]
            it.voice_at = at
            it.dur = frames(max(least, at + speech + after if it.voice else 0.0))
        elif it.kind == "step":
            # The card animates in for a moment, then holds while the line is read.
            it.voice_at = f["lead"] + 0.25
            it.dur = frames(max(2.4, it.voice_at + speech + f["tail"] + 0.2))
        else:
            tb = it.shot["beats"][it.index]
            evs = tb["events"]
            desired = f["lead"] + _sync(it.spec if it.kind == "beat" else None, lang, it.voice)
            if evs:
                # The key event (marked "key", else the first) lands as the narrator says the sync
                # word; the clip is trimmed or held at the start for that, never past an event.
                key = next((e for e in evs if e.get("key")), evs[0])
                # A tap needs a moment on screen first: the viewer sees what will be tapped.
                desired += 0.5 if key["do"] == "tap" else 0.0
                k = key["t"] - tb["t0"]
                it.src_in = tb["t0"] + max(0.0, k - desired)
                it.src_in = max(tb["t0"], min(it.src_in, evs[0]["t"] - 0.15))
                it.head = max(0.0, desired - (key["t"] - it.src_in))
                last = evs[-1]
                settle = 0.9 if last["do"] in ("tap", "goto", "select", "paste", "type") else 0.55
                need_vis = it.head + (last["t"] - it.src_in) + settle
            else:
                it.src_in, it.head, need_vis = tb["t0"], 0.0, 1.0
            it.voice_at = f["lead"]
            it.dur = frames(max(f["lead"] + speech + f["tail"], need_vis, 1.2))
            later = [e["t"] for b in it.shot["beats"][it.index + 1 :] for e in b["events"]]
            limit = (min(later) - 0.05) if later else it.shot["seconds"]
            it.src_out = max(it.src_in + 0.1, min(it.src_in + it.dur - it.head, limit))
        it.start = t
        t += it.dur
    _plan_camera(items, fmt)
    return t


def _first_focus(it: Item, fmt: str) -> camera.State | None:
    w, h, to = geometry(fmt, it.shot)
    for e in it.shot["beats"][it.index]["events"]:
        if e.get("box") and e["do"] in ZOOM_KINDS and e.get("zoom") is not False:
            return camera.focus(to(e["box"]), w, h, FORMATS[fmt]["zmax"])
    return None


def _plan_camera(items: list[Item], fmt: str) -> None:
    prev_end: camera.State | None = None
    for n, it in enumerate(items):
        if it.kind in CARD or it.kind == "step":
            prev_end = None
            continue
        w, h, to = geometry(fmt, it.shot)
        rest = camera.full(w, h)
        prev = items[n - 1] if n else None
        start = prev_end if (prev and prev_end and _contiguous(prev, it)) else rest
        nxt = items[n + 1] if n + 1 < len(items) else None
        carry = bool(nxt and _contiguous(it, nxt) and _first_focus(nxt, fmt))
        evs = []
        for e in it.shot["beats"][it.index]["events"]:
            at = it.head + (e["t"] - it.src_in)
            st = None
            if e.get("box") and e["do"] in ZOOM_KINDS and e.get("zoom") is not False:
                st = camera.focus(to(e["box"]), w, h, FORMATS[fmt]["zmax"]) or rest
            evs.append((at, e["do"], st))
        it.keys = camera.plan(it.dur, evs, start, rest, None if carry else rest)
        prev_end = it.keys[-1][1]


# ------------------------------------------------------------------------------------------ picture


def _ffmpeg(args: list[str]) -> None:
    render.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args])


def _key(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:20]


def render_item(it: Item, fmt: str, take_dir: Path, art: dict, out: Path) -> None:
    f = FORMATS[fmt]
    n = round(it.dur * FPS)
    # Pieces are encoded again in the final pass: fast and nearly lossless here.
    fast = [x if x != "medium" else "veryfast" for x in X264]
    tail = ["-frames:v", str(n), *fast, "-crf", "12", "-r", str(FPS), "-an", str(out)]
    if it.kind in CARD or it.kind == "step":
        card = art[art_key(it)]
        fc = f"[0:v]fps={FPS},tpad=stop_mode=clone:stop_duration={it.dur + 1:.3f},format=yuv420p[v]"
        _ffmpeg(["-i", str(card), "-filter_complex", fc, "-map", "[v]", *tail])
        return
    clip = take_dir / it.shot["clip"]
    hold = it.dur - it.head - (it.src_out - it.src_in) + 1.0
    pre = (
        f"trim=start={it.src_in:.3f}:end={it.src_out:.3f},setpts=PTS-STARTPTS,fps={FPS},"
        f"tpad=start_mode=clone:start_duration={it.head:.3f}:"
        f"stop_mode=clone:stop_duration={hold:.3f}"
    )
    w, h, _ = geometry(fmt, it.shot)
    framed = FRAMED.get((fmt, it.shot["device"]))
    band = bool(framed) and fmt == "reel"
    zp = camera.zoompan(it.keys, w, h, f["w"], brand.REEL_PIC_H if band else f["h"], FPS)
    if framed or (fmt == "youtube" and it.shot["device"] != "wide"):
        name, _, _, ph = framed or ("stage", 0, 0, brand.PHONE_HOLE)
        loop = ["-loop", "1", "-framerate", str(FPS), "-t", f"{it.dur + 1:.3f}", "-i"]
        fc = (
            f"[1:v]{pre},scale={ph['w']}:{ph['h']}:flags=lanczos,setsar=1[c];"
            f"color=c=0x0B4A44:s={w}x{h}:r={FPS}:d={it.dur + 1:.3f}[g];"
            f"[g][c]overlay={ph['x']}:{ph['y']}[b];[0:v]format=rgba[st];"
            f"[b][st]overlay=0:0,{zp}"
        )
        inputs = [*loop, str(art[name]), "-i", str(clip)]
        if band:
            # The caption band sits above the picture; finish() burns the captions into it.
            fc += f",pad={f['w']}:{f['h']}:0:{brand.REEL_BAND}[z];[z][2:v]overlay=0:0"
            inputs += [*loop, str(art["band"])]
        fc += ",format=yuv420p[v]"
    else:
        fc = f"[0:v]{pre},scale={w}:{h},setsar=1,{zp},format=yuv420p[v]"
        inputs = ["-i", str(clip)]
    _ffmpeg([*inputs, "-filter_complex", fc, "-map", "[v]", *tail])


def art_key(it: Item) -> str:
    """Which drawn card an item without a screen recording shows."""
    return f"step-{it.spec['id']}" if it.kind == "step" else it.kind


def picture(items: list[Item], fmt: str, take_dir: Path, art: dict, work: Path) -> Path:
    parts = []
    for i, it in enumerate(items):
        part = work / f"p{i:02d}-{it.kind}.mp4"
        key = _key(
            fmt,
            it.kind,
            round(it.dur, 3),
            round(it.src_in, 3),
            round(it.src_out, 3),
            round(it.head, 3),
            [(round(t, 3), s.z, s.cx, s.cy) for t, s in it.keys],
            render.mtime(take_dir / it.shot["clip"]) if it.shot else "",
            render.mtime(art.get(art_key(it))) if it.shot is None else "",
            render.mtime(art.get("stage")),
            # Framed shots also depend on their device stage and band (others keep their old keys).
            *(
                [render.mtime(art.get(n)) for n in stage_art(fmt, it.shot)]
                if it.shot and FRAMED.get((fmt, it.shot["device"]))
                else []
            ),
        )
        if not render.fresh(part, key):
            render_item(it, fmt, take_dir, art, part)
            render.stamp(part, key)
        parts.append(part)
    out = work / "picture.mp4"
    key = "|".join(f"{p.name}:{render.mtime(p)}" for p in parts)
    if not render.fresh(out, key):
        render.concat(parts, out)
        render.stamp(out, key)
    return out


# -------------------------------------------------------------------------------------------- audio


def mix(items: list[Item], total: float, music: Path | None, gain: float, out: Path) -> None:
    lines = [(it.voice.audio, it.start + it.voice_at) for it in items if it.voice]
    args, chains = [], []
    for i, (p, at) in enumerate(lines):
        args += ["-i", str(p)]
        ms = int(round(at * 1000))
        chains.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{i}]"
        )
    voice = "".join(f"[a{i}]" for i in range(len(lines)))
    fc = ";".join(chains) + (
        f";{voice}amix=inputs={len(lines)}:normalize=0:dropout_transition=0,"
        f"apad=whole_dur={total:.3f}[vo]"
    )
    if music is not None and music.exists():
        m = len(lines)
        args += ["-stream_loop", "-1", "-i", str(music)]
        fade_at = max(0.0, total - 1.6)
        fc += (
            f";[{m}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=end={total:.3f},"
            f"afade=t=in:d=0.6,afade=t=out:st={fade_at:.3f}:d=1.6,volume={gain}[mu];"
            "[vo]asplit[v1][v2];[mu][v2]sidechaincompress=threshold=0.02:ratio=6:attack=20:"
            "release=400[du];[v1][du]amix=inputs=2:normalize=0[mx]"
        )
        last = "[mx]"
    else:
        last = "[vo]"
    fc += f";{last}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[out]"
    _ffmpeg(
        [
            *args,
            "-filter_complex",
            fc,
            "-map",
            "[out]",
            "-t",
            f"{total:.3f}",
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
    )


# -------------------------------------------------------------------------------- captions and text


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[tuple[str, float, float]] = field(default_factory=list)


def item_words(it: Item, track: str) -> list[tuple[str, float, float]]:
    line = text(it.lines, track)
    if not line or not it.voice:
        return []
    words = line.split()
    base = it.start + it.voice_at
    return [
        (w, base + a, base + b)
        for w, (a, b) in zip(words, word_times(words, it.voice), strict=True)
    ]


def track_cues(items: list[Item], track: str) -> list[Cue]:
    """Sentence-sized cues (at most two lines of 42 characters) for SRT and VTT."""
    cues: list[Cue] = []
    for it in items:
        words = item_words(it, track)
        if not words:
            continue
        i = 0
        for piece in timing.balanced(" ".join(w for w, _, _ in words)):
            k = len(piece.split())
            chunk = words[i : i + k]
            i += k
            cues.append(Cue(chunk[0][1], chunk[-1][2] + 0.2, timing.two_lines(piece), chunk))
    for a, b in zip(cues, cues[1:], strict=False):
        if b.start - a.end < 0.35:
            a.end = b.start
    for c in cues:
        c.end = max(c.end, c.start + 0.8)
    for a, b in zip(cues, cues[1:], strict=False):
        a.end = min(a.end, b.start)
    return cues


def srt(cues: list[Cue]) -> str:
    return "".join(
        f"{i}\n{timing.tc(c.start)} --> {timing.tc(c.end)}\n{c.text}\n\n"
        for i, c in enumerate(cues, 1)
    )


def vtt(cues: list[Cue]) -> str:
    body = "".join(
        f"{timing.tc(c.start, '.')} --> {timing.tc(c.end, '.')}\n{c.text}\n\n" for c in cues
    )
    return "WEBVTT\n\n" + body


CAPTION_BANDS = {
    "Reel": (1240, 1545),
    "ReelTop": (270, 575),
}  # y ranges the two caption spots cover


def caption_spot(it: Item) -> str:
    """Bottom captions, unless what the beat points at would sit under them; then the top. Framed
    shots have the caption band above the phone."""
    if it.shot and FRAMED.get(("reel", it.shot["device"])):
        return "Band"
    if it.kind != "beat" or not it.keys:
        return "Reel"
    w, h, to = geometry("reel", it.shot)
    f = FORMATS["reel"]
    hits = {name: False for name in CAPTION_BANDS}
    for e in it.shot["beats"][it.index]["events"]:
        if not e.get("box") or e["do"] not in ZOOM_KINDS:
            continue
        t = it.head + (e["t"] - it.src_in) + 0.5
        _, y, _, bh = camera.on_screen(to(e["box"]), camera.at(it.keys, t), w, h, f["w"], f["h"])
        for name, (top, bottom) in CAPTION_BANDS.items():
            hits[name] |= y < bottom and y + bh > top
    return "ReelTop" if hits["Reel"] and not hits["ReelTop"] else "Reel"


def reel_ass(items: list[Item], track: str, font: str) -> str:
    """Burned-in reel captions: a few words at a time, big and bold, the spoken word in Mint, at the
    bottom unless that would cover what the beat points at."""
    groups: list[list[tuple[str, float, float]]] = []
    spots: list[str] = []
    for it in items:
        spot = caption_spot(it)
        cur: list[tuple[str, float, float]] = []
        for w in item_words(it, track):
            if cur and (len(" ".join(x for x, _, _ in cur)) + 1 + len(w[0]) > 22):
                groups.append(cur)
                spots.append(spot)
                cur = []
            cur.append(w)
            if w[0][-1] in ".?!:" and len(" ".join(x for x, _, _ in cur)) > 8:
                groups.append(cur)
                spots.append(spot)
                cur = []
        if cur:
            groups.append(cur)
            spots.append(spot)
    events = []
    for gi, (g, spot) in enumerate(zip(groups, spots, strict=True)):
        end = g[-1][2] + 0.25
        if gi + 1 < len(groups):
            end = min(end, groups[gi + 1][0][1]) if groups[gi + 1][0][1] - end < 0.4 else end
        for wi, (_, ws, _) in enumerate(g):
            a = g[0][1] if wi == 0 else ws
            b = g[wi + 1][1] if wi + 1 < len(g) else end
            if b <= a:
                continue
            shown = " ".join(
                "{\\c&H00B0EB3D&}" + w + "{\\c&H00FFFFFF&}" if j == wi else w
                for j, (w, _, _) in enumerate(g)
            )
            events.append(
                f"Dialogue: 0,{timing.ass_tc(a)},{timing.ass_tc(b)},{spot},,0,0,0,,{shown}"
            )
    fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    # White on a Deep teal box (BorderStyle 3: the outline colour fills the box, padded by Outline).
    look = f"{font},132,&H00FFFFFF,&H00FFFFFF,&H14444A0B,&H00000000,-1,0,0,0,100,100,0,0,3,20,0"
    style = f"Style: Reel,{look},2,100,100,420,1\nStyle: ReelTop,{look},8,100,100,290,1"
    if "Band" in spots:
        # In the band above a framed phone: one line, centred in the band's REEL_BAND pixels.
        style += f"\nStyle: Band,{look},8,90,90,{(brand.REEL_BAND - 150) // 2},1"
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        fmt,
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    return "\n".join(head + events) + "\n"


def chapters(board: dict, items: list[Item], lang: str, total: float) -> list[tuple[float, str]]:
    """YouTube chapters: the first starts at 0:00 and every chapter lasts at least 10 seconds."""
    titles = {c["id"]: local(c["title"], lang) for c in board.get("chapters", [])}
    out: list[tuple[float, str]] = []
    seen = set()
    for it in items:
        cid = (it.spec or {}).get("chapter") if it.kind in ("beat", "step") else None
        if cid and cid not in seen:
            seen.add(cid)
            out.append((0.0 if not out else it.start, titles.get(cid, cid)))
    merged: list[tuple[float, str]] = []
    for t, name in out:
        if merged and t - merged[-1][0] < 10:
            continue
        merged.append((t, name))
    while len(merged) > 1 and total - merged[-1][0] < 10:
        merged.pop()
    return merged


def clock(t: float) -> str:
    s = int(t)
    return f"{s // 60}:{s % 60:02d}"


def transcript(
    board: dict, items: list[Item], track: str, fmt: str, lang: str, chaps: list[tuple[float, str]]
) -> str:
    title = local(board["title"], lang)
    lines = [
        f"Sales X-Ray tutorial {board['number']}: {title}",
        f"{TRACK_LABEL[track]} · {fmt}",
        "",
    ]
    marks = dict(chaps)
    para: list[str] = []
    for it in items:
        if it.start in marks and fmt == "youtube":
            if para:
                lines += [" ".join(para), ""]
                para = []
            lines.append(f"[{clock(it.start)}] {marks[it.start]}")
        line = text(it.lines, track)
        if line:
            para.append(line)
    if para:
        lines.append(" ".join(para))
    return "\n".join(lines).strip() + "\n"


# -------------------------------------------------------------------------------------------- build


def art_for(
    repo: Path, kit: brand.Kit, board: dict, fmt: str, lang: str, work: Path
) -> dict[str, Path]:
    """Stage, motion cards, chapter tags and the hook, drawn by Chromium (cached by their HTML)."""
    art: dict[str, Path] = {}
    stills, motion = [], []
    if fmt == "youtube":
        stills.append(
            {
                "name": "stage",
                "html": brand.stage_html(kit),
                "width": brand.STAGE_W,
                "height": brand.STAGE_H,
                "transparent": True,
            }
        )
        nxt = board.get("next") or {}
        motion.append(
            {
                "name": f"intro-{lang}",
                "seconds": 3.4,
                # No number on the cards: the list's order can change without new renders.
                "html": brand.intro_html(
                    kit, "", local(board["title"], lang), "Sales X-Ray tutorial"
                ),
            }
        )
        motion.append(
            {
                "name": f"outro-{lang}",
                "seconds": 4.0,
                "html": brand.outro_html(
                    kit,
                    local((board.get("outro") or {}).get("headline"), lang),
                    NEXT_LABEL[lang],
                    local(nxt.get("title"), lang),
                ),
            }
        )
        for i, c in enumerate(board.get("chapters", []), 1):
            stills.append(
                {
                    "name": f"lt-{lang}-{c['id']}",
                    "transparent": True,
                    "width": 1400,
                    "height": 140,
                    "html": brand.lower_third_html(kit, i, local(c["title"], lang)),
                }
            )
    else:
        hook = board["reel"]["hook"]
        if hook.get("beat"):
            stills.append(
                {
                    "name": f"hook-{lang}",
                    "transparent": True,
                    "width": 1080,
                    "height": 420,
                    "html": brand.hook_html(
                        kit, local(hook["text"], lang), local(hook.get("accent"), lang)
                    ),
                }
            )
        else:
            motion.append(
                {
                    "name": f"rintro-{lang}",
                    "key": "intro",
                    "seconds": 2.4,
                    "width": 1080,
                    "height": 1920,
                    "html": brand.reel_intro_html(
                        kit, "", local(hook.get("text") or board["title"], lang), "Sales X-Ray"
                    ),
                }
            )
        motion.append(
            {
                "name": f"end-{lang}",
                "seconds": 1.8,
                "width": 1080,
                "height": 1920,
                "html": brand.reel_end_html(
                    kit,
                    local(board["title"], lang),
                    # Tester how-tos go out on WhatsApp; there is no channel to point at.
                    brand.TAGLINE if board.get("kind") == "tester" else REEL_CTA[lang],
                ),
            }
        )
    w, h = FORMATS[fmt]["w"], FORMATS[fmt]["h"]
    for s in board["shots"]:
        if s["device"] != "card":
            continue
        for beat in s["beats"]:
            card = beat.get("card") or {}
            chips = [local(c, lang) for c in card.get("chips", [])]
            motion.append(
                {
                    "name": f"step-{fmt}-{beat['id']}-{lang}",
                    "key": f"step-{beat['id']}",
                    "seconds": 1.4,
                    "width": w,
                    "height": h,
                    "html": brand.step_html(
                        kit,
                        w,
                        h,
                        local(card.get("step"), lang),
                        local(card.get("title"), lang),
                        chips,
                        card.get("icon", "phone"),
                    ),
                }
            )
    # Device frames for the shots that use them (phone footage joins the phone in framed boards).
    devices = {
        "phone2" if s["device"] == "footage" and board.get("frames") else s["device"]
        for s in board["shots"]
    }
    for (f, device), (name, sw, sh, hole) in FRAMED.items():
        if f != fmt or device not in devices:
            continue
        kind = "phone" if device == "phone2" else "laptop"
        html = brand.device_stage_html(kit, sw, sh, hole, kind)
        stills.append({"name": name, "html": html, "width": sw, "height": sh, "transparent": True})
        if fmt == "reel":
            html = brand.reel_band_html(kit)
            stills.append(
                {"name": "band", "html": html, "width": brand.REEL_W, "height": brand.REEL_BAND}
            )
    cards_dir = work.parent / "art"
    render.render_cards(repo, stills, cards_dir)
    render_motion(repo, motion, cards_dir)
    for c in stills:
        art[c["name"].split("-")[0] if c["name"] == "stage" else c["name"]] = (
            cards_dir / f"{c['name']}.png"
        )
    for c in motion:
        art[c.get("key") or c["name"].rsplit("-", 1)[0]] = cards_dir / f"{c['name']}.mp4"
    return art


def render_motion(repo: Path, cards: list[dict], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    keys = {
        c["name"]: _key(c["html"], c.get("seconds"), c.get("width"), c.get("height")) for c in cards
    }
    todo = [c for c in cards if not render.fresh(out / f"{c['name']}.mp4", keys[c["name"]])]
    if not todo:
        return
    spec = out / "motion.json"
    spec.write_text(json.dumps(todo), encoding="utf-8")
    render.wait_for_headroom()
    cmd = [
        *render.NICE,
        "node",
        str(repo / "scripts/tutorials/capture.mjs"),
        "motion",
        str(spec),
        str(out),
    ]
    subprocess.run(cmd, check=True, cwd=repo, env=render.safe_env(), stdin=subprocess.DEVNULL)  # noqa: S603
    for c in todo:
        render.stamp(out / f"{c['name']}.mp4", keys[c["name"]])
    spec.unlink()


def finish(
    pic: Path,
    wav: Path,
    items: list[Item],
    fmt: str,
    lang: str,
    art: dict[str, Path],
    board: dict,
    fonts: Path,
    work: Path,
    out: Path,
) -> None:
    """Overlays (chapter tags or the reel hook), burned-in reel captions, and the sound."""
    inputs = ["-i", str(pic), "-i", str(wav)]
    chain, label, k = [], "[0:v]", 2
    if fmt == "youtube":
        first: dict[str, Item] = {}
        for it in items:
            cid = (it.spec or {}).get("chapter") if it.kind in ("beat", "step") else None
            if cid and cid not in first:
                first[cid] = it
        for cid, it in first.items():
            png = art.get(f"lt-{lang}-{cid}")
            if not png:
                continue
            t0, t1 = it.start + 0.35, it.start + 0.35 + 3.4
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{t1 - t0:.3f}", "-i", str(png)]
            u = f"clip((t-{t0:.3f})/0.45,0,1)"
            chain.append(
                f"[{k}:v]format=rgba,setpts=PTS+{t0:.3f}/TB,fade=t=in:st={t0:.3f}:d=0.35:alpha=1,"
                f"fade=t=out:st={t1 - 0.35:.3f}:d=0.35:alpha=1[o{k}];"
                f"{label}[o{k}]overlay=x='72-80*(1-{u}*{u}*(3-2*{u}))':y=916:eof_action=pass[b{k}]"
            )
            label = f"[b{k}]"
            k += 1
    else:
        hook = items[0]
        png = art.get(f"hook-{lang}") if hook.kind == "hook" else None
        if png:
            t0, t1 = 0.1, max(1.2, hook.dur - 0.05)
            # Framed reels keep the band for captions: the hook title goes over the phone instead.
            y = (
                brand.REEL_BAND + 60
                if hook.shot and FRAMED.get(("reel", hook.shot["device"]))
                else 150
            )
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{t1 - t0:.3f}", "-i", str(png)]
            chain.append(
                f"[{k}:v]format=rgba,setpts=PTS+{t0:.3f}/TB,fade=t=in:st={t0:.3f}:d=0.2:alpha=1,"
                f"fade=t=out:st={t1 - 0.25:.3f}:d=0.25:alpha=1[o{k}];"
                f"{label}[o{k}]overlay=x=0:y={y}:eof_action=pass[b{k}]"
            )
            label = f"[b{k}]"
            k += 1
        ass_file = work / f"captions-{lang}.ass"
        ass_file.write_text(reel_ass(items, burned(lang), "Hind"), encoding="utf-8")
        chain.append(f"{label}ass={ass_file}:fontsdir={fonts / 'hind'}[c]")
        label = "[c]"
    fc = ";".join(chain) + (";" if chain else "") + f"{label}format=yuv420p[v]"
    _ffmpeg(
        [
            *inputs,
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            "1:a",
            *X264,
            "-crf",
            "18",
            "-r",
            str(FPS),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def thumbnail(
    repo: Path, kit: brand.Kit, board: dict, take: dict, take_dir: Path, lang: str, work: Path
) -> Path | None:
    th = board.get("thumb") or {}
    shots = {s["id"]: s for s in take["shots"]}
    for shot in shots.values():
        beats = {b["id"]: b for b in shot["beats"]}
        if th.get("beat") in beats:
            b = beats[th["beat"]]
            screen = work.parent / "art" / f"thumb-screen-{th['beat']}.png"
            if not screen.exists():
                at = max(0.0, min(shot["seconds"] - 0.1, b["t1"] - 0.2))
                _ffmpeg(
                    [
                        "-ss",
                        f"{at:.3f}",
                        "-i",
                        str(take_dir / shot["clip"]),
                        "-frames:v",
                        "1",
                        str(screen),
                    ]
                )
            card = {
                "name": f"thumb-{lang}",
                "width": 1280,
                "height": 720,
                "jpeg": True,
                "html": brand.thumbnail_html(
                    kit,
                    local(th.get("text") or board["title"], lang),
                    local(th.get("accent"), lang),
                    BADGE[lang],
                    screen,
                ),
            }
            render.render_cards(repo, [card], work.parent / "art")
            return work.parent / "art" / f"thumb-{lang}.jpg"
    return None


# ------------------------------------------------------------------------------------ phone footage

# Shots with device "footage" are real phone recordings (screens only a phone shows). The source
# files stay on ac under <out>/v2/footage, never in git. "footage": {"file", "size": [w, h], "from",
# "to", "crop": [top, bottom], "blur": [{"box": [x, y, w, h], "from"?, "to"?}]} in source pixels and
# seconds; each beat's "phone": {"at", "events": [{"do", "at", "box", "key"?, "what"?}]}. The cut
# is padded to the reel frame with the app's black and gets mint tap rings, so the build treats it
# like a take.
REEL_W, REEL_H = 1170, 2078
FRAME_PHONE = (1080, 2340)  # framed boards ("frames": true): footage keeps the phone's 9:19.5
RING = 150


def footage_frame(
    f: dict, target: tuple[int, int] = (REEL_W, REEL_H)
) -> tuple[int, int, int, int, int, int, float]:
    """(left, top, cropped width, cropped height, side pad, top pad, scale to the target frame) for
    a portrait recording; "crop" is [top, bottom] or [top, bottom, left, right] (black bars, status
    bar). A cut narrower than the target is padded at the sides; a wider one (a 9:19.5 phone with
    its status bar cropped, in the 9:19.5 frame) gets black where the bars were."""
    w, h = f["size"]
    top, bottom, left, right = [*f.get("crop", []), 0, 0, 0, 0][:4]
    cw, ch = w - left - right, h - top - bottom
    tw, th = target
    full = round(ch * tw / th)
    if full >= cw:
        return left, top, cw, ch, (full - cw) // 2, 0, tw / full
    full_h = round(cw * th / tw)
    share = top / (top + bottom) if top + bottom else 0.5
    return left, top, cw, ch, 0, round((full_h - ch) * share), tw / cw


def footage_target(board: dict) -> tuple[int, int]:
    return FRAME_PHONE if board.get("frames") else (REEL_W, REEL_H)


def footage_shot(board: dict, sspec: dict) -> dict:
    """The take entry for a footage shot: times from the cut's start, boxes in reel pixels."""
    f = sspec["footage"]
    left, top, _, _, pad, pad_top, s = footage_frame(f, footage_target(board))

    def box(b: list[float]) -> dict:
        x, y, w, h = b
        return {"x": (x - left + pad) * s, "y": (y - top + pad_top) * s, "w": w * s, "h": h * s}

    beats = []
    for b in sspec["beats"]:
        p = b["phone"]
        evs = [
            {"do": e["do"], "t": round(e["at"] - f["from"], 3), "box": box(e["box"])}
            | ({"key": True} if e.get("key") else {})
            for e in p.get("events", [])
        ]
        beats.append({"id": b["id"], "t0": round(p["at"] - f["from"], 3), "events": evs})
    return {
        "id": sspec["id"],
        # In a framed board the recording sits in the drawn phone like any "phone2" take.
        "device": "phone2" if board.get("frames") else "footage",
        "clip": f"clips/{board['id']}--{sspec['id']}.mp4",
        "seconds": round(f["to"] - f["from"], 3),
        "beats": beats,
    }


def prepare_footage(board: dict, sspec: dict, src_dir: Path, take_dir: Path) -> Path:
    """Cuts a phone recording into the shot's clip: trimmed, private bits blurred, status bar
    cropped, padded to the reel frame, and a tap ring wherever the beats tap."""
    f = sspec["footage"]
    src = src_dir / f["file"]
    shot = footage_shot(board, sspec)
    out = take_dir / shot["clip"]
    # Tap labels ("what") are for the script table only; they don't change the picture.
    phones = [
        {
            **b["phone"],
            "events": [{k: v for k, v in e.items() if k != "what"} for e in b["phone"]["events"]],
        }
        for b in sspec["beats"]
    ]
    target = footage_target(board)
    extra = [target] if board.get("frames") else []  # older cuts keep their keys
    key = _key(f, phones, render.mtime(src), REEL_W, RING, *extra)
    if render.fresh(out, key):
        return out
    if not src.exists():
        raise FileNotFoundError(f"phone recording {src} is missing")
    out.parent.mkdir(parents=True, exist_ok=True)
    left, top, cw, ch, pad, pad_top, _ = footage_frame(f, target)
    # Padded at the sides to the target's shape, or (a wider cut) above and below.
    pad_h = ch if pad else max(ch, round(cw * target[1] / target[0]))
    t0, dur = f["from"], f["to"] - f["from"]
    # Phones record only when the screen changes: make the frame rate steady before trimming, or
    # the cut would start at the first change after "from" and every time after it would shift.
    chain = [
        f"[0:v]setpts=PTS-STARTPTS,fps={FPS},trim=start={t0:.3f}:end={f['to']:.3f},"
        "setpts=PTS-STARTPTS[v0]"
    ]
    last = "v0"
    for i, bl in enumerate(f.get("blur", [])):
        x, y, bw, bh = bl["box"]
        a, b = bl.get("from", t0) - t0, bl.get("to", f["to"]) - t0
        chain.append(
            f"[{last}]split[k{i}][s{i}];[s{i}]crop={bw}:{bh}:{x}:{y},"
            f"boxblur=lr=20:lp=3:cr=8:cp=3[b{i}];"
            f"[k{i}][b{i}]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})'[u{i}]"
        )
        last = f"u{i}"
    chain.append(
        f"[{last}]crop={cw}:{ch}:{left}:{top},"
        f"pad={cw + 2 * pad}:{pad_h}:{pad}:{pad_top}:black,"
        f"scale={target[0]}:{target[1]}:flags=lanczos,setsar=1[f]"
    )
    last = "f"
    taps = [ev for bt in shot["beats"] for ev in bt["events"] if ev["do"] == "tap"]
    mint = brand.MINT.lstrip("#")
    r, g, b = (int(mint[i : i + 2], 16) for i in (0, 2, 4))
    c = RING / 2
    ring = (
        f"color=c=black:s={RING}x{RING}:d={dur:.3f}:r={FPS},format=rgba,"
        f"geq=r={r}:g={g}:b={b}:a='if(between(hypot(X-{c},Y-{c}),{c - 22},{c - 8}),235,"
        f"if(lt(hypot(X-{c},Y-{c}),{c - 22}),60,0))'"
    )
    if taps:
        chain.append(f"{ring},split={len(taps)}" + "".join(f"[r{i}]" for i in range(len(taps))))
    for i, e in enumerate(taps):
        bx = e["box"]
        x, y = bx["x"] + bx["w"] / 2 - c, bx["y"] + bx["h"] / 2 - c
        chain.append(
            f"[{last}][r{i}]overlay={x:.0f}:{y:.0f}:"
            f"enable='between(t,{e['t'] - 0.05:.3f},{e['t'] + 0.55:.3f})'[t{i}]"
        )
        last = f"t{i}"
    fc = ";".join(chain) + f";[{last}]format=yuv420p[v]"
    _ffmpeg(
        ["-i", str(src), "-filter_complex", fc, "-map", "[v]", "-an", *X264, "-crf", "14", str(out)]
    )
    render.stamp(out, key)
    return out


def build(
    repo: Path,
    board: dict,
    cast: dict,
    langs: list[str],
    fmts: list[str],
    take_dir: Path,
    root: Path,
    fonts: Path,
    logos: Path,
    music: Path | None,
    voices: dict,
) -> list[dict]:
    tid = board["id"]
    take_file = take_dir / f"take-{tid}.json"
    screens = [s for s in board["shots"] if s["device"] not in ("card", "footage")]
    # A video made only of step cards and phone footage has nothing to record.
    take = (
        json.loads(take_file.read_text(encoding="utf-8"))
        if screens or take_file.exists()
        else {"tutorial": tid, "shots": []}
    )
    for sspec in board["shots"]:
        if sspec["device"] == "footage":
            prepare_footage(board, sspec, root / "footage", take_dir)
            take["shots"] = [s for s in take["shots"] if s["id"] != sspec["id"]]
            take["shots"].append(footage_shot(board, sspec))
    used = {b["id"] for s in board["shots"] for b in s["beats"]}
    shown = [
        f"{b['id']}: {w}"
        for s in take["shots"]
        for b in s["beats"]
        if b["id"] in used
        for w in b.get("warnings", [])
    ]
    if shown:
        # Owner rule: no prices, costs or minutes in any footage. Hide them, then re-take.
        raise ValueError("price or minutes on screen in " + "; ".join(shown))
    for s in take["shots"]:
        w, h = probe_size(take_dir / s["clip"])
        s["width"], s["height"] = w, h
    kit = brand.Kit(fonts, logos)
    lib = root / "library" / tid
    results = []
    for fmt in fmts:
        for lang in langs:
            work = root / "work" / tid / f"{fmt}-{lang}"
            work.mkdir(parents=True, exist_ok=True)
            items = sequence(board, take, fmt)
            total = lay_out(items, fmt, lang, voices)
            art = art_for(repo, kit, board, fmt, lang, work)
            pic = picture(items, fmt, take_dir, art, work)
            wav = work / "mix.wav"
            mix_key = _key(
                total,
                [
                    (str(it.voice.audio), round(it.start + it.voice_at, 3))
                    for it in items
                    if it.voice
                ],
                render.mtime(music),
                FORMATS[fmt]["music"],
            )
            if not render.fresh(wav, mix_key):
                mix(items, total, music, FORMATS[fmt]["music"], wav)
                render.stamp(wav, mix_key)
            dest = lib / fmt
            dest.mkdir(parents=True, exist_ok=True)
            base = f"{tid}-{fmt}-{lang}"
            video = dest / f"{base}.mp4"
            ass_text = reel_ass(items, burned(lang), "Hind") if fmt == "reel" else ""
            fin_key = _key(
                render.mtime(pic),
                render.mtime(wav),
                ass_text,
                [render.mtime(p) for p in art.values()],
            )
            if not render.fresh(video, fin_key):
                finish(pic, wav, items, fmt, lang, art, board, fonts, work, video)
                render.stamp(video, fin_key)
            results.append(
                outputs(
                    repo,
                    kit,
                    board,
                    take,
                    take_dir,
                    items,
                    total,
                    fmt,
                    lang,
                    dest,
                    base,
                    video,
                    work,
                    cast,
                )
            )
            print(f"{base}: {total:.1f} s", flush=True)
    editor_pack(board, take, take_dir, voices, langs, lib)
    (lib / "videos.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    return results


def probe_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout  # noqa: S603
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"])


def outputs(
    repo: Path,
    kit: brand.Kit,
    board: dict,
    take: dict,
    take_dir: Path,
    items: list[Item],
    total: float,
    fmt: str,
    lang: str,
    dest: Path,
    base: str,
    video: Path,
    work: Path,
    cast: dict,
) -> dict:
    caps = dest / "captions"
    caps.mkdir(exist_ok=True)
    files = {}
    for track in TRACKS:
        cues = track_cues(items, track)
        if not cues:
            continue
        (caps / f"{base}.{track}.srt").write_text(srt(cues), encoding="utf-8")
        (caps / f"{base}.{track}.vtt").write_text(vtt(cues), encoding="utf-8")
        files[track] = {
            "label": TRACK_LABEL[track],
            "srt": f"captions/{base}.{track}.srt",
            "vtt": f"captions/{base}.{track}.vtt",
        }
    chaps = chapters(board, items, lang, total) if fmt == "youtube" else []
    tx = {burned(lang): f"{base}.transcript.txt"}
    (dest / f"{base}.transcript.txt").write_text(
        transcript(board, items, burned(lang), fmt, lang, chaps), encoding="utf-8"
    )
    if lang != "en":
        (dest / f"{base}.transcript-devanagari.txt").write_text(
            transcript(board, items, lang, fmt, lang, chaps), encoding="utf-8"
        )
        tx[lang] = f"{base}.transcript-devanagari.txt"
    title = local(board["title"], lang)
    desc = local(board.get("description"), lang)
    tags = list(board.get("tags", []))
    if fmt == "youtube":
        yt_title = f"{title} | Sales X-Ray tutorial {board['number']}"
        chapter_text = "\n".join(f"{clock(t)} {name}" for t, name in chaps)
        description = f"{desc}\n\n{chapter_text}\n\nSales X-Ray: {brand.TAGLINE}\n#SalesXRay"
        thumb = thumbnail(repo, kit, board, take, take_dir, lang, work)
        if thumb:
            shutil.copyfile(thumb, dest / f"{base}.thumbnail.jpg")
    else:
        hook = local(board["reel"]["hook"]["text"], lang)
        yt_title = f"{hook} | Sales X-Ray"
        description = f"{desc}\n\n#SalesXRay #Shorts"
    manifest = {
        "id": board["id"],
        "number": board["number"],
        "format": fmt,
        "language": lang,
        "language_label": LANG_LABEL[lang],
        "narrator": cast["languages"][lang]["name"],
        "seconds": round(total, 2),
        "size": [FORMATS[fmt]["w"], FORMATS[fmt]["h"]],
        "title": yt_title[:100],
        "description": description,
        "chapters": [{"start": clock(t), "seconds": round(t, 2), "title": n} for t, n in chaps],
        "tags": tags,
        "files": {
            "video": video.name,
            "thumbnail": f"{base}.thumbnail.jpg" if fmt == "youtube" else None,
            "transcripts": tx,
            "captions": files,
            "burned_in_captions": burned(lang) if fmt == "reel" else None,
        },
    }
    (dest / f"{base}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    (dest / f"{base}.youtube.txt").write_text(
        f"TITLE\n{manifest['title']}\n\nDESCRIPTION\n{description}\n\nTAGS\n{', '.join(tags)}\n",
        encoding="utf-8",
    )
    cue_rows = [
        {
            "item": it.spec["id"] if it.spec else it.kind,
            "in": timing.tc(it.start, "."),
            "out": timing.tc(it.start + it.dur, "."),
            "voice_in": timing.tc(it.start + it.voice_at, ".") if it.voice else "",
            "line": text(it.lines, burned(lang)),
        }
        for it in items
    ]
    with (dest / f"{base}.cues.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cue_rows[0].keys()))
        w.writeheader()
        w.writerows(cue_rows)
    return manifest


def editor_pack(
    board: dict, take: dict, take_dir: Path, voices: dict, langs: list[str], lib: Path
) -> None:
    """Raw material for editors: the screen clips (one per shot) and every voice line."""
    ed = lib / "editor"
    (ed / "clips").mkdir(parents=True, exist_ok=True)
    for s in take["shots"]:
        src = take_dir / s["clip"]
        dst = ed / "clips" / src.name
        if not dst.exists() or render.mtime(dst) < render.mtime(src):
            shutil.copyfile(src, dst)
    named = [
        ("intro", board.get("intro")),
        ("outro", board.get("outro")),
        ("reel-hook", (board.get("reel") or {}).get("hook")),
    ]
    for s in board["shots"]:
        for b in s["beats"]:
            named += [(b["id"], b), (f"{b['id']}-short", b.get("short"))]
    for name, o in named:
        if not o:
            continue
        for lang in langs:
            v = voices.get((id(o), lang))
            if v:
                d = ed / "voice" / lang
                d.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(v.audio, d / f"{board['id']}--{name}--{lang}.mp3")
