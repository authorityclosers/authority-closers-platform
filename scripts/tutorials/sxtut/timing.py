"""Timing and captions: one picture timeline for every language, caption cues from voice timings.

Each segment lasts long enough for its clip and for the longest of its three voice lines, so one
silent cut fits English, Hinglish and Marathi-English alike (option B) and the editor swaps audio
without re-cutting (option C).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

FPS = 30
LEAD_S = 0.35  # the voice starts this long after its shot does
TAIL_S = 0.45  # and the shot holds this long after the voice ends
MAX_LINE = 42  # caption characters per line
MAX_LINES = 2


def frames(seconds: float) -> int:
    return int(math.ceil(round(seconds * FPS, 6)))


def tc(seconds: float, sep: str = ",") -> str:
    """SRT timecode (HH:MM:SS,mmm); sep="." gives the same with a dot."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def ass_tc(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


@dataclass
class Cue:
    start: float
    end: float
    text: str
    style: str = "phone"


@dataclass
class Seg:
    id: str
    device: str
    clip_s: float
    voice_s: dict[str, float] = field(default_factory=dict)
    start: float = 0.0
    dur: float = 0.0


def layout(segs: list[Seg], intro_s: float, outro_s: float) -> float:
    """Sets each segment's start and duration (whole frames); returns the total length."""
    t = intro_s
    for s in segs:
        need = max([s.clip_s] + [LEAD_S + v + TAIL_S for v in s.voice_s.values()])
        s.start = t
        s.dur = frames(need) / FPS
        t += s.dur
    return t + outro_s


def phrase_spans(phrases: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """The text sent to the voice (phrases joined by spaces) and each phrase's span in it."""
    spans, pos, parts = [], 0, []
    for p in phrases:
        p = p.strip()
        spans.append((pos, pos + len(p)))
        parts.append(p)
        pos += len(p) + 1
    return " ".join(parts), spans


def span_times(alignment: dict, spans: list[tuple[int, int]]) -> list[tuple[float, float]]:
    """Start and end second of each character span, from ElevenLabs character alignment."""
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    n = len(starts)
    out = []
    for a, b in spans:
        a = min(a, n - 1)
        b = max(a, min(b - 1, n - 1))
        out.append((float(starts[a]), float(ends[b])))
    return out


def wrap(text: str, width: int = MAX_LINE) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def sentences(text: str) -> list[str]:
    out, cur = [], []
    for w in text.split():
        cur.append(w)
        if w[-1] in ".?!:" and not w.endswith("4.0") and len(" ".join(cur)) > 12:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _split_points(words: list[str], parts: int) -> list[int]:
    """Word counts after which to break a sentence into `parts` near-equal pieces, at a comma when
    one is close to the even split (so a caption never ends on "aur" or "and")."""
    ends = [len(" ".join(words[: i + 1])) for i in range(len(words))]
    total = ends[-1]
    cuts: list[int] = []
    for k in range(1, parts):
        target = total * k / parts
        options = [i for i in range(len(words) - 1) if not cuts or i + 1 > cuts[-1]]
        near = min(options, key=lambda i: abs(ends[i] - target))
        commas = [i for i in options if words[i].endswith(",")]
        best = min(commas, key=lambda i: abs(ends[i] - target), default=None)
        if best is not None and abs(ends[best] - target) <= 0.3 * total / parts:
            near = best
        cuts.append(near + 1)
    return cuts


def balanced(text: str) -> list[str]:
    """Pieces of at most two caption lines: split at sentence ends, then into near-equal parts."""
    pieces = []
    for sent in sentences(text):
        parts = math.ceil(len(wrap(sent)) / MAX_LINES)
        words = sent.split()
        if parts <= 1 or len(words) < 2:
            pieces.append(sent)
            continue
        bounds = [0, *_split_points(words, parts), len(words)]
        pieces += [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)]
    return pieces


def two_lines(text: str) -> str:
    """One caption: a single line if it fits, else two lines of about equal length (no orphans)."""
    if len(text) <= MAX_LINE:
        return text
    words = text.split()
    fits = [
        i
        for i in range(1, len(words))
        if max(len(" ".join(words[:i])), len(" ".join(words[i:]))) <= MAX_LINE
    ]
    if not fits:
        return "\n".join(wrap(text))
    i = min(fits, key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:i]) + "\n" + " ".join(words[i:])


def chunk(text: str, start: float, end: float, style: str) -> list[Cue]:
    """Splits one phrase into cues of at most two caption lines, timed by share of characters."""
    groups = balanced(text)
    total = sum(len(g) for g in groups) or 1
    cues, t = [], start
    for g in groups:
        d = (end - start) * len(g) / total
        cues.append(Cue(t, t + d, two_lines(g), style))
        t += d
    return cues


def cues_for(
    seg_start: float, captions: list[str], times: list[tuple[float, float]], style: str
) -> list[Cue]:
    out: list[Cue] = []
    for text, (a, b) in zip(captions, times, strict=True):
        out += chunk(text, seg_start + LEAD_S + a, seg_start + LEAD_S + b, style)
    # Close tiny gaps so captions do not flicker between phrases of one line.
    for x, y in zip(out, out[1:], strict=False):
        if 0 < y.start - x.end < 0.35:
            x.end = y.start
    return out


def srt(cues: list[Cue]) -> str:
    return "".join(
        f"{i}\n{tc(c.start)} --> {tc(c.end)}\n{c.text}\n\n" for i, c in enumerate(cues, 1)
    )


# White bold text on a dark teal box (BorderStyle 3). Margins: phone captions sit in the panel right
# of the phone (MarginL 1010); desktop captions in the strip under the window; card captions low.
ASS_COLOURS = "&H00FFFFFF,&H00FFFFFF,&H00382A12,&H8C2A1A0F"
ASS_STYLES = {
    "phone": (46, 14, 1010, 110, 120),
    "desktop": (40, 12, 120, 120, 22),
    "card": (44, 14, 120, 120, 90),
}


def ass(cues: list[Cue], font: str, width: int = 1920, height: int = 1080) -> str:
    """Burn-in captions for libass (ffmpeg's ass filter)."""
    fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    styles = [
        f"Style: {name},{font},{size},{ASS_COLOURS},1,0,0,0,100,100,0,0,3,{pad},0,2,"
        f"{left},{right},{bottom},1"
        for name, (size, pad, left, right, bottom) in ASS_STYLES.items()
    ]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        fmt,
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in cues:
        text = c.text.replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{ass_tc(c.start)},{ass_tc(c.end)},{c.style},,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
