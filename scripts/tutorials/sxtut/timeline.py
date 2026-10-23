"""Editor timelines for option C: FCPXML 1.10 (Final Cut Pro, DaVinci Resolve) and FCP7 XML.

Picture: title card, one raw clip per shot at its slot, end card. Sound: each language's voice
lines on their own lane or track (roles dialogue.en / dialogue.hi / dialogue.mr), so the editor
mutes two and keeps one. Media paths are relative to the pack folder ("media/..."), so the pack
opens wherever it is unzipped. Premiere Pro imports the FCP7 XML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from .timing import FPS, frames


@dataclass
class Item:
    kind: str  # video | still | audio
    path: Path  # absolute path inside the pack
    start: float  # seconds on the timeline
    dur: float  # seconds used
    media_dur: float  # full length of the media file (stills: dur)
    width: int = 1920
    height: int = 1080
    lane: str = "v"  # v | en | hi | mr
    name: str = ""


def _t(seconds: float) -> str:
    return f"{frames(seconds)}/{FPS}s" if seconds else "0s"


def _url(p: Path, base: Path | None = None) -> str:
    # Relative to the pack folder, so the timeline opens wherever the editor unzips it (relink by
    # folder if asked).
    if base is not None:
        return quote(p.resolve().relative_to(base.resolve()).as_posix())
    return "file://" + quote(str(p.resolve()))


def _attrs(**kv: str) -> str:
    return " ".join(f'{k.rstrip("_")}="{v}"' for k, v in kv.items())


def fcpxml(title: str, items: list[Item], total: float, base: Path | None = None) -> str:
    fmts = [
        "<format "
        + _attrs(id="r0", name="FFVideoFormat1080p30", frameDuration=f"1/{FPS}s")
        + ' width="1920" height="1080"/>'
    ]
    assets: list[str] = []
    seen: dict[Path, str] = {}
    for it in items:
        if it.path in seen:
            continue
        rid = f"r{len(seen) + 1}"
        seen[it.path] = rid
        rep = f'<media-rep kind="original-media" src="{_url(it.path, base)}"/>'
        name = escape(it.path.stem)
        if it.kind == "audio":
            head = _attrs(id=rid, name=name, start="0s", duration=_t(it.media_dur), hasAudio="1")
            audio = _attrs(audioSources="1", audioChannels="1", audioRate="44100")
            assets.append(f"<asset {head} {audio}>{rep}</asset>")
        else:
            fid = f"f{rid}"
            rate = f' frameDuration="1/{FPS}s"' if it.kind == "video" else ""
            fmts.append(f'<format id="{fid}" width="{it.width}" height="{it.height}"{rate}/>')
            dur = _t(it.media_dur) if it.kind == "video" else "0s"
            head = _attrs(id=rid, name=name, start="0s", duration=dur, hasVideo="1", format=fid)
            assets.append(f"<asset {head}>{rep}</asset>")
    video = [it for it in items if it.kind in ("video", "still")]
    audio = [it for it in items if it.kind == "audio"]
    lanes = {"en": 1, "hi": 2, "mr": 3}
    spine = []
    t = 0.0
    for v in sorted(video, key=lambda x: x.start):
        if v.start > t + 1e-6:
            spine.append(f'<gap name="Gap" offset="{_t(t)}" duration="{_t(v.start - t)}"/>')
        # Voice lines hang off the shot they start in, one lane below the picture per language.
        children = "".join(
            "<asset-clip "
            + _attrs(
                ref=seen[a.path],
                lane=f"-{lanes[a.lane]}",
                offset=_t(a.start - v.start),
                name=escape(a.name),
                duration=_t(a.dur),
                start="0s",
                audioRole=f"dialogue.{a.lane}",
            )
            + "/>"
            for a in audio
            if v.start <= a.start < v.start + v.dur - 1e-6
        )
        common = _attrs(
            ref=seen[v.path],
            offset=_t(v.start),
            name=escape(v.name),
            duration=_t(v.dur),
            start="0s",
        )
        if v.kind == "still":
            spine.append(f"<video {common}>{children}</video>")
        else:
            fit = '<adjust-conform type="fit"/>'
            spine.append(f'<asset-clip {common} tcFormat="NDF">{fit}{children}</asset-clip>')
        t = v.start + v.dur
    sequence = _attrs(
        format="r0",
        duration=_t(total),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n'
        + "<resources>\n"
        + "\n".join(fmts + assets)
        + "\n</resources>\n"
        + f'<library><event name="Sales X-Ray tutorials"><project name="{escape(title)}">'
        + f"<sequence {sequence}><spine>\n"
        + "\n".join(spine)
        + "\n</spine></sequence></project></event></library>\n</fcpxml>\n"
    )


RATE = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"


def xmeml(title: str, items: list[Item], total: float, base: Path | None = None) -> str:
    """FCP7 XML (xmeml v4), which Premiere Pro imports with File > Import."""
    ids: dict[Path, str] = {}

    def file_el(it: Item) -> str:
        if it.path in ids:
            return f'<file id="{ids[it.path]}"/>'
        fid = f"file-{len(ids) + 1}"
        ids[it.path] = fid
        if it.kind == "audio":
            chars = "<samplerate>44100</samplerate><depth>16</depth>"
            media = (
                f"<media><audio><samplecharacteristics>{chars}</samplecharacteristics>"
                "<channelcount>1</channelcount></audio></media>"
            )
        else:
            chars = f"<width>{it.width}</width><height>{it.height}</height>"
            media = f"<media><video><samplecharacteristics>{chars}</samplecharacteristics>"
            media += "</video></media>"
        return (
            f'<file id="{fid}"><name>{escape(it.path.name)}</name>'
            f"<pathurl>{_url(it.path, base)}</pathurl>{RATE}"
            f"<duration>{frames(it.media_dur)}</duration>{media}</file>"
        )

    def clip(it: Item, n: int) -> str:
        s, d = frames(it.start), frames(it.dur)
        return (
            f'<clipitem id="clip-{it.lane}-{n}"><name>{escape(it.name or it.path.stem)}</name>'
            f"<enabled>TRUE</enabled><duration>{frames(it.media_dur)}</duration>{RATE}"
            f"<start>{s}</start><end>{s + d}</end><in>0</in><out>{d}</out>{file_el(it)}</clipitem>"
        )

    video = sorted([i for i in items if i.kind in ("video", "still")], key=lambda x: x.start)
    vtrack = "".join(clip(it, n) for n, it in enumerate(video))
    atracks = ""
    for lane in ("en", "hi", "mr"):
        a = sorted(
            [i for i in items if i.kind == "audio" and i.lane == lane], key=lambda x: x.start
        )
        if a:
            atracks += f"<track>{''.join(clip(it, n) for n, it in enumerate(a))}</track>"
    size = "<width>1920</width><height>1080</height>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
        + '<xmeml version="4"><sequence id="seq-1">'
        + f"<name>{escape(title)}</name><duration>{frames(total)}</duration>{RATE}"
        + f"<media><video><format><samplecharacteristics>{size}{RATE}</samplecharacteristics>"
        + f"</format><track>{vtrack}</track></video><audio>{atracks}</audio></media>"
        + "</sequence></xmeml>\n"
    )
