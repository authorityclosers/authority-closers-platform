"""Pure, display-only word attribution. Callers supply authorized projected C2 data.

Source interfaces accept already validated decisions; model parsing and channel capture
belong to later slices. Nothing here establishes identity or enforces report scoring.
"""

from __future__ import annotations

import re
import unicodedata as unicode
from typing import Any, Literal, NotRequired, TypedDict

from .checkpoints import content_hash

Role = Literal["you", "salesperson", "prospect", "other"]


class SpeakerDecision(TypedDict):
    speaker_id: str
    role: NotRequired[Role | None]
    display_name: NotRequired[str | None]
    icon: NotRequired[str | None]
    spoken_name: NotRequired[str | None]
    evidence_segment_ids: NotRequired[list[str]]
    confidence: NotRequired[Literal["low", "medium", "high"] | None]


class SpeakerMapRevision(TypedDict):
    transcript_revision: str
    speakers: list[SpeakerDecision]
    revision: NotRequired[int]


class SavedChannelMap(SpeakerMapRevision):
    saved_you_side: Literal[0, 1]


_STOP_WORDS = (
    "है हूं हूँ से जी आप मैं हम हां सर मेरा मेरी sir ji madam the a an there my i i'm your "
    "calling speaking just happy glad looking sure sorry fine good great well ok okay not "
    "very really also interested busy going trying back available free here regarding about "
    "from for with dr dr. mr mr. mrs ms"
)
NOT_NAMES = set(_STOP_WORDS.split())
SUFFIX = (
    r"(?:here|speaking|this side|बोल रहा(?:\s+(?:हूं|हूँ))?|"
    r"बोल रही(?:\s+(?:हूं|हूँ))?|bol raha|bol rahi)"
)
BOUNDARY = r"(?:(?<=[A-Za-z0-9_])(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])(?=[A-Za-z0-9_]))"
CUES = {
    "introduced_own_company": (
        r"\b(?:(?:this is|my name is|i am|myself).*?\bfrom|from our company|"
        r"from authority closers|our team)\b|हमारी कंपनी|मैं team से"
    ),
    "stated_call_purpose": (
        r"\b(?:calling about|calling to|reason for (?:my|this) call)\b|कॉल का कारण"
    ),
    "asked_discovery_question": (
        r"\b(?:tell me about your|what does that cost|what is your current)\b|आपका.*\?"
    ),
    "presented_offer_or_price": (
        r"\b(?:our (?:offer|price|plan)|we (?:offer|charge))\b|हमारा (?:ऑफर|प्लान)"
    ),
    "proposed_next_step": r"\b(?:shall we schedule|let's schedule|next step is)\b|अगला कदम",
}


def _evidence(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": segment["id"],
        "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"],
    }


def _segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    """Use C2's native evidence clocks even when playback clamped its final tail."""
    native = {
        row["id"]: row for row in transcript.get("playback_projection", {}).get("segments", [])
    }
    return [
        {**row, "end_ms": native.get(row["id"], {}).get("native_end_ms", row["end_ms"])}
        for row in transcript["segments"]
    ]


def _leader(scores: dict[str, int], minimum: int) -> str | None:
    ranked = sorted(scores, key=lambda key: scores[key], reverse=True)
    if not ranked or scores[ranked[0]] < minimum:
        return None
    return ranked[0] if len(ranked) == 1 or scores[ranked[0]] > scores[ranked[1]] else None


def is_account_name(spoken: str | None, account_name: str | None) -> bool:
    first = (account_name or "").split()
    return bool(spoken and first and re.sub(r"\s+जी$", "", spoken).lower() == first[0].lower())


