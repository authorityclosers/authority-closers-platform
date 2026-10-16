"""Simulated calls for the Sales Xray CRM (slice d, 15 Oct sync).

"Press call, a synthetic call is generated and appears in the pipeline."
Until a calling provider passes its gates, a desk call takes one of the
fictional sales-call recordings that matches the lead's language (and its
business, for test leads) and runs it through the normal upload and analysis.
Nobody is dialled. The recordings and their catalogue live in a read-only
folder set by ``lead_desk_simulation_root``; without it the feature is off.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

SAMPLE_ID: Final = re.compile(r"\Asyn-[A-Za-z0-9._-]{1,150}\Z")
_CODES: Final[dict[str, str]] = {
    "english": "en",
    "hindi": "hi",
    "marathi": "mr",
    "gujarati": "gu",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "bengali": "bn",
    "bangla": "bn",
    "punjabi": "pa",
    "odia": "or",
    "urdu": "ur",
}


@dataclass(frozen=True, slots=True)
class Sample:
    sample_id: str
    file: str
    language_mix: str
    business_id: str
    business_name: str
    duration_ms: int

    @property
    def languages(self) -> frozenset[str]:
        return frozenset(part for part in self.language_mix.lower().split("-") if part)


_cache: dict[str, tuple[float, tuple[Sample, ...]]] = {}


def catalogue(root: str | None) -> tuple[Sample, ...]:
    """The samples in ``root``/catalogue.json whose recording exists. Empty when off."""
    if not root:
        return ()
    folder = Path(root)
    index = folder / "catalogue.json"
    try:
        stamp = index.stat().st_mtime
    except OSError:
        return ()
    cached = _cache.get(root)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        rows = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    samples: list[Sample] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            sample = Sample(
                sample_id=str(row["sample_id"]),
                file=str(row["file"]),
                language_mix=str(row["language_mix"]),
                business_id=str(row["business_id"]),
                business_name=str(row.get("business_name") or row["business_id"]),
                duration_ms=int(row["duration_ms"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            SAMPLE_ID.fullmatch(sample.sample_id)
            and re.fullmatch(r"[A-Za-z0-9._-]{1,160}\.mp3", sample.file)
            and (folder / sample.file).is_file()
        ):
            samples.append(sample)
    result = tuple(samples)
    _cache[root] = (stamp, result)
    return result


def language_codes(language: str | None) -> frozenset[str]:
    if not language:
        return frozenset()
    parts = re.split(r"[\s,/+-]+", language.lower())
    return frozenset(_CODES.get(part, part) for part in parts if part)


def pick(
    samples: tuple[Sample, ...], *, language: str | None, business: str | None, seed: str
) -> Sample | None:
    """A recording in the lead's language, from its business when it has one.

    The same lead gets the same first choice; ``seed`` varies it per call.
    """
    if not samples:
        return None
    wanted = language_codes(language)
    pool = [sample for sample in samples if wanted & sample.languages] or list(samples)
    if business:
        name = business.strip().lower()
        own = [
            sample
            for sample in pool
            if sample.business_name.lower() == name or sample.business_id.lower() == name
        ]
        pool = own or pool
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return sorted(pool, key=lambda sample: sample.sample_id)[digest % len(pool)]


def audio_path(root: str | None, sample_id: str) -> Path | None:
    if not SAMPLE_ID.fullmatch(sample_id):
        return None
    for sample in catalogue(root):
        if sample.sample_id == sample_id:
            return Path(root or "") / sample.file
    return None
