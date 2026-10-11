"""Exact-manifest import of Strike F drafts into noncanonical review proposals.

Draft skill/gap labels are preserved, never mapped by number, title or prose.
Estimated duration is not a source timestamp. This importer cannot recommend,
approve, activate, synthesize or queue a clip, and never writes the input data.
"""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ac_platform.coaching.contracts import Model
from ac_platform.coaching.dataset import DATASET_ROOT, SHA_PATTERN, TOPIC_PATTERN
from ac_platform.conversation_intelligence.checkpoints import content_hash

SCRIPTS_ROOT = Path("/home/acdev/datasets/dipak-scripts")
MAX_TOPICS = 150


class DraftSegment(Model):
    segment_id: str
    draft_skill: str
    draft_gap_type: str
    text_sha256: str = Field(pattern=SHA_PATTERN)
    estimated_duration_ms: int = Field(gt=0, strict=True)
    timing_source: Literal["estimated"] = "estimated"
    playable: Literal[False] = False


class TopicReviewProposal(Model):
    topic_id: str = Field(pattern=TOPIC_PATTERN)
    title: str
    kind: Literal["audio", "video"]
    placeholder: Literal[True] = True
    voice: Literal["neutral"] = "neutral"
    source_schema: Literal["coaching-media/1"] = "coaching-media/1"
    export_sha256: str = Field(pattern=SHA_PATTERN)
    source_document_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    script_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    script_origin: Literal["provided_docx", "locally_authored_placeholder", "roadmap_title_only"]
    draft_skill: str
    draft_gap_type: str
    segments: tuple[DraftSegment, ...]
    # These are proposals, not declarations of author-approved teaching tags.
    canonical_skill_id: None = None
    canonical_gap_type: None = None
    review_state: Literal["pending_review"] = "pending_review"
    playback_state: Literal["unavailable"] = "unavailable"


class DraftBatch(Model):
    schema_id: Literal["ac.sales-xray.coaching-draft-proposals/1"] = Field(
        default="ac.sales-xray.coaching-draft-proposals/1", alias="schema"
    )
    index_sha256: str = Field(pattern=SHA_PATTERN)
    proposals: tuple[TopicReviewProposal, ...] = Field(max_length=MAX_TOPICS)
    rejected_records: int = Field(ge=0)
    manifest_limited: bool = False
    queue_is_canonical: Literal[False] = False

    @property
    def sha256(self) -> str:
        return content_hash(self.model_dump(mode="json", by_alias=True))


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A draft metadata field is missing.")
    return value


def _bounded_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024:
        raise ValueError("A bounded regular draft export is required.")
    data = path.read_bytes()
    if len(data) > 512 * 1024:
        raise ValueError("Draft changed during read.")
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise ValueError("A draft export must be an object.")
    return data, raw


