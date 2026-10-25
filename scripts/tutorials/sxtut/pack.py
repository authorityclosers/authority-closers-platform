"""Delivery of the v2 videos. `publish` lays out the "Sales X-Ray Videos" folder (owner, 25 Oct
2026: one numbering 1-11 from videos-v2.json, a phone-video folder per language, the wide cuts and
the editable files apart, a start-here sheet). `export` is the earlier dated pack (orchestrator,
25 Oct 2026: tester videos "everything editable and with voice-over, in our folders"):

    <day>/<Language>/<NN Title>/   both cuts (9x16, 16x9), SRT subtitles, the script (.txt, .docx)
                                   and every voice line of that language
    <day>/Project files/<id>/      raw screen takes, the storyboard and take JSON, cue sheets
    <day>/index.csv                one row per video: language, format, length, file, what it shows

Built from the v2 library (`~/sx-tutorials/v2/library/<id>/`), so it never re-renders anything.
The .docx scripts are written by `docx_script.py` through uv and python-docx.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import v2

FOLDER = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
CUT = {"reel": "9x16", "youtube": "16x9"}


README = """Sales X-Ray how-to videos: editable pack

English/, Hindi/, Marathi/
    One folder per video. Inside:
    <id>-<language>-9x16.mp4   for WhatsApp, Reels and Shorts (captions burned in)
    <id>-<language>-16x9.mp4   for YouTube and the website (add the .srt as captions)
    <id>-<language>-*.srt      subtitles; Hindi and Marathi also as .devanagari.srt
    <id>-<language>-script.docx and .txt   the script with times, to edit or re-record
    voice/                     every voice line as its own MP3 (ElevenLabs), to re-cut freely
Project files/<id>/
    takes/                     the raw screen recordings, no captions or music
    <id>.storyboard.json       the storyboard: shots, actions and every line in all languages
    <id>.take.json             when each tap and highlight happens in the takes
    cues/                      each cut's timeline (item, in, out, voice in, line)
Index                          one row per video file: language, format, length, link, what it shows

Screens come from Sales X-Ray's review fixtures with made-up people and companies. Steps that only
a real phone shows (Google Play, Android prompts) are drawn as step cards until phone recordings
replace them. Rebuild: scripts/tutorials/tutorials.py v2 build <id> on ac (README there, section
v2).
"""


def safe(name: str) -> str:
    return re.sub(r"[^\w .,()&-]+", "", name).strip()[:80]


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copyfile(src, dst)


def _cue_rows(lib: Path, fmt: str, base: str) -> list[dict]:
    f = lib / fmt / f"{base}.cues.csv"
    if not f.exists():
        return []
    with f.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def script_rows(board: dict, lang: str, cues: list[dict]) -> list[dict]:
    """One row per item of the 16:9 cut: time, what is on screen, and the narration as said (and in
    Roman script for Hindi and Marathi)."""
    beats = {b["id"]: b for s in board["shots"] for b in s["beats"]}
    rows = []
    for c in cues:
        item = c["item"]
        if item in beats:
            b = beats[item]
            card = b.get("card")
            shown = v2.local(card["title"], lang) if card else _describe(b)
            lines = b
        elif item in ("intro", "outro"):
            lines = board.get(item) or {}
            shown = "Title card" if item == "intro" else "End card"
        else:
            continue
        rows.append(
            {
                "time": c["in"][3:8],
                "on_screen": shown,
                "say": v2.text(lines, lang),
                "roman": v2.text(lines, f"{lang}-Latn") if lang != "en" else "",
            }
        )
    return rows


def _describe(beat: dict) -> str:
    """A short on-screen note from a beat's actions: what is tapped, typed or highlighted."""
    out = []
    for a in beat.get("actions", []):
        t = a.get("target") or {}
        what = t.get("name") or t.get("text") or t.get("placeholder") or t.get("label")
        if a["do"] in ("tap", "highlight", "type", "paste", "select") and what:
            verb = {
                "tap": "Tap",
                "highlight": "Show",
                "type": "Type in",
                "paste": "Paste into",
                "select": "Choose in",
            }[a["do"]]
            out.append(f"{verb} “{what}”")
    phone = beat.get("phone")
    if phone:
        # Real phone footage: its taps carry a label ("what") instead of a target.
        taps = [f"Tap “{e['what']}”" for e in phone.get("events", []) if e.get("what")]
        return "Phone: " + ("; ".join(dict.fromkeys(taps)) or "the real screen")
    return "; ".join(dict.fromkeys(out)) or "Screen"


