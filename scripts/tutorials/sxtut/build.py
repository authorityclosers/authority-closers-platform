"""One tutorial end to end: voice lines, capture, stitched picture, and the three deliverables (A, B, C).

Storyboard (scripts/tutorials/scripts/<id>.json):
  {"id", "number", "title", "kicker", "end_headline", "next",
   "segments": [{"id", "device": "phone"|"desktop"|"card"|"end", "label", "setup": [...], "actions": [...],
                 "en": {"say": [phrases]}, "hi": {"say": [...], "caption": [...]}, "mr": {...}}]}
"card" shows the title card and "end" the end card; both may carry a voice line. If a board has no "card" segment,
a silent 2.5 s title card opens it; without an "end" segment a silent 3 s end card closes it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from . import render, textprep, timeline, timing, tts

LANG_NAMES = {"en": "English", "hi": "Hinglish", "mr": "Marathi-English"}
CARD_KINDS = ("card", "end")


def caption_phrases(seg: dict, lang: str) -> list[str]:
    block = seg.get(lang) or {}
    return list(block.get("caption") or block.get("say") or [])


def with_cards(board: dict) -> list[dict]:
    segs = list(board["segments"])
    if not any(s["device"] == "card" for s in segs):
        segs.insert(0, {"id": "title", "device": "card", "hold_s": 2.5})
    if not any(s["device"] == "end" for s in segs):
        segs.append({"id": "end", "device": "end", "hold_s": 3.0})
    return segs


def voice(board: dict, cast: dict, langs: list[str], cache: Path) -> dict:
    """{seg_id: {lang: {"audio", "dur", "times"}}}; cached lines cost nothing."""
    rules = textprep.load_pronounce()
    out: dict = {}
    for seg in with_cards(board):
        for lang in langs:
            phrases = (seg.get(lang) or {}).get("say")
            if not phrases:
                continue
            spoken = [textprep.spoken(p, lang, rules) for p in phrases]
            text, spans = timing.phrase_spans(spoken)
            audio, info = tts.synthesize(tts.line_from_cast(text, lang, cast), cache)
            out.setdefault(seg["id"], {})[lang] = {
                "audio": str(audio),
                "dur": render.probe_seconds(audio),
                "times": timing.span_times(info["alignment"], spans),
            }
    return out


def characters(board: dict, langs: list[str]) -> int:
    rules = textprep.load_pronounce()
    return sum(len(" ".join(textprep.spoken(p, lang, rules) for p in (s.get(lang) or {}).get("say", [])))
               for s in with_cards(board) for lang in langs)


def capture(repo: Path, board_file: Path, out: Path, device: str | None = None) -> None:
    args = ["node", str(repo / "scripts/tutorials/capture.mjs"), "shoot", str(board_file), str(out)]
    if device:
        args += ["--device", device]
    render.wait_for_headroom()
    subprocess.run(["nice", "-n", "19", "ionice", "-c3", *args], check=True, cwd=repo, stdin=subprocess.DEVNULL,
                   env=render.safe_env())


def build(repo: Path, board: dict, cast: dict, langs: list[str], cap_dir: Path, out: Path, fonts: Path,
          voices: dict) -> dict:
    tid = board["id"]
    work = out / "work" / tid
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((cap_dir / f"capture-{tid}.json").read_text(encoding="utf-8"))
    clips = {s["id"]: s for s in manifest["segments"]}
    segs_spec = with_cards(board)

    # 1. Timing shared by every language.
    segs = []
    for s in segs_spec:
        clip_s = clips[s["id"]]["seconds"] if s["id"] in clips else float(s.get("hold_s", 0))
        if s["device"] not in CARD_KINDS and s["id"] in clips:
            clip_s = render.probe_seconds(cap_dir / clips[s["id"]]["clip"])
        segs.append(timing.Seg(s["id"], s["device"], clip_s,
                               {lang: voices[s["id"]][lang]["dur"] for lang in langs if lang in voices.get(s["id"], {})}))
    total = timing.layout(segs, 0.0, 0.0)

    # 2. Stage art.
    font_css = render.brand_font_css(repo)
    steps = [s for s in segs_spec if s["device"] not in CARD_KINDS]
    cards = [{"name": "title", "html": render.title_html(font_css, board["number"], board["title"],
                                                           board.get("kicker", "Sales X-Ray tutorial"))},
             {"name": "end", "html": render.end_html(font_css, board.get("end_headline", "That's it!"),
                                                     board.get("next", ""))}]
    for i, s in enumerate(steps, 1):
        cards.append({"name": f"frame-{s['id']}", "transparent": True,
                      "html": render.frame_html(font_css, s["device"], s.get("label", ""), f"Step {i} of {len(steps)}")})
    render.render_cards(repo, cards, work / "cards")

    # 3. Picture (silent cut, no captions).
    parts = []
    for spec, seg in zip(segs_spec, segs):
        part = work / f"seg-{seg.id}.mp4"
        if seg.device in CARD_KINDS:
            card = work / "cards" / ("title.png" if seg.device == "card" else "end.png")
            key = f"{seg.dur:.3f}|{seg.device}|{render.mtime(card)}"
            if not render.fresh(part, key):
                render.segment_video(part, seg.dur, None, None, seg.device, card_png=card)
        else:
            frame, clip = work / "cards" / f"frame-{seg.id}.png", cap_dir / clips[seg.id]["clip"]
            key = f"{seg.dur:.3f}|{seg.device}|{render.mtime(frame)}|{render.mtime(clip)}"
            if not render.fresh(part, key):
                render.segment_video(part, seg.dur, frame, clip, seg.device)
        render.stamp(part, key)
        parts.append(part)
    silent = work / f"{tid}-silent.mp4"
    key = "|".join(f"{p.name}:{render.mtime(p)}" for p in parts)
    if not render.fresh(silent, key):
        render.concat(parts, silent)
        render.stamp(silent, key)

    # 4. Captions and voice per language.
    a_dir, b_dir, c_dir = out / "A-narrated" / tid, out / "B-voiceover-kit" / tid, out / "C-editor-pack" / tid
    for d in (a_dir, b_dir, c_dir / "captions", c_dir / "media"):
        d.mkdir(parents=True, exist_ok=True)
    result = {"id": tid, "seconds": round(total, 2), "langs": {}}
    cue_rows = []
    for lang in langs:
        cues, deva, lines = [], [], []
        for spec, seg in zip(segs_spec, segs):
            v = voices.get(seg.id, {}).get(lang)
            if not v:
                continue
            style = "card" if seg.device in CARD_KINDS else seg.device
            cues += timing.cues_for(seg.start, caption_phrases(spec, lang), v["times"], style)
            if lang != "en":
                deva += timing.cues_for(seg.start, spec[lang]["say"], v["times"], style)
            lines.append((Path(v["audio"]), seg.start + timing.LEAD_S))
        srt = timing.srt(cues)
        (a_dir / f"{tid}-{lang}.srt").write_text(srt, encoding="utf-8")
        (b_dir / f"{tid}-{lang}.srt").write_text(srt, encoding="utf-8")
        (c_dir / "captions" / f"{tid}-{lang}.srt").write_text(srt, encoding="utf-8")
        if deva:
            dsrt = timing.srt(deva)
            (a_dir / f"{tid}-{lang}-devanagari.srt").write_text(dsrt, encoding="utf-8")
            (c_dir / "captions" / f"{tid}-{lang}-devanagari.srt").write_text(dsrt, encoding="utf-8")
        ass_text = timing.ass(cues, "Plus Jakarta Sans")
        ass_file = work / f"{tid}-{lang}.ass"
        ass_file.write_text(ass_text, encoding="utf-8")
        wav = work / f"{tid}-{lang}.wav"
        mix_key = f"{total:.3f}|" + "|".join(f"{p.name}@{at:.3f}" for p, at in lines)
        if not render.fresh(wav, mix_key):
            render.voice_mix(lines, total, wav)
            render.stamp(wav, mix_key)
        final = a_dir / f"{tid}-{lang}.mp4"
        final_key = f"{render.mtime(silent)}|{render.mtime(wav)}|{hashlib.sha256(ass_text.encode()).hexdigest()}"
        if not render.fresh(final, final_key):
            render.narrated(silent, wav, ass_file, fonts, final)
            render.stamp(final, final_key)
        result["langs"][lang] = {"cues": len(cues), "file": str(a_dir / f"{tid}-{lang}.mp4")}

    # 5. Option B: silent cut, scripts with timecodes, cue sheet.
    shutil.copyfile(silent, b_dir / f"{tid}-silent.mp4")
    for spec, seg in zip(segs_spec, segs):
        row = {"segment": seg.id, "in": timing.tc(seg.start, "."), "out": timing.tc(seg.start + seg.dur, "."),
               "voice_in": timing.tc(seg.start + timing.LEAD_S, "."), "device": seg.device,
               "on_screen": spec.get("label", "title card" if seg.device == "card" else "end card" if seg.device == "end" else "")}
        for lang in langs:
            row[f"line_{lang}"] = " ".join(caption_phrases(spec, lang))
            row[f"seconds_{lang}"] = round(seg.voice_s.get(lang, 0.0), 1)
        cue_rows.append(row)
    with (b_dir / f"{tid}-cue-sheet.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cue_rows[0].keys()))
        w.writeheader()
        w.writerows(cue_rows)
    for lang in langs:
        md = [f"# {board['number']} {board['title']}: voice-over script, {LANG_NAMES[lang]}", "",
              f"Picture: `{tid}-silent.mp4` ({timing.tc(total, '.')}). Start each line at its time; the space after it "
              "is the longest of the three languages, so there is room to breathe. Keep UI words in English as on screen.",
              ""]
        for spec, seg, row in zip(segs_spec, segs, cue_rows):
            text = " ".join(caption_phrases(spec, lang))
            if not text:
                continue
            md += [f"**{row['voice_in']}** to {row['out']}  ·  _{row['on_screen']}_  ·  AI voice took {row[f'seconds_{lang}']} s", "",
                   f"> {text}", ""]
            if lang != "en":
                md += [f"> {' '.join(spec[lang]['say'])}", ""]
        (b_dir / f"{tid}-script-{lang}.md").write_text("\n".join(md), encoding="utf-8")

    # 6. Option C: media, shot list, timelines.
    media = c_dir / "media"
    items: list[timeline.Item] = []
    for sub in ("clips", "stills", "cards"):
        (media / sub).mkdir(parents=True, exist_ok=True)
    for name in ("title", "end"):
        shutil.copyfile(work / "cards" / f"{name}.png", media / "cards" / f"{tid}-{name}-card.png")
    shots = []
    for spec, seg in zip(segs_spec, segs):
        if seg.device in CARD_KINDS:
            png = media / "cards" / f"{tid}-{'title' if seg.device == 'card' else 'end'}-card.png"
            items.append(timeline.Item("still", png, seg.start, seg.dur, seg.dur, name=png.stem))
        else:
            src = cap_dir / clips[seg.id]["clip"]
            dst = media / "clips" / src.name
            shutil.copyfile(src, dst)
            wpx, hpx = (1170, 2532) if seg.device == "phone" else (2880, 1800)
            items.append(timeline.Item("video", dst, seg.start, min(seg.dur, seg.clip_s), seg.clip_s, wpx, hpx,
                                       name=f"{seg.id} {spec.get('label', '')}".strip()))
            for st in clips[seg.id].get("stills", []):
                s_src = cap_dir / st["file"]
                shutil.copyfile(s_src, media / "stills" / s_src.name)
        for lang in langs:
            v = voices.get(seg.id, {}).get(lang)
            if v:
                vdir = media / "voice" / lang
                vdir.mkdir(parents=True, exist_ok=True)
                dst = vdir / f"{tid}--{seg.id}--{lang}.mp3"
                shutil.copyfile(v["audio"], dst)
                items.append(timeline.Item("audio", dst, seg.start + timing.LEAD_S, v["dur"], v["dur"], lane=lang,
                                           name=f"{seg.id} {lang}"))
        shots.append({"shot": seg.id, "in": timing.tc(seg.start, "."), "seconds": round(seg.dur, 2),
                      "device": seg.device, "on_screen": spec.get("label", ""),
                      "screen": next((a.get("url") for a in spec.get("setup", []) if a.get("do") == "goto"), ""),
                      "clip": f"media/clips/{Path(clips[seg.id]['clip']).name}" if seg.id in clips else "",
                      "line_en": " ".join(caption_phrases(spec, "en"))})
    with (c_dir / f"{tid}-shot-list.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(shots[0].keys()))
        w.writeheader()
        w.writerows(shots)
    title = f"{board['number']} {board['title']}"
    (c_dir / f"{tid}.fcpxml").write_text(timeline.fcpxml(title, items, total, c_dir), encoding="utf-8")
    (c_dir / f"{tid}-premiere.xml").write_text(timeline.xmeml(title, items, total, c_dir), encoding="utf-8")
    shutil.copyfile(silent, c_dir / f"{tid}-reference-silent.mp4")
    (work / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
