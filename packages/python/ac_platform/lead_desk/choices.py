"""What a seller's languages, areas and products are picked from (owner bug #49, 27 Oct 2026).

The free-text boxes on a seller's lead rules were hard to fill and easy to misspell, so a
typed "Navi-Mumbai" never matched a lead's "Navi Mumbai". The sheet offers chips instead:
the values the organisation's own leads carry, each with how many leads carry it.

Every chip is read the way seller matching reads it (``allocation``), so a picked chip
always matches its own leads:

- areas and products: lower case, hyphens as spaces, single spaces (``allocation.key``);
  spellings with one key are one chip, shown in their most common spelling. Products are
  the lead's interest, which intake fills from the interest, interested_in, product_interest
  and course_interested answers (``capture``);
- languages: each part of a lead's language ("Hindi, English", "hi-mr"), as its code
  (``allocation.language_codes``), shown by its name.

``fit`` says how many of last month's leads a profile would take on its rules, with the
same check allocation runs. Pure: no database and no clock.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Final, Literal
from uuid import UUID

from pydantic import Field, field_validator

from ac_platform.lead_desk import allocation
from ac_platform.lead_desk.contracts import SCHEMA, Command, Model
from ac_platform.lead_desk.journey.templates import template

DAYS: Final = 90
FIT_DAYS: Final = 30
SHOWN: Final = 60
# A lead's (city, language, interest) and how many leads carry exactly that.
Row = tuple[str | None, str | None, str | None, int]


class Choice(Model):
    value: str  # shown on the chip, and saved as it is into the seller's list
    key: str  # what matching compares: de-duplicate and mark chosen chips by it
    leads: int


class More(Model):
    areas: int = 0
    languages: int = 0
    products: int = 0


class Industry(Model):
    id: str
    name: str


class TeamChoices(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    days: int
    leads: int
    areas: tuple[Choice, ...]
    languages: tuple[Choice, ...]
    products: tuple[Choice, ...]
    more: More
    industry: Industry | None
    # The industry profiles hold stages, no products, so this is empty for now.
    suggested_products: tuple[str, ...] = ()


class FitCommand(Command):
    languages: list[str] = Field(default_factory=list, max_length=50)
    areas: list[str] = Field(default_factory=list, max_length=50)
    products: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("languages", "areas", "products")
    @classmethod
    def _short(cls, values: list[str]) -> list[str]:
        if any(len(value) > 80 for value in values):
            raise ValueError("Keep each one under 80 characters.")
        return [value.strip() for value in values if value.strip()]


class FitBy(Model):
    language: int
    area: int
    product: int


class FitView(Model):
    days: int
    leads: int
    fits: int
    percent: int
    by: FitBy


def _spelling(value: str) -> str:
    return " ".join(value.split())


class _Tally:
    """Leads per key, and each key's spellings."""

    def __init__(self) -> None:
        self.leads: Counter[str] = Counter()
        self.spellings: defaultdict[str, Counter[str]] = defaultdict(Counter)

    def add(self, key: str, spelling: str, count: int) -> None:
        if key:
            self.leads[key] += count
            self.spellings[key][spelling] += count

    def chips(self, name: dict[str, str] | None = None) -> tuple[tuple[Choice, ...], int]:
        ranked = sorted(self.leads.items(), key=lambda item: (-item[1], item[0]))
        shown = tuple(
            Choice(
                value=(name or {}).get(key) or self.spellings[key].most_common(1)[0][0],
                key=key,
                leads=count,
            )
            for key, count in ranked[:SHOWN]
        )
        return shown, max(0, len(ranked) - SHOWN)


# Words between languages ("Hindi and English") are no language of their own.
_JOINING: Final = frozenset({"and", "or", "&"})


def _language_parts(value: str) -> list[tuple[str, str]]:
    """Each language a lead's value names, once: its code and how it was first written."""
    written = value.replace("-", " ").replace(",", " ").replace("/", " ").split()
    parts: dict[str, str] = {}
    for code, word in zip(allocation.language_codes(value), written, strict=True):
        if code not in _JOINING:
            parts.setdefault(code, word.title() if word.islower() else word)
    return list(parts.items())


def view(rows: Iterable[Row], *, days: int, industry: str | None) -> TeamChoices:
    areas, languages, products = _Tally(), _Tally(), _Tally()
    total = 0
    for city, language, interest, count in rows:
        total += count
        if city and city.strip():
            areas.add(allocation.key(city), _spelling(city), count)
        if interest and interest.strip():
            products.add(allocation.key(interest), _spelling(interest), count)
        if language and language.strip():
            for code, spelling in _language_parts(language):
                languages.add(code, spelling, count)
    shown_areas, more_areas = areas.chips()
    shown_languages, more_languages = languages.chips(allocation.LANGUAGE_NAMES)
    shown_products, more_products = products.chips()
    profile = template(industry) if industry else None
    return TeamChoices(
        days=days,
        leads=total,
        areas=shown_areas,
        languages=shown_languages,
        products=shown_products,
        more=More(areas=more_areas, languages=more_languages, products=more_products),
        industry=Industry(id=profile.id, name=profile.name) if profile else None,
    )


def fit(rows: Iterable[Row], command: FitCommand) -> FitView:
    """Last month's leads this profile would take on its rules: language, area and product
    each fit or don't apply, the check allocation runs (``allocation.checks``)."""
    seller = allocation.RepState(
        person_id=UUID(int=0),
        name="",
        available=True,
        max_open=None,
        open_leads=0,
        languages=tuple(command.languages),
        areas=tuple(command.areas),
        interests=tuple(command.products),
    )
    total = fits = language_ok = area_ok = product_ok = 0
    for city, language, interest, count in rows:
        checks = allocation.checks(
            allocation.LeadFacts(language=language, city=city, interest=interest), seller
        )
        total += count
        language_ok += count if checks[0] is not False else 0
        area_ok += count if checks[1] is not False else 0
        product_ok += count if checks[2] is not False else 0
        fits += count if all(check is not False for check in checks) else 0
    return FitView(
        days=FIT_DAYS,
        leads=total,
        fits=fits,
        percent=round(100 * fits / total) if total else 0,
        by=FitBy(language=language_ok, area=area_ok, product=product_ok),
    )
