"""Where a new lead goes when an organisation runs several pipelines."""

import pytest

from ac_platform.lead_desk.journey import pipelines
from ac_platform.lead_desk.journey.model import JourneyError
from ac_platform.lead_desk.journey.pipelines import MAIN, Pipeline

MAIN_ONLY = (Pipeline(MAIN, "Leads", 0, ()),)
TWO = (
    Pipeline(MAIN, "Enrolment", 0, ()),
    Pipeline("partner_outreach", "Partner outreach", 1, ("csv",)),
)


def test_main_takes_every_lead_no_other_pipeline_takes() -> None:
    assert pipelines.route(MAIN_ONLY, "csv") == MAIN
    assert pipelines.route(TWO, "csv") == "partner_outreach"
    for source in ("meta", "webhook", "sheet", "manual", "referral", "synthetic"):
        assert pipelines.route(TWO, source) == MAIN


def test_main_never_takes_a_source_by_name() -> None:
    odd = (Pipeline(MAIN, "Leads", 0, ("csv",)), Pipeline("b", "B", 1, ("csv",)))
    assert pipelines.route(odd, "csv") == "b"


def test_unknown_pipelines_and_sources_are_refused_in_plain_words() -> None:
    assert pipelines.find(TWO, "partner_outreach").name == "Partner outreach"
    with pytest.raises(JourneyError, match="isn't there"):
        pipelines.find(TWO, "nope")
    assert pipelines.clean_sources(["csv", "csv", "meta"]) == ("csv", "meta")
    with pytest.raises(JourneyError, match="from the list"):
        pipelines.clean_sources(["fax"])
    assert pipelines.clean_name("  Partner   outreach ") == "Partner outreach"
    with pytest.raises(JourneyError):
        pipelines.clean_name("   ")
