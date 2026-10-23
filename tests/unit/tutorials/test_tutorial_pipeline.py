"""Sales X-Ray tutorial pipeline: list, scripts, captions, timing and editor timelines.

No network, no browser, no ffmpeg: these check the parts that decide what a tutorial says and when.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TUT = ROOT / "scripts/tutorials"
sys.path.insert(0, str(TUT))

from sxtut import render, textprep, timeline, timing, tts  # noqa: E402

LANGS = ("en", "hi", "mr")


def boards():
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((TUT / "scripts").glob("*.json"))
    ]


def test_every_tutorial_teaches_features_that_are_in_the_catalogue() -> None:
    seed = json.loads((ROOT / "scripts/catalogue/feature_seed.json").read_text(encoding="utf-8"))
    known = {f["id"] for f in seed["features"]}
    listed = json.loads((TUT / "tutorials.json").read_text(encoding="utf-8"))["tutorials"]
    assert 8 <= len(listed) <= 14
    assert len({t["id"] for t in listed}) == len(listed)
    for t in listed:
        assert t["features"], t["id"]
        assert set(t["features"]) <= known, (t["id"], set(t["features"]) - known)


def test_every_storyboard_is_in_the_list_and_uses_fictional_fixture_screens() -> None:
    listed = {
        t["id"]
        for t in json.loads((TUT / "tutorials.json").read_text(encoding="utf-8"))["tutorials"]
    }
    for b in boards():
        assert b["id"] in listed
        for seg in b["segments"]:
            if seg["device"] in ("phone", "desktop"):
                gotos = [
                    a["url"]
                    for a in seg.get("setup", []) + seg.get("actions", [])
                    if a["do"] == "goto"
                ]
                assert gotos and all(u.startswith("/review-fixture/") for u in gotos), (
                    b["id"],
                    seg["id"],
                )


def test_every_line_follows_the_owner_rules_and_hindi_marathi_lines_have_captions() -> None:
    for b in boards():
        for text in (b["title"], b.get("end_headline", ""), b.get("next", "")):
            assert textprep.lint(text) == []
        for seg in b["segments"]:
            assert textprep.lint(seg.get("label", "")) == []
            for lang in LANGS:
                block = seg.get(lang) or {}
                for line in block.get("say", []) + block.get("caption", []):
                    assert textprep.lint(line) == [], (b["id"], seg["id"], lang, line)
                if lang != "en" and block:
                    assert len(block["say"]) == len(block["caption"]), (b["id"], seg["id"], lang)
                    assert all(c.isascii() for c in "".join(block["caption"]).replace("·", "")), (
                        "captions are Roman"
                    )


@pytest.mark.parametrize(
    "line",
    [
        "Plans start at ₹999",
        "It costs nothing",
        "Save 20 minutes a day",
        "Call 98765 43210",
        "Mail sam@example.com",
        "बस 5 मिनट",
    ],
)
def test_lint_refuses_prices_minutes_numbers_and_emails(line: str) -> None:
    assert textprep.lint(line)


def test_product_names_are_spoken_as_the_team_says_them_but_captions_keep_the_written_form() -> (
    None
):
    rules = textprep.load_pronounce()
    assert textprep.spoken("Brain 4.0 scores it", "en", rules) == "Brain four point oh scores it"
    assert (
        textprep.spoken("Sales X-Ray में Brain 4.0", "hi", rules)
        == "Sales X-Ray में Brain four point oh"
    )


def test_the_hearing_check_accepts_how_speech_to_text_spells_the_product() -> None:
    pronounce = json.loads((TUT / "pronounce.json").read_text(encoding="utf-8"))
    got = tts.heard("नमस्ते SalesXRay में ... Brain 4.0 पूरा report", pronounce)
    assert got == {"Brain 4.0": True, "Sales X-Ray": True}
    assert tts.heard("hello there", pronounce) == {"Brain 4.0": False, "Sales X-Ray": False}


def test_a_line_is_cached_by_everything_that_shapes_its_audio() -> None:
    cast = json.loads((TUT / "voices.json").read_text(encoding="utf-8"))
    a = tts.line_from_cast("Open Leads.", "en", cast)
    assert a.key() == tts.line_from_cast("Open Leads.", "en", cast).key()
    assert a.key() != tts.line_from_cast("Open Leads!", "en", cast).key()
    assert a.key() != tts.line_from_cast("Open Leads.", "en", cast, "alt").key()


def test_the_key_never_reaches_chromium_or_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "not-a-real-key")
    assert "ELEVENLABS_API_KEY" not in render.safe_env()


def test_phrase_times_come_from_character_alignment() -> None:
    text, spans = timing.phrase_spans(["Open Leads.", "Tap Call."])
    assert text == "Open Leads. Tap Call."
    assert spans == [(0, 11), (12, 21)]
    starts = [i * 0.1 for i in range(len(text))]
    align = {
        "character_start_times_seconds": starts,
        "character_end_times_seconds": [s + 0.1 for s in starts],
    }
    assert timing.span_times(align, spans) == [
        (0.0, pytest.approx(1.1)),
        (pytest.approx(1.2), pytest.approx(2.1)),
    ]


def test_one_picture_timeline_fits_the_longest_language() -> None:
    segs = [
        timing.Seg("a", "phone", 3.0, {"en": 2.0, "hi": 4.2, "mr": 3.9}),
        timing.Seg("b", "phone", 5.0, {"en": 1.0}),
    ]
    total = timing.layout(segs, 0.0, 0.0)
    assert segs[0].dur == pytest.approx(
        timing.frames(timing.LEAD_S + 4.2 + timing.TAIL_S) / timing.FPS
    )
    assert segs[1].dur == pytest.approx(5.0)
    assert segs[1].start == pytest.approx(segs[0].dur)
    assert total == pytest.approx(segs[0].dur + segs[1].dur)
    for s in segs:
        assert (s.dur * timing.FPS) == pytest.approx(round(s.dur * timing.FPS))


def test_captions_are_two_short_lines_at_most_and_srt_is_well_formed() -> None:
    long = (
        "Sales X-Ray agla lead saamne la deta hai, opener aur jawaab ready ke saath, "
        "aur aapka poora din set."
    )
    cues = timing.cues_for(10.0, [long, "Bas itna hi."], [(0.0, 6.0), (6.2, 7.0)], "phone")
    assert all(len(c.text.split("\n")) <= timing.MAX_LINES for c in cues)
    assert all(len(line) <= timing.MAX_LINE for c in cues for line in c.text.split("\n"))
    assert cues[0].start == pytest.approx(10.0 + timing.LEAD_S)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(cues, cues[1:], strict=False))
    srt = timing.srt(cues)
    assert srt.startswith("1\n00:00:10,350 --> ")
    assert timing.tc(3723.5) == "01:02:03,500"
    assert "\\N" in timing.ass(cues, "Plus Jakarta Sans") or all("\n" not in c.text for c in cues)


def test_editor_timelines_are_valid_xml_with_one_audio_role_per_language(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    items = [
        timeline.Item("still", media / "title.png", 0.0, 2.5, 2.5, name="title"),
        timeline.Item("video", media / "clip a.mp4", 2.5, 4.0, 4.0, 1170, 2532, name="s1"),
    ]
    items += [
        timeline.Item(
            "audio", media / f"s1-{lang}.mp3", 2.85, 3.0, 3.0, lane=lang, name=f"s1 {lang}"
        )
        for lang in LANGS
    ]
    # Parsing XML this test just generated, not outside input.
    fcp_text = timeline.fcpxml("04 Call a lead", items, 6.5, tmp_path).split("\n", 2)[2]
    fcp = ET.fromstring(fcp_text)  # noqa: S314
    roles = {c.get("audioRole") for c in fcp.iter("asset-clip") if c.get("audioRole")}
    assert roles == {"dialogue.en", "dialogue.hi", "dialogue.mr"}
    assert {r.get("src") for r in fcp.iter("media-rep")} >= {
        "media/clip%20a.mp4",
        "media/title.png",
    }
    seq = fcp.find(".//sequence")
    assert seq is not None and seq.get("duration") == "195/30s"
    xm_text = timeline.xmeml("04 Call a lead", items, 6.5, tmp_path).split("\n", 2)[2]
    xm = ET.fromstring(xm_text)  # noqa: S314
    assert len(xm.findall(".//audio/track")) == 3
    assert [c.findtext("start") for c in xm.findall(".//video/track/clipitem")] == ["0", "75"]


def test_long_captions_break_at_commas_into_even_lines() -> None:
    line = (
        "Computer pe owners aur managers ko poori team dikhti hai: kaun call kar raha hai, "
        "kaun late chal raha hai, aur leads stages mein kaise aage badh rahe hain."
    )
    cues = timing.chunk(line, 0.0, 9.0, "desktop")
    assert len(cues) == 3
    assert not any(c.text.split()[-1] in ("aur", "and", "ya", "or") for c in cues)
    assert (
        timing.two_lines("Brain 4.0 turns it into a Report.") == "Brain 4.0 turns it into a Report."
    )
    two = timing.two_lines(
        "Sales X-Ray agla lead saamne la deta hai, opener aur jawaab ready ke saath."
    )
    top, bottom = two.split("\n")
    assert abs(len(top) - len(bottom)) <= 12