def write_txt(
    path: Path, title: str, lang: str, rows: list[dict], seconds: dict[str, float]
) -> None:
    lines = [
        title,
        f"{FOLDER[lang]} · 16x9 {v2.clock(seconds.get('youtube', 0))} · "
        f"9x16 {v2.clock(seconds.get('reel', 0))}",
        "",
    ]
    for r in rows:
        lines.append(f"[{r['time']}] {r['on_screen']}")
        lines.append(r["say"])
        if r["roman"]:
            lines.append(r["roman"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_docx(
    repo: Path, path: Path, title: str, lang: str, rows: list[dict], seconds: dict[str, float]
) -> None:
    spec = path.with_suffix(".docx.json")
    spec.write_text(
        json.dumps(
            {
                "title": title,
                "language": FOLDER[lang],
                "lengths": {CUT[k]: v2.clock(v) for k, v in seconds.items()},
                "rows": rows,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    uv = str(Path.home() / ".local/bin/uv")
    helper = repo / "scripts/tutorials/sxtut/docx_script.py"
    cmd = [
        uv,
        "run",
        "--no-project",
        "--with",
        "python-docx",
        "python",
        str(helper),
        str(spec),
        str(path),
    ]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)  # noqa: S603 - fixed uv argument list
    spec.unlink()


ABOUT = """Editable files: one folder per video, named like the videos.

<Language>/Script.docx and Script.txt   the narration with times, to edit or re-record
<Language>/Subtitles phone.srt, Subtitles wide.srt   (Hindi and Marathi also in Devanagari)
<Language>/Voice lines/                 every narration line as its own MP3
<Language>/YouTube description.txt      title, description and chapters for YouTube
Project files/                          the screen recordings (takes), the storyboard and timings

Rebuild on ac: scripts/tutorials/tutorials.py v2 build <id>, then v2 publish (README, section v2).
"""


def video_name(n: int, title: str) -> str:
    """'01 Join the testers': the file and folder name of video n (no colons, for Drive and
    Windows)."""
    return safe(f"{n:02d} {title.replace(':', ' -')}")


def publish(
    repo: Path, root: Path, out: Path, catalogue: dict, boards: dict, langs: list[str]
) -> dict:
    """The "Sales X-Ray Videos" folder (owner, 25 Oct 2026: one numbering, simple folders, a
    start-here sheet): each language's phone (9:16) videos at the top, the 16:9 cuts under
    "YouTube (wide)", scripts, subtitles, voice lines and project files under "Editable files".
    Returns (and writes as manifest.json) what the start-here sheet lists. Copies from the
    library; never re-renders."""
    videos = []
    for n, entry in enumerate(catalogue["videos"], 1):
        tid = entry["id"]
        board = boards[tid]
        lib = root / "library" / tid
        name = video_name(n, entry["title"])
        if entry.get("coming"):
            # Owner, 25 Oct 2026: nothing with the old screens goes to testers. The sheet keeps
            # the row with a note; its files leave the folder (publish.sh moves them to Old
            # versions).
            videos.append(
                {**entry, "number": n, "name": name, "phone": {}, "wide": {}, "seconds": {}}
            )
            continue
        edit = out / "Editable files" / name
        proj = edit / "Project files"
        for src in (lib / "editor" / "clips").glob("*.mp4"):
            _copy(src, proj / "takes" / src.name)
        _copy(repo / "scripts/tutorials/v2" / f"{tid}.json", proj / f"{tid}.storyboard.json")
        take_file = root / "take" / f"take-{tid}.json"
        if take_file.exists():
            _copy(take_file, proj / f"{tid}.take.json")
        row = {**entry, "number": n, "name": name, "phone": {}, "wide": {}, "seconds": {}}
        for lang in langs:
            folder = FOLDER[lang]
            seconds = {}
            for fmt, cut in (("reel", "phone"), ("youtube", "wide")):
                base = f"{tid}-{fmt}-{lang}"
                video = lib / fmt / f"{base}.mp4"
                if not video.exists():
                    continue
                meta = json.loads((lib / fmt / f"{base}.json").read_text(encoding="utf-8"))
                seconds[fmt] = meta["seconds"]
                top = out / folder if cut == "phone" else out / "YouTube (wide)" / folder
                _copy(video, top / f"{name}.mp4")
                row[cut][lang] = (top / f"{name}.mp4").relative_to(out).as_posix()
                caps = lib / fmt / "captions"
                _copy(
                    caps / f"{base}.{v2.burned(lang)}.srt", edit / folder / f"Subtitles {cut}.srt"
                )
                if lang != "en":
                    _copy(
                        caps / f"{base}.{lang}.srt",
                        edit / folder / f"Subtitles {cut} (Devanagari).srt",
                    )
                _copy(lib / fmt / f"{base}.cues.csv", proj / "cues" / f"{tid}-{lang}-{cut}.csv")
                described = lib / fmt / f"{base}.youtube.txt"
                if cut == "wide" and described.exists():
                    _copy(described, edit / folder / "YouTube description.txt")
            if not seconds:
                continue
            row["seconds"][lang] = seconds
            title = v2.local(board["title"], lang)
            rows = script_rows(board, lang, _cue_rows(lib, "youtube", f"{tid}-youtube-{lang}"))
            write_txt(edit / folder / "Script.txt", title, lang, rows, seconds)
            write_docx(repo, edit / folder / "Script.docx", title, lang, rows, seconds)
            for mp3 in (lib / "editor" / "voice" / lang).glob("*.mp3"):
                _copy(mp3, edit / folder / "Voice lines" / mp3.name)
        videos.append(row)
    (out / "Editable files").mkdir(parents=True, exist_ok=True)
    (out / "Editable files" / "About these files.txt").write_text(ABOUT, encoding="utf-8")
    keep = ("name", "sheet", "optin", "coming")
    manifest = {**{k: catalogue[k] for k in keep}, "videos": videos}
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return manifest


def export(repo: Path, root: Path, day: Path, boards: list[dict], langs: list[str]) -> list[dict]:
    """Copies the built videos into the editable pack and returns the index rows."""
    index = []
    for board in boards:
        tid = board["id"]
        lib = root / "library" / tid
        proj = day / "Project files" / tid
        for src in (lib / "editor" / "clips").glob("*.mp4"):
            _copy(src, proj / "takes" / src.name)
        board_file = repo / "scripts/tutorials/v2" / f"{tid}.json"
        if board_file.exists():
            _copy(board_file, proj / f"{tid}.storyboard.json")
        take_file = root / "take" / f"take-{tid}.json"
        if take_file.exists():
            _copy(take_file, proj / f"{tid}.take.json")
        for lang in langs:
            title = v2.local(board["title"], lang)
            name = f"{board['number']} {v2.local(board['title'], 'en')}"
            folder = day / FOLDER[lang] / safe(name)
            seconds = {}
            for fmt in ("youtube", "reel"):
                base = f"{tid}-{fmt}-{lang}"
                video = lib / fmt / f"{base}.mp4"
                if not video.exists():
                    continue
                meta = json.loads((lib / fmt / f"{base}.json").read_text(encoding="utf-8"))
                seconds[fmt] = meta["seconds"]
                name = f"{tid}-{lang}-{CUT[fmt]}"
                _copy(video, folder / f"{name}.mp4")
                _copy(lib / fmt / f"{base}.cues.csv", proj / "cues" / f"{name}.cues.csv")
                own = v2.burned(lang)
                caps = lib / fmt / "captions"
                _copy(caps / f"{base}.{own}.srt", folder / f"{name}.srt")
                if lang != "en":
                    _copy(caps / f"{base}.{lang}.srt", folder / f"{name}.devanagari.srt")
                index.append(
                    {
                        "video": title,
                        "id": tid,
                        "language": FOLDER[lang],
                        "format": CUT[fmt],
                        "length": v2.clock(meta["seconds"]),
                        "file": f"{FOLDER[lang]}/{folder.name}/{name}.mp4",
                        "shows": v2.local(board.get("description"), lang),
                    }
                )
            if not seconds:
                continue
            rows = script_rows(board, lang, _cue_rows(lib, "youtube", f"{tid}-youtube-{lang}"))
            write_txt(folder / f"{tid}-{lang}-script.txt", title, lang, rows, seconds)
            write_docx(repo, folder / f"{tid}-{lang}-script.docx", title, lang, rows, seconds)
            for mp3 in (lib / "editor" / "voice" / lang).glob("*.mp3"):
                _copy(mp3, folder / "voice" / mp3.name)
    (day / "README.txt").write_text(README, encoding="utf-8")
    with (day / "index.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["video", "id", "language", "format", "length", "file", "link", "shows"]
        )
        w.writeheader()
        for r in index:
            w.writerow({**r, "link": ""})
    return index
