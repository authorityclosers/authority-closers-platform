"""The one-pass request identifiers: v1 is pinned (sealed configurations depend on it), v2 is
its own recipe and marker."""

from ac_platform.one_pass import markers


def test_v1_identifiers_are_unchanged() -> None:
    assert markers.RECIPE == "one-pass-facts-v1"
    assert markers.PROMPT_REVISION == "one-pass-v1"
    assert markers.MARKER == "FACT_OUTPUT: one-pass-facts-v1."


def test_v2_is_its_own_recipe_and_marker() -> None:
    assert markers.RECIPE_V2 == "one-pass-facts-v2"
    assert markers.PROMPT_REVISION_V2 == "one-pass-v2"
    assert markers.MARKER_V2 == "FACT_OUTPUT: one-pass-facts-v2."
    assert not markers.MARKER_V2.startswith(markers.MARKER)
    assert frozenset({markers.RECIPE, markers.RECIPE_V2}) == markers.RECIPES
    assert frozenset({markers.PROMPT_REVISION, "one-pass-v2"}) == markers.PROMPT_REVISIONS
    assert dict(markers.PROMPT_REVISION_BY_RECIPE) == {
        markers.RECIPE: markers.PROMPT_REVISION,
        markers.RECIPE_V2: markers.PROMPT_REVISION_V2,
    }
    assert {value: key for key, value in markers.PROMPT_REVISION_BY_RECIPE.items()} == dict(
        markers.RECIPE_BY_PROMPT_REVISION
    )


def test_a_prompt_names_its_recipe_by_its_first_line() -> None:
    assert markers.recipe_of(markers.MARKER + "\n...") == markers.RECIPE
    assert markers.recipe_of(markers.MARKER_V2 + "\n...") == markers.RECIPE_V2
    for other in (markers.MARKER, "x\n" + markers.MARKER + "\n", "FACT_OUTPUT: other.\n", None, 7):
        assert markers.recipe_of(other) is None
        assert not markers.is_one_pass(other)
    assert markers.is_one_pass(markers.MARKER + "\n") and markers.is_one_pass(
        markers.MARKER_V2 + "\n"
    )
