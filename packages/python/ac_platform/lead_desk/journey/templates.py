"""Ready-made lead stages per kind of business, and what each stage means.

Every business tracks its leads its own way. A business picks the profile closest to
it, gets working stages at once, and changes them as it likes. Profiles are named by
industry, never after a customer.

Each stage has three parts:

- its **label**, the business's own words ("Site visit booked");
- its **kind**, what the desk does with it (one of the six desk stages: a new lead, a
  lead that could not be reached, an open lead that needs a follow-up, a hot lead, won
  or lost). The desk's follow-ups, queues and reports run on the kind, so a business's
  own stages never break them;
- its **milestone**, what it means for selling ("a meeting or visit is booked"). The
  ad-platform engine matches milestones to each platform's own events, so nobody has
  to match them by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

Kind = Literal["new", "not_connected", "follow_up", "interested", "won", "lost"]
Milestone = Literal[
    "lead",
    "unreachable",
    "contacted",
    "qualified",
    "appointment_booked",
    "appointment_done",
    "proposal",
    "application",
    "negotiation",
    "won",
    "lost",
    "other",
]

KINDS: Final[tuple[Kind, ...]] = (
    "new",
    "not_connected",
    "follow_up",
    "interested",
    "won",
    "lost",
)
MILESTONES: Final[tuple[Milestone, ...]] = (
    "lead",
    "unreachable",
    "contacted",
    "qualified",
    "appointment_booked",
    "appointment_done",
    "proposal",
    "application",
    "negotiation",
    "won",
    "lost",
    "other",
)
# The order a lead moves through, for the milestones on the way to a sale.
FUNNEL_ORDER: Final[dict[str, int]] = {
    "lead": 0,
    "contacted": 1,
    "qualified": 2,
    "appointment_booked": 3,
    "appointment_done": 4,
    "proposal": 5,
    "application": 6,
    "negotiation": 7,
    "won": 8,
}

# Plain words, as the page shows them.
KIND_WORDS: Final[dict[str, str]] = {
    "new": "New lead",
    "not_connected": "Couldn't reach",
    "follow_up": "In talks",
    "interested": "Hot",
    "won": "Won",
    "lost": "Lost",
}
MILESTONE_WORDS: Final[dict[str, str]] = {
    "lead": "A new enquiry",
    "unreachable": "You couldn't reach them",
    "contacted": "You spoke to them",
    "qualified": "A good fit and keen",
    "appointment_booked": "A meeting or visit is booked",
    "appointment_done": "The meeting or visit happened",
    "proposal": "They have your quote or proposal",
    "application": "They sent forms or documents",
    "negotiation": "Agreeing the final terms",
    "won": "They bought",
    "lost": "They won't buy",
    "other": "Something else",
}
# The desk kind a milestone usually means.
MILESTONE_KIND: Final[dict[str, Kind]] = {
    "lead": "new",
    "unreachable": "not_connected",
    "contacted": "follow_up",
    "qualified": "interested",
    "appointment_booked": "interested",
    "appointment_done": "interested",
    "proposal": "interested",
    "application": "interested",
    "negotiation": "interested",
    "won": "won",
    "lost": "lost",
    "other": "follow_up",
}


@dataclass(frozen=True, slots=True)
class TemplateStage:
    key: str
    label: str
    milestone: Milestone

    @property
    def kind(self) -> Kind:
        return MILESTONE_KIND[self.milestone]


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    name: str
    blurb: str
    icon: str
    stages: tuple[TemplateStage, ...]


def _t(key: str, label: str, milestone: Milestone) -> TemplateStage:
    return TemplateStage(key, label, milestone)


_NEW = _t("new", "New", "lead")
_UNREACHED = _t("not_connected", "Couldn't reach", "unreachable")
_LOST = _t("lost", "Lost", "lost")

TEMPLATES: Final[tuple[Template, ...]] = (
    Template(
        "simple",
        "Any business",
        "Six stages that suit most teams.",
        "spark",
        (
            _NEW,
            _UNREACHED,
            _t("follow_up", "Follow-up", "contacted"),
            _t("interested", "Interested", "qualified"),
            _t("won", "Won", "won"),
            _LOST,
        ),
    ),
    Template(
        "real_estate",
        "Real estate",
        "From enquiry to site visit to booking.",
        "building",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("site_visit_booked", "Site visit booked", "appointment_booked"),
            _t("site_visit_done", "Site visit done", "appointment_done"),
            _t("negotiation", "Negotiation", "negotiation"),
            _t("booked", "Booked", "won"),
            _LOST,
        ),
    ),
    Template(
        "education",
        "Coaching & education",
        "Counselling, demo class, enrolment.",
        "cap",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("counselled", "Counselled", "contacted"),
            _t("demo_booked", "Demo class booked", "appointment_booked"),
            _t("demo_attended", "Demo attended", "appointment_done"),
            _t("application", "Application started", "application"),
            _t("enrolled", "Enrolled", "won"),
            _LOST,
        ),
    ),
    Template(
        "insurance",
        "Insurance",
        "Needs, quote, documents, policy.",
        "shield",
        (
            _t("new", "New lead", "lead"),
            _UNREACHED,
            _t("needs_understood", "Needs understood", "contacted"),
            _t("quote_shared", "Quote shared", "proposal"),
            _t("documents", "Documents collected", "application"),
            _t("policy_issued", "Policy issued", "won"),
            _LOST,
        ),
    ),
    Template(
        "clinic",
        "Clinics & healthcare",
        "Enquiry, appointment, visit, treatment.",
        "heart",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("spoke", "Spoke to patient", "contacted"),
            _t("appointment_booked", "Appointment booked", "appointment_booked"),
            _t("visited", "Visited", "appointment_done"),
            _t("treatment_started", "Treatment started", "won"),
            _LOST,
        ),
    ),
    Template(
        "b2b_services",
        "B2B services & agencies",
        "Discovery, meeting, proposal, deal.",
        "briefcase",
        (
            _t("new", "New lead", "lead"),
            _UNREACHED,
            _t("discovery_call", "Discovery call", "contacted"),
            _t("qualified", "Qualified", "qualified"),
            _t("meeting_booked", "Meeting booked", "appointment_booked"),
            _t("proposal_sent", "Proposal sent", "proposal"),
            _t("negotiation", "Negotiation", "negotiation"),
            _t("won", "Won", "won"),
            _LOST,
        ),
    ),
    Template(
        "automotive",
        "Cars & bikes",
        "Test drive, quote, booking.",
        "car",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("test_drive_booked", "Test drive booked", "appointment_booked"),
            _t("test_drive_done", "Test drive done", "appointment_done"),
            _t("quote_shared", "Quote shared", "proposal"),
            _t("booked", "Booked", "won"),
            _LOST,
        ),
    ),
    Template(
        "loans",
        "Loans & finance",
        "Eligibility, documents, disbursal.",
        "bank",
        (
            _t("new", "New lead", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("eligible", "Eligible", "qualified"),
            _t("documents", "Documents collected", "application"),
            _t("disbursed", "Disbursed", "won"),
            _LOST,
        ),
    ),
    Template(
        "home_services",
        "Home services & solar",
        "Survey, quote, order.",
        "home",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("survey_booked", "Site survey booked", "appointment_booked"),
            _t("survey_done", "Survey done", "appointment_done"),
            _t("quote_sent", "Quote sent", "proposal"),
            _t("order_confirmed", "Order confirmed", "won"),
            _LOST,
        ),
    ),
    Template(
        "software",
        "Software & SaaS",
        "Demo, trial, proposal, signed.",
        "screen",
        (
            _t("new", "New lead", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("demo_booked", "Demo booked", "appointment_booked"),
            _t("demo_done", "Demo done", "appointment_done"),
            _t("proposal_sent", "Proposal sent", "proposal"),
            _t("won", "Signed", "won"),
            _LOST,
        ),
    ),
    Template(
        "travel",
        "Travel & holidays",
        "Plan, itinerary, booking.",
        "plane",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("itinerary_sent", "Itinerary sent", "proposal"),
            _t("negotiation", "Finalising", "negotiation"),
            _t("booked", "Booked", "won"),
            _LOST,
        ),
    ),
    Template(
        "retail",
        "Shops & showrooms",
        "Enquiry, store visit, purchase.",
        "bag",
        (
            _t("new", "New enquiry", "lead"),
            _UNREACHED,
            _t("contacted", "Contacted", "contacted"),
            _t("visit_booked", "Store visit booked", "appointment_booked"),
            _t("visited", "Visited store", "appointment_done"),
            _t("bought", "Bought", "won"),
            _LOST,
        ),
    ),
)
TEMPLATE_IDS: Final[frozenset[str]] = frozenset(template.id for template in TEMPLATES)
DEFAULT_TEMPLATE: Final[str] = "simple"


def template(template_id: str) -> Template | None:
    return next((item for item in TEMPLATES if item.id == template_id), None)


# ----- what a stage the business names itself probably means -------------------------

_BOOKED = r"(book|schedul|fix|set up|arrang|plann|confirm)"
_MEET = (
    r"(visit|demo|meeting|test ?drive|appointment|consult|trial class|trial|walk ?in|"
    r"survey|inspection|tour|viewing|showing|call back booked)"
)
_RULES: Final[tuple[tuple[Milestone, re.Pattern[str]], ...]] = (
    (
        "lost",
        re.compile(r"\b(lost|not interested|dropped|reject|junk|dead|spam|closed lost|cold)\b"),
    ),
    (
        "unreachable",
        re.compile(
            r"(not reach|unreach|no answer|couldn'?t reach|not connected|ringing|switched off)"
        ),
    ),
    (
        "appointment_done",
        re.compile(rf"{_MEET}.*\b(done|complet|attend|happen|held|over)\w*|\b(visited|attended)\b"),
    ),
    ("appointment_booked", re.compile(rf"{_MEET}.*{_BOOKED}|{_BOOKED}\w*.*{_MEET}|{_MEET}")),
    ("proposal", re.compile(r"(quot|proposal|estimate|pricing|price sent|offer|itinerar|costing)")),
    (
        "application",
        re.compile(r"(applica|document|docs\b|kyc|paperwork|form submit|applied|login)"),
    ),
    ("negotiation", re.compile(r"(negotiat|final terms|finalis|finaliz|token|discussion)")),
    (
        "won",
        re.compile(
            r"\b(won|win|customer|enrol|admit|purchas|paid|payment|sold|convert|issued|disburs|"
            r"order|signed|booked|booking|closed|deal done|joined|started)\w*"
        ),
    ),
    ("qualified", re.compile(r"(qualif|interest|hot|eligib|shortlist|warm|keen|potential)")),
    (
        "contacted",
        re.compile(r"(contact|connect|spoke|talk|call|counsel|follow|discover|intro|reach)"),
    ),
    ("lead", re.compile(r"\b(new|enquir|inquir|lead|fresh|incoming)\w*")),
)


def guess_milestone(label: str) -> Milestone:
    """What a stage the business names itself most likely means, from its words.

    Only a first suggestion: the page shows it in plain words and the manager can
    change it. Words for a meeting win over "booked", so "Site visit booked" is a
    booked meeting, while "Booked" alone is a sale.
    """
    words = " ".join(label.lower().split())
    for milestone, pattern in _RULES:
        if pattern.search(words):
            return milestone
    return "other"


def slug(label: str) -> str:
    """A stage key from its label: lower case, letters, digits and underscores."""
    value = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    value = re.sub(r"_+", "_", value)
    if not value or not value[0].isalpha():
        value = f"stage_{value}" if value else "stage"
    return value[:40].rstrip("_")
