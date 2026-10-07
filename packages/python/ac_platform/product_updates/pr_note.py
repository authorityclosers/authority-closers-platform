"""The shared, dependency-free parser for the PR's user-facing note section."""

from __future__ import annotations

import re
from dataclasses import dataclass

FEATURE_KEY = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


@dataclass(frozen=True)
class UserNote:
    title: str
    items: list[str]
    feature_key: str | None = None


def parse_user_note(body: str) -> UserNote | str:
    """Return a note, ``none``, or a diagnostic naming the broken format rule."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    headings = list(re.finditer(r"^## User-facing note\s*$", body, flags=re.MULTILINE))
    if len(headings) != 1:
        return "Exactly one User-facing note section is required"
    section = re.split(r"^#{1,2} ", body[headings[0].end() :], maxsplit=1, flags=re.MULTILINE)[0]
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if lines == []:
        return "User-facing note section is empty"
    if len(lines) == 1 and lines[0].lower() == "none":
        return "none"
    titles, items, features = [], [], []
    for line in lines:
        if line.startswith("Title:"):
            titles.append(line.removeprefix("Title:").strip())
        elif line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("Feature:"):
            features.append(line.removeprefix("Feature:").strip())
        else:
            return "Only Title:, - bullets, and an optional Feature: line are allowed"
    if len(titles) != 1 or not 1 <= len(titles[0]) <= 60:
        return "Exactly one title of 1–60 characters is required"
    if not 1 <= len(items) <= 3 or any(not 1 <= len(item) <= 160 for item in items):
        return "1–3 bullets of 1–160 characters each are required"
    if len(features) > 1 or (features and not FEATURE_KEY.fullmatch(features[0])):
        return "Feature must be one key matching [a-z0-9][a-z0-9_.-]{0,63}"
    if any(re.search(r"[<>]|https?://", value, re.IGNORECASE) for value in titles + items):
        return "HTML and URLs are refused in the title and bullets"
    return UserNote(titles[0], items, features[0] if features else None)
