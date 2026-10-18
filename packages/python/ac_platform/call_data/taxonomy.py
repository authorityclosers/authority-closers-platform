"""The call data taxonomy: every kind of thing a call can establish (owner, 19 Oct 2026).

One code-defined registry, versioned as a whole. A new type, or a changed rule,
bumps ``TAXONOMY_VERSION``; stored objects keep the version they were made
under, so older rows always read. Industry packs (later) add types under their
own ``pack.<industry>.`` prefix without touching these.

Phone numbers and other contact details are deliberately absent (ADR 0056 §5):
no pipeline extracts them from a conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

TAXONOMY_VERSION = "call-taxonomy/1"

CATEGORIES = MappingProxyType(
    {
        "people": "People",
        "company": "Company",
        "need": "Needs and goals",
        "friction": "Objections and questions",
        "decision": "Decision",
        "money": "Money",
        "market": "Alternatives",
        "offer": "Products discussed",
        "commitment": "Commitments",
        "signal": "AI read",
        "outcome": "Outcome",
        "conversation": "Conversation",
    }
)

# Value kinds. Each has one JSON shape, checked by ``values.validate_value``.
VALUE_KINDS = frozenset(
    {
        "text",  # {"text"}
        "numeric",  # the prospect fact contract's NumericFactValue fields
        "when",  # {"text", "date"?, "time"?, "purpose"?}
        "enum",  # {"enum"}
        "person",  # {"name"?, "role"?, "relation"?}
        "commitment",  # {"text", "due"?}
        "objection",  # {"text", "kind", "resolved"}
        "question",  # {"text", "answered"}
        "ratio",  # {"parts": {speaker: share}} measured, never from a model
    }
)

# A key's first part names its family; each family belongs to one category.
PREFIX_CATEGORY = MappingProxyType(
    {
        "person": "people",
        **{name: name for name in CATEGORIES if name != "people"},
    }
)

OBJECTION_KINDS = ("price", "timing", "authority", "need", "trust", "competition", "other")


@dataclass(frozen=True, slots=True)
class AutoFill:
    """When the fast pipeline may write a lead field without asking."""

    min_confidence: float = 0.85
    min_mentions: int = 2
    # A plainly stated simple fact ("I'm Amit, from XYZ Digital") needs one mention.
    simple: bool = False


NEVER = None


@dataclass(frozen=True, slots=True)
class ObjectType:
    key: str
    category: str
    label: str
    kind: str
    many: bool
    priority: int  # lower asks first in the one-at-a-time confirmation
    hint: str  # what the extractor looks for (plain English, goes into the prompt)
    fast: bool = True  # the fast pipeline extracts it; the deep one extracts every type
    lead_field: str | None = None  # Lead Desk column it can fill
    prospect_field: str | None = None  # prospect_fields.FIELD_REGISTRY key it maps to
    auto_fill: AutoFill | None = NEVER
    ask: bool = True  # worth a confirmation question when not auto-filled
    enum_values: tuple[str, ...] = ()
    ai_read: bool = False  # an AI judgement, always labelled as the AI's read

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES or self.kind not in VALUE_KINDS:
            raise ValueError(f"bad taxonomy entry {self.key}")
        family = self.key.split(".", 1)[0]
        if family != "pack" and PREFIX_CATEGORY.get(family) != self.category:
            raise ValueError(f"key {self.key} outside category {self.category}")
        if (self.kind == "enum") != bool(self.enum_values):
            raise ValueError(f"enum values for {self.key}")


_SIMPLE = AutoFill(min_confidence=0.85, min_mentions=1, simple=True)

_TYPES: tuple[ObjectType, ...] = (
    # People
    ObjectType(
        "person.name",
        "people",
        "Name",
        "text",
        False,
        10,
        "The prospect's own name as they or the salesperson say it.",
        lead_field="name",
        prospect_field="name",
        auto_fill=_SIMPLE,
    ),
    ObjectType(
        "person.role",
        "people",
        "Role",
        "text",
        False,
        20,
        "The prospect's job title or role in their business (founder, owner, manager).",
        prospect_field="role",
        auto_fill=_SIMPLE,
    ),
    ObjectType(
        "person.other_party",
        "people",
        "Other people involved",
        "person",
        True,
        120,
        "Other people the prospect mentions who matter to the decision or the business "
        "(partner, spouse, boss, team lead), with their relation.",
    ),
    ObjectType(
        "person.personal_context",
        "people",
        "Personal context",
        "text",
        True,
        130,
        "Personal details that help the next conversation: wants more family time, "
        "travelling next week, health, a shared connection.",
    ),
    # Company
    ObjectType(
        "company.name",
        "company",
        "Company",
        "text",
        False,
        30,
        "The name of the prospect's business.",
        lead_field="company",
        prospect_field="business",
        auto_fill=_SIMPLE,
    ),
    ObjectType(
        "company.industry",
        "company",
        "Industry",
        "text",
        False,
        60,
        "What the business does (digital marketing agency, real estate brokerage, coaching).",
        prospect_field="industry",
        auto_fill=AutoFill(),
    ),
    ObjectType(
        "company.team_size",
        "company",
        "Team size",
        "numeric",
        False,
        70,
        "How many people work in the business or the sales team (unit: people).",
        prospect_field="team_size",
        auto_fill=AutoFill(),
    ),
    ObjectType(
        "company.revenue",
        "company",
        "Revenue",
        "numeric",
        False,
        80,
        "The business's revenue or turnover as stated, with currency and period.",
        prospect_field="turnover",
    ),
    ObjectType(
        "company.location",
        "company",
        "City",
        "text",
        False,
        90,
        "The city or area the prospect or business is in.",
        lead_field="city",
        prospect_field="city",
        auto_fill=_SIMPLE,
    ),
    # Needs
    ObjectType(
        "need.primary_pain",
        "need",
        "Biggest problem",
        "text",
        False,
        40,
        "The single biggest problem the prospect wants solved, in their terms.",
        prospect_field="main_pain",
    ),
    ObjectType(
        "need.pain",
        "need",
        "Other problems",
        "text",
        True,
        140,
        "Other problems or frustrations the prospect mentions.",
    ),
    ObjectType(
        "need.goal",
        "need",
        "What they want",
        "text",
        True,
        50,
        "What the prospect wants to achieve, with numbers and dates if said "
        "(grow from 4-5 lakh to 10 lakh a month).",
    ),
    # Friction
    ObjectType(
        "friction.blocker",
        "friction",
        "What's stopping them",
        "text",
        False,
        45,
        "The main thing stopping the prospect from going ahead now.",
    ),
    ObjectType(
        "friction.objection",
        "friction",
        "Objection",
        "objection",
        True,
        110,
        "Each objection or concern the prospect raises, its kind, and whether the "
        "salesperson resolved it in the call.",
    ),
    ObjectType(
        "friction.question",
        "friction",
        "Prospect's question",
        "question",
        True,
        150,
        "Questions the prospect asks, and whether they were answered.",
        ask=False,
    ),
    # Decision
    ObjectType(
        "decision.maker",
        "decision",
        "Decision maker",
        "person",
        False,
        55,
        "Who makes the buying decision (the prospect, a partner, a boss).",
        prospect_field="decision_maker",
    ),
    ObjectType(
        "decision.approver",
        "decision",
        "Needs approval from",
        "person",
        True,
        56,
        "Anyone whose approval the prospect needs before buying.",
    ),
    ObjectType(
        "decision.status",
        "decision",
        "Decision",
        "enum",
        False,
        57,
        "Where the decision stands at the end of the call.",
        enum_values=("decided_yes", "decided_no", "pending", "not_discussed"),
    ),
    ObjectType(
        "decision.timeline",
        "decision",
        "Timeline",
        "text",
        False,
        65,
        "When the prospect wants results or plans to decide (within 3 months, after Diwali).",
        prospect_field="timeline",
    ),
    # Money
    ObjectType(
        "money.budget",
        "money",
        "Budget",
        "numeric",
        False,
        75,
        "The budget the prospect states for this purchase, with currency.",
        prospect_field="budget",
    ),
    ObjectType(
        "money.price_quoted",
        "money",
        "Price quoted",
        "numeric",
        True,
        76,
        "Prices the salesperson quotes, with currency and what it covers.",
        ask=False,
    ),
    ObjectType(
        "money.investment_discussed",
        "money",
        "Investment discussed",
        "numeric",
        False,
        77,
        "The investment amount the prospect is considering.",
    ),
    # Market
    ObjectType(
        "market.alternative",
        "market",
        "Alternative considered",
        "text",
        True,
        100,
        "Other options the prospect is weighing (hiring in-house, doing nothing, another course).",
    ),
    ObjectType(
        "market.competitor",
        "market",
        "Competitor",
        "text",
        True,
        101,
        "Named competing companies, products or people.",
    ),
    ObjectType(
        "market.past_attempt",
        "market",
        "Tried before",
        "text",
        True,
        102,
        "What the prospect already tried for this problem and how it went.",
    ),
    # Offer
    ObjectType(
        "offer.product_mentioned",
        "offer",
        "Product discussed",
        "text",
        True,
        160,
        "The products, programmes or services discussed in the call.",
        lead_field="interest",
        ask=False,
    ),
    # Commitments
    ObjectType(
        "commitment.follow_up",
        "commitment",
        "Next follow-up",
        "when",
        False,
        5,
        "The agreed next call or meeting: when, and what it is for.",
        prospect_field="next_step",
    ),
    ObjectType(
        "commitment.seller_promise",
        "commitment",
        "We promised",
        "commitment",
        True,
        15,
        "Anything the salesperson promised to do or send, and by when.",
    ),
    ObjectType(
        "commitment.prospect_promise",
        "commitment",
        "They promised",
        "commitment",
        True,
        16,
        "Anything the prospect promised to do, and by when.",
    ),
    ObjectType(
        "commitment.next_step",
        "commitment",
        "Next step",
        "text",
        False,
        6,
        "The single next step both sides agreed, in one line.",
        ask=False,
    ),
    # AI reads
    ObjectType(
        "signal.urgency",
        "signal",
        "Urgency (AI read)",
        "enum",
        False,
        170,
        "How urgent the prospect's need sounds.",
        enum_values=("low", "medium", "high"),
        ai_read=True,
        ask=False,
    ),
    ObjectType(
        "signal.interest",
        "signal",
        "Interest (AI read)",
        "enum",
        False,
        171,
        "How interested the prospect sounds in buying.",
        enum_values=("low", "medium", "high"),
        ai_read=True,
        ask=False,
    ),
    # Outcome
    ObjectType(
        "outcome.call_outcome",
        "outcome",
        "Call outcome",
        "enum",
        False,
        180,
        "How the call ended.",
        enum_values=(
            "deal_closed",
            "follow_up_agreed",
            "meeting_scheduled",
            "no_sale",
            "not_a_fit",
            "callback_requested",
            "no_conversation",
        ),
        ask=False,
    ),
    # Conversation (deep pipeline only)
    ObjectType(
        "conversation.language",
        "conversation",
        "Languages spoken",
        "enum",
        True,
        190,
        "The languages spoken in the call.",
        enum_values=("en", "hi", "mr", "gu", "other"),
        fast=False,
        ask=False,
    ),
    ObjectType(
        "conversation.talk_ratio",
        "conversation",
        "Talk ratio",
        "ratio",
        False,
        191,
        "Measured share of talking time per speaker (computed, never from a model).",
        fast=False,
        ask=False,
    ),
)

TYPES = MappingProxyType({item.key: item for item in _TYPES})
FAST_TYPES = tuple(item for item in _TYPES if item.fast)
DEEP_TYPES = _TYPES


def get(key: str) -> ObjectType | None:
    return TYPES.get(key)


def registry() -> dict[str, object]:
    """The taxonomy as plain data, for Admin and the web app."""
    return {
        "version": TAXONOMY_VERSION,
        "categories": dict(CATEGORIES),
        "types": [
            {
                "key": item.key,
                "category": item.category,
                "label": item.label,
                "kind": item.kind,
                "many": item.many,
                "priority": item.priority,
                "fast": item.fast,
                "lead_field": item.lead_field,
                "prospect_field": item.prospect_field,
                "auto_fill": item.auto_fill is not None,
                "ask": item.ask,
                "enum_values": list(item.enum_values),
                "ai_read": item.ai_read,
            }
            for item in _TYPES
        ],
    }