def _names(
    segments: list[dict[str, Any]], voices: list[str]
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    # Build exact Unicode L/M and punctuation classes from the input: stdlib re
    # lacks JS's property escapes. Do not fold or transliterate spoken spelling.
    chars = set("".join(row["text"] for row in segments))
    letters = re.escape("".join(sorted(c for c in chars if unicode.category(c)[0] in "LM"))) or "\0"
    punctuation = re.escape("".join(sorted(c for c in chars if unicode.category(c)[0] == "P")))
    name = rf"([{letters}][{letters}'’\-]*)(?![{letters}])"
    start = rf"(?<![{letters}])"
    patterns = [
        (rf"{start}(?:मेरा नाम|my name is|myself|this is)\s+{name}", False),
        (rf"{start}(?:i am|i'm)\s+{name}", True),
        (rf"{start}(?:मैं|main)\s+{name}\s+(?:बोल रहा|बोल रही|bol raha|bol rahi)", False),
        (rf"^[\s{punctuation}]*{name}\s+{SUFFIX}(?=\s|$|[,.!?])", True),
        (rf"{start}(?:hi|hello|hey)\s+{name}\s+{SUFFIX}(?=\s|$|[,.!?])", True),
    ]
    greetings = [
        rf"{start}{name}\s+जी\s*,?\s*(?:नमस्ते|नमस्कार)",
        rf"{start}(?:नमस्ते|नमस्कार|hello|hi|hey)\s+{name}(\s+जी)?(?!\s+{SUFFIX}(?=\s|$|[,.!?]))",
    ]
    names: dict[str, str] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        if segment["start_ms"] > 150_000:
            break
        voice = segment["speaker_id"]
        if voice not in voices:
            continue
        candidates = [(pattern, styled, voice, False) for pattern, styled in patterns]
        if len(voices) == 2:
            other = next(key for key in voices if key != voice)
            candidates += [(pattern, False, other, True) for pattern in greetings]
        for pattern, styled, target, greeting in candidates:
            match = re.search(pattern, segment["text"], re.I)
            if not match:
                continue
            word = match[1]
            script = unicode.name(word[0], "")
            style = ("LATIN" in script and word[0].isupper()) or (
                "DEVANAGARI" in script and unicode.category(word[0]).startswith("L")
            )
            if len(word) < 2 or word.lower() in NOT_NAMES or (styled and not style):
                continue
            if target not in names:
                honorific = greeting and re.search(r"जी\s*,?\s*(?:नमस्ते|नमस्कार)|\s+जी$", match[0])
                names[target] = word + (" जी" if honorific else "")
                evidence[target] = [_evidence(segment)]
    return names, evidence


def _you(segments: list[dict[str, Any]], voices: list[str], account: str | None) -> str | None:
    first = (account or "").split()
    if len(voices) < 2 or not first or len(first[0]) < 2:
        return None
    name = re.escape(first[0])
    intro = (
        rf"{BOUNDARY}(?:this is|i am|i'm|my name is|myself)\s+{name}{BOUNDARY}|"
        rf"{BOUNDARY}{name}\s+(?:here|speaking|this side){BOUNDARY}|(?:मैं|मेरा नाम)\s+{name}"
    )
    greet = (
        rf"{BOUNDARY}(?:hi|hello|hey|thanks|thank you|namaste|namaskar)\s+{name}{BOUNDARY}|"
        rf"{BOUNDARY}{name}\s+(?:ji|sir|bhai|bhaiya){BOUNDARY}"
    )
    scores: dict[str, int] = {}
    for segment in segments:
        voice = segment["speaker_id"]
        if voice not in voices:
            continue
        if re.search(intro, segment["text"], re.I):
            scores[voice] = scores.get(voice, 0) + 3
        elif len(voices) == 2 and re.search(greet, segment["text"], re.I):
            other = next(key for key in voices if key != voice)
            scores[other] = scores.get(other, 0) + 2
    return _leader(scores, 2)


def predict_speaker_map(
    transcript: dict[str, Any] | None, *, account_holder_name: str | None
) -> dict[str, Any]:
    """Predict only from C2 words; coaching evidence cannot assert account ownership."""
    result: dict[str, Any] = {
        "schema": "ac.sales-xray.speaker-map/1",
        "status": "unavailable" if transcript is None else "predicted",
        "unavailable_reason": "transcript_not_ready" if transcript is None else None,
        "transcript_revision": transcript["revision"] if transcript is not None else None,
        "map_revision": None,
        "user_revision": 0,
        "speakers": [],
        "report_basis": None,
    }
    if transcript is None:
        return result
    segments = _segments(transcript)
    ids = list(
        dict.fromkeys(row["speaker_id"] for row in segments if row["speaker_id"] is not None)
    )
    voices = [key for key in ids if key != "unattributed"]
    names, evidence = _names(segments, voices)
    suggested = _you(segments, voices, account_holder_name)
    matches = [key for key in voices if is_account_name(names.get(key), account_holder_name)]
    you = (
        suggested
        if suggested in matches
        else (matches[0] if len(matches) == 1 and len(voices) > 1 else None)
    )
    cues: dict[str, list[dict[str, Any]]] = {key: [] for key in ids}
    for segment in segments:
        voice = segment["speaker_id"]
        if voice not in voices:
            continue
        if voice == you and not cues[voice]:
            cues[voice].append({"cue": "stated_account_holder_name", **evidence[voice][0]})
        for cue, pattern in CUES.items():
            if len(cues[voice]) < 5 and re.search(pattern, segment["text"], re.I):
                cues[voice].append({"cue": cue, **_evidence(segment)})
    seller = _leader({key: len(value) for key, value in cues.items() if key in voices}, 1)
    for number, key in enumerate(ids, 1):
        role = "you" if key == you else "salesperson" if key == seller else None
        if role is None and seller and len(voices) == 2 and key in voices:
            role = "prospect"
        result["speakers"].append(
            {
                "speaker_id": key,
                "number": number,
                "role": role,
                "role_source": "predicted" if role else None,
                "display_name": account_holder_name.strip()
                if role == "you" and account_holder_name
                else names.get(key),
                "name_source": "account_profile"
                if role == "you"
                else "stated_in_call"
                if key in names
                else None,
                "name_evidence": evidence.get(key, []),
                "role_cues": cues[key],
                "channel": None,
                "confidence": None,
            }
        )
    result["map_revision"] = content_hash(
        {"transcript_revision": result["transcript_revision"], "speakers": result["speakers"]}
    )
    return result


def resolve_speaker_map(
    transcript: dict[str, Any] | None,
    *,
    account_holder_name: str | None,
    user_revision: SpeakerMapRevision | None = None,
    saved_channel: SavedChannelMap | None = None,
    model_revision: SpeakerMapRevision | None = None,
) -> dict[str, Any]:
    """Merge per field. Model data must already have passed S5 validation."""
    result = predict_speaker_map(transcript, account_holder_name=account_holder_name)
    if transcript is None:
        return result
    text = result["speakers"]
    known = {row["speaker_id"] for row in text}
    segments = _segments(transcript)
    names, evidence = _names(
        segments,
        [row["speaker_id"] for row in text if row["speaker_id"] != "unattributed"],
    )
    diagnostics = []
    for source, revision in (
        ("model", model_revision),
        ("channel", saved_channel),
        ("confirmed", user_revision),
    ):
        if revision is None:
            continue
        entries = revision["speakers"]
        ids = [row["speaker_id"] for row in entries]
        if (
            revision["transcript_revision"] != transcript["revision"]
            or len(set(ids)) != len(ids)
            or not set(ids) <= known
            or sum(row.get("role") == "you" for row in entries) > 1
        ):
            diagnostics.append("speaker_map_source_invalid_" + source)
            continue
        if (
            source == "channel"
            and saved_channel is not None
            and saved_channel.get("saved_you_side") not in (0, 1)
        ):
            diagnostics.append("speaker_map_source_invalid_channel")
            continue
        by_id = {row["speaker_id"]: row for row in entries}
        for speaker in result["speakers"]:
            decision: SpeakerDecision | dict[str, Any] = by_id.get(speaker["speaker_id"], {})
            if speaker["speaker_id"] == "unattributed":
                continue
            if "role" in decision:
                role = decision["role"]
                spoken = decision.get("spoken_name", decision.get("display_name")) or names.get(
                    speaker["speaker_id"]
                )
                if (
                    source == "model"
                    and role == "you"
                    and not is_account_name(spoken, account_holder_name)
                ):
                    role = "salesperson"
                speaker.update(role=role, role_source=source if role else None)
            if source != "channel" and ("display_name" in decision or "spoken_name" in decision):
                name = decision.get("display_name", decision.get("spoken_name"))
                speaker.update(
                    display_name=name or names.get(speaker["speaker_id"]),
                    name_source=("user" if source == "confirmed" else "model")
                    if name
                    else "stated_in_call"
                    if speaker["speaker_id"] in names
                    else None,
                )
                speaker["name_evidence"] = (
                    []
                    if name and source == "confirmed"
                    else evidence.get(speaker["speaker_id"], [])
                )
            if source == "model" and decision:
                speaker["confidence"] = decision.get("confidence")
                if decision.get("evidence_segment_ids"):
                    speaker["name_evidence"] = [
                        _evidence(row)
                        for row in segments
                        if row["id"] in decision["evidence_segment_ids"]
                    ]
        if source == "confirmed":
            for speaker in result["speakers"]:
                decision = by_id.get(speaker["speaker_id"], {})
                if speaker["speaker_id"] != "unattributed" and "icon" in decision:
                    speaker["icon"] = decision["icon"]
            result["user_revision"] = revision.get("revision", 0)
    priority = {None: 0, "predicted": 1, "model": 2, "channel": 3, "confirmed": 4}
    holders = sorted(
        (row for row in result["speakers"] if row["role"] == "you"),
        key=lambda row: priority[row["role_source"]],
        reverse=True,
    )
    for extra in holders[1:]:
        extra.update(role="salesperson")
    for speaker in result["speakers"]:
        if speaker["role"] == "you" and speaker["name_source"] != "user" and account_holder_name:
            speaker.update(display_name=account_holder_name.strip(), name_source="account_profile")
        elif speaker["role"] != "you" and speaker["name_source"] == "account_profile":
            speaker.update(
                display_name=names.get(speaker["speaker_id"]),
                name_source="stated_in_call" if speaker["speaker_id"] in names else None,
                name_evidence=evidence.get(speaker["speaker_id"], []),
            )
        if speaker["role_source"] != "model" and speaker["name_source"] != "model":
            speaker["confidence"] = None
    result["diagnostics"] = diagnostics
    result["map_revision"] = content_hash(
        {
            "transcript_revision": result["transcript_revision"],
            # Presentation choices must not change the map used by report provenance.
            "speakers": [
                {key: value for key, value in row.items() if key != "icon"}
                for row in result["speakers"]
            ],
        }
    )
    origin = project_speaker_roles(result)["origin"]
    result["status"] = {
        "user_confirmed_roles": "confirmed",
        "channel_mapped_roles": "channel",
        "model_named_roles": "model_named",
    }.get(origin, "predicted")
    if result["status"] == "predicted" and any(
        row["name_source"] == "model" for row in result["speakers"]
    ):
        result["status"] = "model_named"
    return result


def project_speaker_roles(speaker_map: dict[str, Any]) -> dict[str, Any]:
    """Names-free snapshot; mixed/unresolved attribution never gains authority."""
    rows = [row for row in speaker_map["speakers"] if row["speaker_id"] != "unattributed"]
    sources = {row["role_source"] for row in rows}
    origin = "unverified_provider_labels"
    if rows and None not in sources:
        origin = (
            "text_predicted_roles"
            if "predicted" in sources
            else "model_named_roles"
            if "model" in sources
            else "user_confirmed_roles"
            if "confirmed" in sources
            else "channel_mapped_roles"
        )
    return {
        "origin": origin,
        "transcript_revision": speaker_map["transcript_revision"],
        "map_revision": speaker_map["map_revision"],
        "speakers": [
            {
                "speaker_id": row["speaker_id"],
                "role": "seller" if row["role"] in ("you", "salesperson") else row["role"],
                "is_account_holder": row["role"] == "you",
            }
            for row in rows
            if row["role"] is not None
        ],
    }
