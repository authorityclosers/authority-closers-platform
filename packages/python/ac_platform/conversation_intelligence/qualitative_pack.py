"""Versioned single-call reasoning instructions, not scoring or admission policy.

The bundled pack is a reviewed candidate. Loading it does not activate it: accepted
plans must explicitly bind its identity and hash. Never fetch live Drive content
while preparing a report or silently change an already accepted prompt revision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ac_platform.conversation_intelligence.checkpoints import content_hash

ReportLanguage = Literal["en", "hi-Deva+en", "mr-Deva+en"]
QUALITATIVE_PACK_ID = "sx-qualitative-20260922-r1"
_PACK_PATH = Path(__file__).with_name("profiles") / "sales_xray_qualitative_20260922.json"


class _Immutable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PackSource(_Immutable):
    id: str = Field(min_length=1, max_length=64)
    drive_id: str = Field(pattern=r"^[A-Za-z0-9_-]{10,128}$")
    captured_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuleSource(_Immutable):
    source_id: str = Field(min_length=1, max_length=64)
    sections: tuple[str, ...] = Field(min_length=1, max_length=8)


class QualitativeRule(_Immutable):
    id: str = Field(pattern=r"^SXQ(?:0[1-9]|10)$")
    instruction: str = Field(min_length=1, max_length=800)
    sources: tuple[RuleSource, ...] = Field(min_length=1, max_length=4)


class QualitativePack(_Immutable):
    schema_id: Literal["ac.sales-xray.qualitative-pack/1"]
    id: Literal["sx-qualitative-20260922-r1"]
    scope: Literal["single_call"]
    numeric_evaluation: Literal[False]
    sources: tuple[PackSource, ...] = Field(min_length=1, max_length=8)
    rules: tuple[QualitativeRule, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_references(self) -> QualitativePack:
        source_ids = [source.id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("qualitative_pack_duplicate_source")
        if tuple(rule.id for rule in self.rules) != tuple(f"SXQ{n:02}" for n in range(1, 11)):
            raise ValueError("qualitative_pack_rule_order_invalid")
        for rule in self.rules:
            for source in rule.sources:
                if source.source_id not in source_ids or any(
                    not section.strip() or len(section) > 160 for section in source.sections
                ):
                    raise ValueError("qualitative_pack_source_invalid")
        return self

    @property
    def sha256(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def compile(self) -> str:
        return (
            f"QUALITATIVE_PACK: {self.id}; sha256={self.sha256}; scope=single_call. "
            "These are reasoning rules, not admission, entitlement or numeric scoring rules.\n"
            + "\n".join(f"{rule.id}: {rule.instruction}" for rule in self.rules)
        )


def load_qualitative_pack(pack_id: str = QUALITATIVE_PACK_ID) -> QualitativePack:
    if pack_id != QUALITATIVE_PACK_ID:
        raise ValueError("qualitative_pack_unknown")
    return QualitativePack.model_validate_json(_PACK_PATH.read_bytes())


def report_language_instruction(language: ReportLanguage) -> str:
    prose = {
        "en": "Write generated report prose in clear everyday English.",
        "hi-Deva+en": (
            "Write generated report prose in natural Hindi using Devanagari, with familiar "
            "English sales terms in English script. Use conversational code-switching; do not "
            "force literal translations of ordinary English sales vocabulary."
        ),
        "mr-Deva+en": (
            "Write generated report prose in natural Marathi using Devanagari, with familiar "
            "English sales terms in English script. Use conversational code-switching; do not "
            "replace Marathi with Hindi or force literal translations of English sales vocabulary."
        ),
    }
    if language not in prose:
        raise ValueError("report_language_invalid")
    return (
        f"REPORT_LANGUAGE: {language}. {prose[language]} "
        "Keep JSON keys, identifiers, enums and provenance unchanged. Never translate, "
        "transliterate or rewrite source evidence. Preserve original quotations including "
        "Roman script, names, negation, amounts, dates and commitments. Generated suggestions "
        "must be visibly suggestions, never presented as source quotations."
    )


def qualitative_pack_manifest(pack: QualitativePack) -> dict[str, object]:
    """A fresh JSON-safe copy for immutable plan/report provenance."""

    return {
        "id": pack.id,
        "sha256": pack.sha256,
        "scope": pack.scope,
        "rule_ids": [rule.id for rule in pack.rules],
        "sources": json.loads(pack.model_dump_json())["sources"],
    }
