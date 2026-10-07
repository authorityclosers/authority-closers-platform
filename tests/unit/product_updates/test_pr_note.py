"""The prescribed P3 grammar is shared by CI collection and note ingestion."""

import pytest

from ac_platform.product_updates.pr_note import UserNote, parse_user_note


def test_note_comments_crlf_and_following_section() -> None:
    result = parse_user_note(
        "## Summary\r\nInternal work\r\n## User-facing note\r\n"
        "<!-- Title: ignore this -->\r\nTitle:  Clearer fictional reports  \r\n"
        "- Read a fictional summary.\r\nFeature: reports.summary\r\n"
        "\r\n## Tests\r\nIgnored test details"
    )
    assert result == UserNote(
        "Clearer fictional reports", ["Read a fictional summary."], "reports.summary"
    )


@pytest.mark.parametrize("value", ["none", "NONE", "None"])
def test_none(value: str) -> None:
    assert parse_user_note(f"## User-facing note\n<!-- instructions -->\n{value}") == "none"


@pytest.mark.parametrize(
    "body,rule",
    [
        ("Title: Missing heading\n- Item", "section"),
        ("## User-facing note\n<!-- comment only -->", "empty"),
        ("## User-facing note\nTitle: " + "x" * 61 + "\n- Item", "title"),
        ("## User-facing note\nTitle: Missing bullets", "bullets"),
        ("## User-facing note\nTitle: Four\n" + "- Item\n" * 4, "bullets"),
        ("## User-facing note\nTitle: Long\n- " + "x" * 161, "bullets"),
        ("## User-facing note\nTitle: Empty\n- ", "allowed"),
        ("## User-facing note\nTitle: Key\n- Item\nFeature: BAD", "Feature"),
        ("## User-facing note\nTitle: <b>Markup</b>\n- Item", "HTML"),
        ("## User-facing note\nTitle: Link\n- https://example.test", "URLs"),
        ("## User-facing note\nTitle: Link\n- HTTP://example.test", "URLs"),
        ("## User-facing note\nTitle: First\nTitle: Second\n- Item", "title"),
        ("## User-facing note\nnone\n- Item", "allowed"),
        ("## User-facing note\nnone\n## User-facing note\nnone", "section"),
    ],
)
def test_invalid_note_names_the_broken_rule(body: str, rule: str) -> None:
    result = parse_user_note(body)
    assert isinstance(result, str) and result != "none" and rule in result


def test_maximum_text_and_feature_boundaries() -> None:
    title, item, feature = "x" * 60, "y" * 160, "z" * 64
    assert parse_user_note(
        f"## User-facing note\nTitle: {title}\n- {item}\n- Two\n- Three\nFeature: {feature}"
    ) == UserNote(title, [item, "Two", "Three"], feature)
