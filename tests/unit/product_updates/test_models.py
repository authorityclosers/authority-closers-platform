"""Portable item validation supplements PostgreSQL's JSON CHECK."""

import pytest

from ac_platform.product_updates.models import ProductUpdate


@pytest.mark.parametrize("items", [[], ["x"] * 5, ["x" * 201], [None], [1], [True], {}, None])
def test_invalid_item_shape_is_refused_by_the_model(items) -> None:
    with pytest.raises(ValueError, match="1–4 strings"):
        ProductUpdate(items=items)


@pytest.mark.parametrize("items", [["x" * 200], ["a", "b", "c", "d"]])
def test_item_boundaries_are_allowed(items) -> None:
    assert ProductUpdate(items=items).items == items
