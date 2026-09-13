"""Versioned release notes compiled into the artifact that ships them."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

RELEASE_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_RELEASE_ID = re.compile(RELEASE_ID_PATTERN)
_ENCODED_SEPARATOR = re.compile(r"%(?:2f|5c)", re.IGNORECASE)


def validate_target_href(value: str) -> str:
    if not 1 <= len(value) <= 500:
        raise ValueError("release targets must contain 1–500 characters")
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("release targets must be same-origin application paths")
    if "\\" in value or _ENCODED_SEPARATOR.search(value):
        raise ValueError("release targets must not contain encoded or backslash separators")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise ValueError("release targets must not contain control characters")
    return value


@dataclass(frozen=True, slots=True)
class AppRelease:
    """One immutable, factual note included in this application artifact."""

    id: str
    title: str
    message: str
    version: str
    highlights: tuple[str, ...]
    target_href: str
    created_at: datetime
    state: Literal["shipped", "draft"] = "shipped"

    def __post_init__(self) -> None:
        if _RELEASE_ID.fullmatch(self.id) is None or len(self.id) > 128:
            raise ValueError("release id must be a bounded stable slug")
        for name, value, limit in (
            ("title", self.title, 200),
            ("message", self.message, 1000),
            ("version", self.version, 80),
        ):
            if not value.strip() or len(value) > limit:
                raise ValueError(f"release {name} must be non-empty and at most {limit} characters")
        if not 1 <= len(self.highlights) <= 8 or any(
            not value.strip() or len(value) > 300 for value in self.highlights
        ):
            raise ValueError("release highlights require 1–8 non-empty values up to 300 characters")
        validate_target_href(self.target_href)
        if self.created_at.tzinfo is None:
            raise ValueError("release timestamps must be timezone-aware")
        if self.state not in {"shipped", "draft"}:
            raise ValueError("release state must be shipped or draft")


@dataclass(frozen=True, slots=True)
class AppReleaseCatalogue:
    """An immutable catalogue whose version changes with its shipped content."""

    version: str
    releases: tuple[AppRelease, ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("catalogue version is required")
        if len(self.releases) > 50:
            raise ValueError("an artifact catalogue may contain at most 50 release notes")
        ids = [release.id for release in self.releases]
        if len(ids) != len(set(ids)):
            raise ValueError("release ids must be unique")

    def available(self, now: datetime) -> tuple[AppRelease, ...]:
        if now.tzinfo is None:
            raise ValueError("catalogue reads require a timezone-aware clock")
        return tuple(
            sorted(
                (
                    release
                    for release in self.releases
                    if release.state == "shipped" and release.created_at <= now
                ),
                key=lambda release: (release.created_at, release.id),
                reverse=True,
            )
        )

    def resolve_available(self, release_id: str, now: datetime) -> AppRelease | None:
        return next(
            (release for release in self.available(now) if release.id == release_id),
            None,
        )


CURRENT_ARTIFACT_RELEASES = AppReleaseCatalogue(
    version="app-updates-v0-2-alpha-catalogue-2",
    releases=(
        AppRelease(
            id="app-updates-v0-2-read-recovery",
            title="A quieter notification bell",
            message=(
                "Read an update once and carry on. "
                "Switching tabs no longer interrupts saving it as read."
            ),
            version="v0.2 Alpha",
            highlights=(
                "Marking an update as read can finish when you return to the app.",
                "Your notification list refreshes after the save finishes.",
                "Saved read status follows your academy account when you sign in again.",
            ),
            target_href="/notifications",
            created_at=datetime(2026, 9, 13, 17, 30, tzinfo=UTC),
        ),
        AppRelease(
            id="app-updates-v0-2-alpha",
            title="A home for app updates",
            message="See what’s new and jump straight into the latest improvements.",
            version="v0.2 Alpha",
            highlights=(
                "Version notes now have a dedicated home.",
                "Each update can link to the feature it describes.",
                "Read status is saved to your learner account.",
            ),
            target_href="/notifications",
            created_at=datetime(2026, 9, 10, tzinfo=UTC),
        ),
    ),
)


__all__ = [
    "AppRelease",
    "AppReleaseCatalogue",
    "CURRENT_ARTIFACT_RELEASES",
    "RELEASE_ID_PATTERN",
    "validate_target_href",
]
