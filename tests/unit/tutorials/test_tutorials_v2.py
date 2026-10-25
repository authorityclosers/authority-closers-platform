"""Tutorials v2 (brand B reels and YouTube tutorials): storyboards, camera, beat timing and
captions.

No network, no browser, no ffmpeg: a fake take manifest and fake voice timings stand in for them.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TUT = ROOT / "scripts/tutorials"
sys.path.insert(0, str(TUT))

from sxtut import brand, camera, textprep, v2  # noqa: E402

LANGS = ("en", "hi", "mr")


def boards() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((TUT / "v2").glob("*.json"))]


def test_v2_storyboards_follow_the_owner_rules_and_have_every_language() -> None:
    import tutorials

    assert boards()
    for b in boards():
        assert tutorials.lint_v2(b) == [], b["id"]
        ids = [beat["id"] for s in b["shots"] for beat in s["beats"]]
        assert len(ids) == len(set(ids)), b["id"]
        chapters = {c["id"] for c in b["chapters"]}
        assert {beat["chapter"] for s in b["shots"] for beat in s["beats"]} <= chapters
        hook = b["reel"]["hook"].get("beat")
        assert hook is None or hook in ids
        assert b["reel"].get("all") or set(b["reel"]["beats"]) <= set(ids)
        for s in b["shots"]:
            assert s["device"] in ("reel", "wide", "card", "footage")
            for beat in s["beats"]:
                assert ("card" in beat) == (s["device"] == "card"), beat["id"]
                assert ("phone" in beat) == (s["device"] == "footage"), beat["id"]
            if s["device"] == "footage":
                f = s["footage"]
                assert not f["file"].startswith(("/", ".")) and f["from"] < f["to"]
                for beat in s["beats"]:
                    times = [beat["phone"]["at"], *(e["at"] for e in beat["phone"]["events"])]
                    assert all(f["from"] <= t <= f["to"] for t in times), beat["id"]
            for a in s.get("setup", []) + [a for beat in s["beats"] for a in beat["actions"]]:
                if a["do"] == "goto":
                    assert a["url"].startswith("/review-fixture/"), a


def test_v2_narrators_are_one_library_voice_per_language() -> None:
    cast = json.loads((TUT / "voices-v2.json").read_text(encoding="utf-8"))
    ids = {lang: cast["languages"][lang]["voice_id"] for lang in LANGS}
    assert all(re.fullmatch(r"[A-Za-z0-9]{20}", v) for v in ids.values())
    assert cast["model_id"] == "eleven_v4"


def test_camera_frames_a_small_button_and_leaves_big_cards_alone() -> None:
    w, h = 1170, 2078
    st = camera.focus({"x": 900, "y": 1900, "w": 150, "h": 120}, w, h, 1.6)
    assert st is not None and st.z == 1.6
    # The window stays inside the frame even for a button in the corner.
    assert st.cx + w / st.z / 2 <= w + 0.5 and st.cy + h / st.z / 2 <= h + 0.5
    assert camera.focus({"x": 0, "y": 300, "w": 1170, "h": 900}, w, h, 1.6) is None


def test_camera_plan_zooms_in_for_a_tap_and_comes_back() -> None:
    rest = camera.full(1170, 2078)
    near = camera.State(1.6, 600.0, 900.0)
    keys = camera.plan(4.0, [(1.0, "tap", near)], rest, rest, rest)
    times = [t for t, _ in keys]
    assert times == sorted(times) and keys[0] == (0.0, rest) and keys[-1][0] == 4.0
    assert any(s == near for _, s in keys)
    assert keys[-1][1] == rest
    expr = camera.zoompan(keys, 1170, 2078, 1080, 1920)
    assert expr.startswith("zoompan=z='") and "s=1080x1920" in expr
    assert expr.count("(") == expr.count(")")


def _eval(expr: str, t: float) -> float:
    """Evaluates an ffmpeg expression of the shapes camera.expr writes (if, lt, clip)."""
    env = {
        "iff": lambda c, a, b: a if c else b,
        "lt": lambda a, b: a < b,
        "clip": lambda x, lo, hi: min(max(x, lo), hi),
        "T": t,
    }
    return float(eval(expr.replace("if(", "iff("), {"__builtins__": {}}, env))  # noqa: S307


def test_camera_expression_holds_and_eases() -> None:
    assert camera.expr([(0.0, 1.0), (1.0, 1.0)], "T") == "1"
    e = camera.expr([(0.0, 1.0), (0.5, 1.0), (1.0, 2.0), (3.0, 2.0)], "T")
    assert _eval(e, 0.2) == 1.0 and _eval(e, 0.5) == 1.0
    assert abs(_eval(e, 0.75) - 1.5) < 1e-9  # smoothstep half way
    assert _eval(e, 1.0) == 2.0 and _eval(e, 2.5) == 2.0 and _eval(e, 9.0) == 2.0
    values = [_eval(e, i / 100) for i in range(0, 120)]
    assert values == sorted(values)


def _voice(spoken: str, seconds: float) -> v2.Voiced:
    n = len(spoken)
    starts = [seconds * i / n for i in range(n)]
    ends = [seconds * (i + 1) / n for i in range(n)]
    return v2.Voiced(Path("x.mp3"), spoken, starts, ends)


def _fake_take(board: dict) -> dict:
    shots = []
    for s in board["shots"]:
        if s["device"] == "card":
            continue  # step cards are drawn, not recorded
        if s["device"] == "footage":
            shots.append({**v2.footage_shot(board, s), "width": 1170, "height": 2078})
            continue
        t, beats = 0.3, []
        for beat in s["beats"]:
            evs = []
            for a in beat["actions"]:
                if a["do"] in ("tap", "highlight", "type", "focus"):
                    evs.append(
                        {
                            "do": a["do"],
                            "t": t + 0.5,
                            "box": {"x": 60, "y": 600, "w": 300, "h": 120},
                            **({"key": True} if a.get("key") else {}),
                        }
                    )
                    t += 1.4
            beats.append({"id": beat["id"], "t0": t - 1.4 * len(evs), "t1": t + 0.2, "events": evs})
            t += 0.4
        shots.append(
            {
                "id": s["id"],
                "device": s["device"],
                "clip": f"{s['id']}.mp4",
                "width": 1170 if s["device"] == "reel" else 2560,
                "height": 2078 if s["device"] == "reel" else 1440,
                "seconds": t + 0.5,
                "beats": beats,
            }
        )
    return {"tutorial": board["id"], "shots": shots}


def test_each_language_gets_its_own_tight_cut_and_reels_stay_short() -> None:
    for b in boards():
        take = _fake_take(b)
        rules = textprep.load_pronounce()
        for fmt in ("reel", "youtube"):
            totals = {}
            for lang in LANGS:
                voices = {}
                for o in v2.spoken_lines(b):
                    said = textprep.spoken(v2.text(o, lang), lang, rules)
                    voices[(id(o), lang)] = _voice(said, len(said) / 14.0)
                items = v2.sequence(b, take, fmt)
                total = v2.lay_out(items, fmt, lang, voices)
                totals[lang] = total
                t = 0.0
                for it in items:
                    assert abs(it.start - t) < 1e-6
                    t += it.dur
                    if it.voice:
                        # The voice fits inside its own item: no line runs into the next shot.
                        assert it.voice_at + it.voice.speech <= it.dur + 1e-6
                    if it.kind not in v2.CARD and it.kind != "step":
                        assert it.src_in <= it.src_out
                        assert it.keys[0][0] == 0.0 and it.keys[-1][0] <= it.dur + 1e-6
            # Tester how-tos go out on WhatsApp and feature videos are short; full tutorials run
            # two minutes or more.
            kind = b.get("kind", "tutorial")
            if fmt == "reel":
                low, high = (18, 48) if kind == "tutorial" else (15, 80)
                assert all(low <= s <= high for s in totals.values()), (b["id"], totals)
            else:
                least = {"tester": 25, "feature": 40}.get(kind, 90)
                assert all(s >= least for s in totals.values()), (b["id"], totals)


def test_captions_follow_the_voice_in_every_track() -> None:
    b = boards()[0]
    take = _fake_take(b)
    items = v2.sequence(b, take, "youtube")
    voices = {(id(o), "hi"): _voice(v2.text(o, "hi"), 4.0) for o in v2.spoken_lines(b)}
    v2.lay_out(items, "youtube", "hi", voices)
    for track in v2.TRACKS:
        cues = v2.track_cues(items, track)
        assert cues, track
        for a, c in zip(cues, cues[1:], strict=False):
            assert a.start < a.end <= c.start + 1e-6
        assert all(len(line) <= 42 for c in cues for line in c.text.split("\n"))
    srt = v2.srt(v2.track_cues(items, "hi-Latn"))
    assert srt.startswith("1\n00:00:0") and "-->" in srt
    assert v2.vtt(v2.track_cues(items, "en")).startswith("WEBVTT\n\n")
    reel_items = v2.sequence(b, take, "reel")
    v2.lay_out(reel_items, "reel", "hi", voices)
    ass = v2.reel_ass(reel_items, "hi-Latn", "Hind")
    assert "Style: Reel,Hind,132" in ass and "{\\c&H00B0EB3D&}" in ass


def test_word_times_are_exact_when_the_caption_matches_the_voice() -> None:
    v = _voice("Tap Call now", 1.2)
    times = v2.word_times(["Tap", "Call", "now"], v)
    assert times[0][0] == 0.0 and abs(times[-1][1] - 1.2) < 1e-9
    # A Roman-script caption of a Devanagari line is spread by characters, still in order.
    v = _voice("Call दबाइए, phone तुरंत लग जाएगा.", 2.0)
    words = ["Call", "dabaiye,", "phone", "turant", "lag", "jaayega."]
    times = v2.word_times(words, v)
    assert [a for a, _ in times] == sorted(a for a, _ in times)


def test_youtube_chapters_start_at_zero_and_last_ten_seconds() -> None:
    b = boards()[0]
    take = _fake_take(b)
    items = v2.sequence(b, take, "youtube")
    voices = {(id(o), "en"): _voice(v2.text(o, "en"), 5.0) for o in v2.spoken_lines(b)}
    total = v2.lay_out(items, "youtube", "en", voices)
    chaps = v2.chapters(b, items, "en", total)
    assert chaps[0][0] == 0.0
    ends = [t for t, _ in chaps[1:]] + [total]
    assert all(e - s >= 10 for (s, _), e in zip(chaps, ends, strict=True))


def test_brand_cards_cache_by_their_html() -> None:
    kit = brand.Kit(Path("/nonexistent"), Path("/nonexistent"))
    assert brand.intro_html(kit, "04", "Call a lead", "Sales X-Ray tutorial") == brand.intro_html(
        kit, "04", "Call a lead", "Sales X-Ray tutorial"
    )
    stage = brand.stage_html(kit)
    assert stage == brand.stage_html(kit) and "mask" in stage
    assert "#0B4A44" in brand.GROUND or "0B4A44" in stage


def test_resolved_storyboard_adds_store_names_and_filled_bars_to_every_screen() -> None:
    b = boards()[0]
    r = v2.resolved(b, {"Asha Fictional": "Asha Kulkarni"})
    for s in r["shots"]:
        dos = [a["do"] for a in s["setup"]]
        assert dos[-2:] == ["marketing", "frost"]
        assert r["shots"][0]["setup"][-2]["names"]["Asha Fictional"] == "Asha Kulkarni"


def test_step_cards_need_no_recording_and_tester_reels_carry_every_step() -> None:
    b = next(x for x in boards() if x["id"] == "t2-install-from-play")
    take = _fake_take(b)
    voices = {(id(o), "mr"): _voice(v2.text(o, "mr"), 3.0) for o in v2.spoken_lines(b)}
    reel = v2.sequence(b, take, "reel")
    assert reel[0].kind == "intro" and reel[-1].kind == "end"
    steps = [it for it in reel if it.kind in ("step", "beat")]
    assert len(steps) == sum(len(s["beats"]) for s in b["shots"])
    v2.lay_out(reel, "reel", "mr", voices)
    for it in reel:
        if it.kind == "step":
            assert it.shot is None and not it.keys and v2.art_key(it) == f"step-{it.spec['id']}"
            assert it.voice_at + it.voice.speech <= it.dur


def test_pack_script_rows_follow_the_cut() -> None:
    from sxtut import pack

    b = next(x for x in boards() if x["id"] == "t5-if-it-hangs")
    cues = [
        {"item": "intro", "in": "00:00:00.000"},
        {"item": "dont", "in": "00:00:05.100"},
        {"item": "refresh", "in": "00:00:12.000"},
        {"item": "outro", "in": "00:00:40.000"},
    ]
    rows = pack.script_rows(b, "hi", cues)
    assert [r["time"] for r in rows] == ["00:00", "00:05", "00:12", "00:40"]
    assert rows[1]["on_screen"].startswith("Screen atki")
    assert rows[2]["on_screen"] == "Phone: Tap “Refresh app data”"  # real phone footage
    assert all(r["say"] and r["roman"] for r in rows)
    assert pack.safe("T1 Join: the testers?") == "T1 Join the testers"


def test_store_names_keep_avatar_initials_in_step() -> None:
    # A renamed fixture person's avatar initials change with the name (Kavya Gokhale shows KG).
    import play_listing as pl

    people = {k: v for k, v in pl.NAMES.items() if re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", k)}
    checked = 0
    for old, new in people.items():
        before = "".join(w[0] for w in old.split())
        after = "".join(w[0] for w in new.split())
        if before in pl.NAMES:
            assert pl.NAMES[before] == after, (old, new)
            checked += 1
    assert checked >= 8
    assert pl.NAMES["Swamini Fictional"] == "Kavya Gokhale"


def test_phone_footage_maps_into_the_reel_frame() -> None:
    # A 1080x2340 phone recording, status bar cropped, is padded at the sides to the reel's 9:16.
    f = {"file": "x.mp4", "size": [1080, 2340], "from": 9.0, "to": 31.5, "crop": [84, 50]}
    left, top, cw, ch, pad, pad_top, s = v2.footage_frame(f)
    assert (left, top, cw, ch, pad, pad_top) == (0, 84, 1080, 2206, 81, 0)
    assert abs((cw + 2 * pad) * s - v2.REEL_W) < 1 and abs(ch * s - v2.REEL_H) < 1
    # A recording with black side bars has them cropped.
    bars = {**f, "size": [720, 1280], "crop": [60, 60, 80, 80]}
    assert v2.footage_frame(bars)[:6] == (80, 60, 560, 1160, 46, 0)
    # In the 9:19.5 phone frame the cropped status and gesture bars come back as black.
    framed = v2.footage_frame(f, v2.FRAME_PHONE)
    assert framed[4] == 0 and framed[5] == round(134 * 84 / 134) and framed[6] == 1
    board = {"id": "t"}
    beat = {
        "id": "b",
        "phone": {
            "at": 9.6,
            "events": [{"do": "tap", "at": 11.7, "box": [0, 84, 100, 50], "key": True}],
        },
    }
    shot = v2.footage_shot(board, {"id": "p", "footage": f, "beats": [beat]})
    assert shot["clip"] == "clips/t--p.mp4" and shot["seconds"] == 22.5
    ev = shot["beats"][0]["events"][0]
    assert shot["beats"][0]["t0"] == 0.6 and ev["t"] == 2.7 and ev["key"]
    assert abs(ev["box"]["x"] - 81 * s) < 1e-6 and ev["box"]["y"] == 0


def test_the_video_list_numbers_and_chains_the_videos_in_order() -> None:
    # Owner, 25 Oct 2026: one numbering 1-11 in the order a tester needs; every "Next" follows it.
    from sxtut import pack

    cat = json.loads((TUT / "videos-v2.json").read_text(encoding="utf-8"))
    by_id = {b["id"]: b for b in boards()}
    ids = [v["id"] for v in cat["videos"]]
    assert len(ids) == len(set(ids)) and set(ids) <= set(by_id)
    for n, tid in enumerate(ids, 1):
        b = by_id[tid]
        assert b["number"] == f"{n:02d}", tid
        nxt = (b.get("next") or {}).get("id")
        assert nxt == (ids[n] if n < len(ids) else None), tid
    names = [pack.video_name(n, v["title"]) for n, v in enumerate(cat["videos"], 1)]
    assert names[0] == "01 Join the testers" and names[8] == "09 All leads - filter and sort"
    assert all(re.fullmatch(r"\d\d [\w ,.()&-]+", n) for n in names)
    assert cat["optin"].startswith("https://play.google.com/apps/testing/")
    # Videos waiting for a re-shoot stay listed with a note, never with old files.
    coming = [v for v in cat["videos"] if v.get("coming")]
    assert all(v["coming"] is True for v in coming) and (not coming or cat["coming"])


def test_framed_shots_sit_in_their_device_and_reels_keep_a_caption_band() -> None:
    # Owner, 25 Oct 2026: a 9:19.5 phone and a 16:10 laptop; captions never on the app.
    phone = {"device": "phone2", "width": 1080, "height": 2340}
    w, h, to = v2.geometry("reel", phone)
    assert (w, h) == (brand.REEL_W, brand.REEL_PIC_H) and w == 1080 and h + brand.REEL_BAND == 1920
    full = to({"x": 0, "y": 0, "w": 1080, "h": 2340})
    hole = brand.REEL_PHONE_HOLE
    assert abs(full["x"] - hole["x"]) < 1e-6 and abs(full["h"] - hole["h"]) < 1
    laptop = {"device": "laptop", "width": 2560, "height": 1600}
    w, h, to = v2.geometry("youtube", laptop)
    assert (w, h) == (brand.STAGE_W, brand.STAGE_H)
    assert abs(to({"x": 0, "y": 0, "w": 2560, "h": 1600})["w"] - brand.YT_LAPTOP_HOLE["w"]) < 1
    assert v2.stage_art("reel", phone) == ["reel-stage", "band"]
    assert v2.stage_art("youtube", laptop) == ["stage-laptop"]
    # Older shots keep the old stage, so their cached cuts stay valid.
    assert v2.stage_art("youtube", {"device": "reel"}) == ["stage"]
    assert v2.stage_art("reel", {"device": "reel"}) == []
    # The chapter tag (bottom left at 1920 wide; a 28-character title is about 700 px) stays clear
    # of the phone's bezel, and of the laptop, which ends above it.
    bezel = brand.YT_PHONE_HOLE["w"] * 0.022
    assert (brand.YT_PHONE_HOLE["x"] - bezel) * 1920 / brand.STAGE_W > 72 + 700
    laptop_bottom = brand.YT_LAPTOP_HOLE["y"] + brand.YT_LAPTOP_HOLE["h"] * 1.06
    assert laptop_bottom * 1080 / brand.STAGE_H < 916
    for b in boards():
        for c in b.get("chapters", []):
            assert all(len(t) <= 28 for t in c["title"].values()), (b["id"], c["id"])
    # Phone footage in a framed board joins the drawn phone at its own 9:19.5.
    f = {"file": "x.mp4", "size": [1080, 2340], "from": 0.0, "to": 5.0, "crop": [84, 50]}
    sspec = {"id": "p", "footage": f, "beats": [{"id": "b", "phone": {"at": 0.5, "events": []}}]}
    assert v2.footage_shot({"id": "t", "frames": True}, sspec)["device"] == "phone2"
    assert v2.footage_shot({"id": "t"}, sspec)["device"] == "footage"
