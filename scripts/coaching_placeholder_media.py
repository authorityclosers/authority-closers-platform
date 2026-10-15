"""Package Strike F's verified neutral-voice placeholder narrations for Coaching.

Owner instruction, 11 Oct 2026 14:15 IST: use Strike F's neutral-voice
narration and topic slide videos as Dipak's clips. This reads the verified
`synthetic-v1/coaching-media` topics, writes a compact manifest, and copies
audio only for each skill's free topic (the top-priority one). Locked topics
ship metadata, a short text teaser and only the first 15 seconds of audio (a
separate cut file), so the free preview is all a URL can ever fetch; the rest
belongs to the full coaching. Narration is a labelled placeholder; it never
imitates Dipak. Needs ffmpeg/ffprobe for the preview cuts (stream copy, no
re-encode, no metadata).

Usage: python scripts/coaching_placeholder_media.py [SYNTHETIC_ROOT]
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages/python/ac_platform/coaching/placeholder_media"
SKILLS = {
    "skill-1": "human_connection_trust",
    "skill-2": "discovery_deep_understanding",
    "skill-3": "qualification",
    "skill-4": "problem_impact_desire",
    "skill-5": "solution_relevance_presentation",
    "skill-6": "certainty_objection_intelligence",
    "skill-7": "closing_decision_management",
    "skill-8": "communication_tonality",
}
GAPS = {"Judgment": "judgment", "Execution": "execution", "Confidence": "confidence"}
# The free preview of a locked lesson (the brief's "clip preview hook").
PREVIEW_MS = 15_000


def cut_preview(audio: Path, target: Path) -> int:
    """The first PREVIEW_MS of `audio` as its own file; returns its real length."""
    subprocess.run(  # noqa: S603 - fixed ffmpeg argv over local dataset files, no shell
        [  # noqa: S607
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio),
            "-t",
            f"{PREVIEW_MS / 1000:.3f}",
            "-map",
            "0:a:0",
            "-c:a",
            "copy",
            "-map_metadata",
            "-1",
            "-id3v2_version",
            "0",
            "-write_xing",
            "0",
            "-fflags",
            "+bitexact",
            str(target),
        ],
        check=True,
    )
    probe = subprocess.run(  # noqa: S603 - fixed ffprobe argv, no shell
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(float(probe.stdout.strip()) * 1000)


def build(source: Path) -> dict[str, Any]:
    topics: list[dict[str, Any]] = []
    for path in sorted((source / "coaching-media").glob("syn-coach-*.json")):
        record = json.loads(path.read_text())
        segments = [s for s in record.get("segments", []) if s.get("playable")]
        audio = source / str(record.get("audio_path", ""))
        if (
            record.get("audio_status") != "verified"
            or record.get("placeholder") is not True
            or record.get("voice") != "neutral"
            or record.get("skill") not in SKILLS
            or not segments
            or not audio.is_file()
        ):
            continue
        segment = segments[0]
        slide = segment.get("slide") or {}
        bullets = [str(b) for b in slide.get("bullets", []) if str(b).strip()][:5]
        topics.append(
            {
                "topic_id": record["id"],
                "title": record["title"],
                "kind": record["kind"],
                "skill_id": SKILLS[record["skill"]],
                "gap_type": GAPS.get(record.get("gap_type", ""), "uncertain"),
                "topic_tag": record.get("topic_tag") or "",
                "priority": int(record.get("priority_order") or 999),
                "start_ms": int(segment["start_ms"]),
                "end_ms": int(segment["end_ms"]),
                "narration": str(record.get("narration_script_text") or segment["text"]),
                "slides": (
                    [
                        {
                            "segment_id": segment["id"],
                            "title": slide["title"],
                            "bullets": bullets,
                        }
                    ]
                    if slide.get("title") and bullets
                    else []
                ),
                "takeaways": bullets or [record["title"]],
                "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                "audio_bytes": audio.stat().st_size,
                "_audio": audio,
            }
        )
    free: dict[str, str] = {}
    for topic in sorted(topics, key=lambda t: (t["priority"], t["topic_id"])):
        free.setdefault(topic["skill_id"], topic["topic_id"])
    TARGET.mkdir(parents=True, exist_ok=True)
    for old in TARGET.glob("*.mp3"):
        old.unlink()
    manifest = []
    for topic in sorted(topics, key=lambda t: (t["skill_id"], t["priority"])):
        audio = topic.pop("_audio")
        topic["free"] = free[topic["skill_id"]] == topic["topic_id"]
        if topic["free"]:
            shutil.copyfile(audio, TARGET / f"{topic['topic_id']}.mp3")
        else:
            # A teaser only: the full narration belongs to the full coaching.
            topic["narration"] = topic["narration"][:160].rsplit(" ", 1)[0] + "…"
            if topic["start_ms"] == 0 and topic["end_ms"] > PREVIEW_MS + 5_000:
                cut = TARGET / f"{topic['topic_id']}.preview.mp3"
                length = cut_preview(audio, cut)
                topic["preview_ms"] = min(length, PREVIEW_MS)
                topic["preview_sha256"] = hashlib.sha256(cut.read_bytes()).hexdigest()
                topic["preview_bytes"] = cut.stat().st_size
        manifest.append(topic)
    return {
        "schema": "ac.sales-xray.coaching-placeholder-media/1",
        "source": "Strike F synthetic-v1 coaching-media, verified neutral narration",
        "topics": manifest,
    }


if __name__ == "__main__":
    data = build(Path(sys.argv[1] if len(sys.argv) > 1 else "/home/acdev/datasets/synthetic-v1"))
    (TARGET / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    free = sum(t["free"] for t in data["topics"])
    previews = sum("preview_ms" in t for t in data["topics"])
    print(f"{len(data['topics'])} topics, {free} free with audio, {previews} previews")