def _source_hashes(index: dict[str, Any], scripts_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    documents = index.get("source_documents", [])
    if not isinstance(documents, list):
        return hashes
    for document in documents[:10]:
        try:
            declared = _text(document["path"])
            path = Path(declared).resolve(strict=True)
            if not path.is_relative_to(scripts_root.resolve(strict=True)) or not path.is_file():
                continue
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual == document["sha256"]:
                hashes[declared] = actual
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return hashes


def _proposal(
    raw: dict[str, Any], data: bytes, source_hashes: dict[str, str]
) -> TopicReviewProposal:
    topic_id = _text(raw.get("id"))
    if (
        raw.get("schema_version") != "coaching-media/1"
        or raw.get("synthetic") is not True
        or raw.get("placeholder") is not True
        or raw.get("voice") != "neutral"
    ):
        raise ValueError("An explicitly labelled placeholder draft is required.")
    origin = raw.get("script_origin")
    declared_source = raw.get("source_docx")
    source_sha = source_hashes.get(declared_source) if isinstance(declared_source, str) else None
    if origin == "provided_docx" and source_sha is None:
        raise ValueError("The supplied script must match its exact manifest source hash.")
    script = raw.get("script_text")
    if not isinstance(script, str):
        raise ValueError("A draft needs explicit text, including empty title-only text.")
    segments = []
    rows = raw.get("segments")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("A bounded segment list is required.")
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("topic_id") != topic_id
            or row.get("playable") is not False
            or row.get("timing_source") != "estimated"
            or row.get("placeholder") is not True
            or row.get("voice") != "neutral"
        ):
            raise ValueError("Draft segments cannot claim verified playback or cross topics.")
        segments.append(
            DraftSegment(
                segment_id=_text(row.get("id")),
                draft_skill=_text(row.get("skill")),
                draft_gap_type=_text(row.get("gap_type")),
                text_sha256=hashlib.sha256(_text(row.get("text")).encode()).hexdigest(),
                estimated_duration_ms=row["estimated_duration_ms"],
            )
        )
    if len({s.segment_id for s in segments}) != len(segments):
        raise ValueError("Draft segment IDs must be unique.")
    return TopicReviewProposal(
        topic_id=topic_id,
        title=_text(raw.get("title")),
        kind=raw.get("kind"),
        export_sha256=hashlib.sha256(data).hexdigest(),
        source_document_sha256=source_sha,
        script_sha256=hashlib.sha256(script.encode()).hexdigest() if script.strip() else None,
        script_origin=origin,
        draft_skill=_text(raw.get("skill")),
        draft_gap_type=_text(raw.get("gap_type")),
        segments=tuple(segments),
    )


def import_drafts(root: Path = DATASET_ROOT, scripts_root: Path = SCRIPTS_ROOT) -> DraftBatch:
    """Exact index IDs only. An invalid topic is counted, never activated."""
    data, index = _bounded_json(root / "index.json")
    if (
        index.get("schema_version") != "coaching-media/1"
        or index.get("synthetic") is not True
        or index.get("placeholder") is not True
        or index.get("voice") != "neutral"
        or not isinstance(index.get("topics"), list)
    ):
        raise ValueError("The declared Strike F manifest is required.")

    sources = _source_hashes(index, scripts_root)
    proposals, seen = [], set()
    rejected = 0
    for item in index["topics"][:MAX_TOPICS]:
        try:
            topic_id = _text(item.get("id"))
            if not re.fullmatch(TOPIC_PATTERN, topic_id) or topic_id in seen:
                raise ValueError("An exact unique manifest ID is required.")
            seen.add(topic_id)
            topic_data, raw = _bounded_json(root / f"{topic_id}.json")
            if raw.get("id") != topic_id:
                raise ValueError("Topic identity differs from the declared manifest.")
            proposals.append(_proposal(raw, topic_data, sources))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            rejected += 1
    return DraftBatch(
        index_sha256=hashlib.sha256(data).hexdigest(),
        proposals=tuple(proposals),
        rejected_records=rejected,
        manifest_limited=len(index["topics"]) > MAX_TOPICS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DATASET_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, help="Write an immutable private proposal snapshot."
    )
    args = parser.parse_args()
    batch = import_drafts(args.root)
    if args.output_dir is not None:
        path = args.output_dir / f"topic-proposals-{batch.sha256[:16]}.json"
        serialized = batch.model_dump_json(by_alias=True, indent=2) + "\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.is_symlink():
                raise ValueError("Review snapshots must be regular private files.") from None
            if path.read_text() != serialized:
                raise ValueError(
                    "Existing snapshot differs; never overwrite review history."
                ) from None
        else:
            with os.fdopen(descriptor, "w") as output:
                output.write(serialized)
    print(
        json.dumps(
            {
                "records": len(batch.proposals),
                "rejected": batch.rejected_records,
                "origin_counts": {
                    origin: sum(p.script_origin == origin for p in batch.proposals)
                    for origin in [
                        "provided_docx",
                        "locally_authored_placeholder",
                        "roadmap_title_only",
                    ]
                },
                "segments": sum(len(p.segments) for p in batch.proposals),
                "playable": 0,
                "canonical_queue": False,
                "batch_sha256": batch.sha256,
            }
        )
    )


if __name__ == "__main__":
    main()
