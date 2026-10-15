"""Human-entered call outcome values; no AI, authority, persistence or stage inference.

Owner inbox, 11 October 2026 04:50 IST: won, lost with a reason,
follow-up with a date, no decision, and an optional stated deal value.
An absent revision is unrecorded, never an inferred no-decision outcome.
The HTTP/store boundary must supply the actor, current call/prospect binding,
optimistic revision and append-only audit. Validation cannot establish them.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.prospect_fact_contract import NumericFactValue

SCHEMA = "ac.sales-xray.call-outcome/1"
OUTCOMES = frozenset({"won", "lost", "follow_up", "no_decision"})
_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,4})?\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
MAX_SAFE_REVISION = 2**53 - 1


class OutcomeValidationError(ValueError):
    """Content-free code, safe to expose without repeating private input."""


@dataclass(frozen=True, slots=True)
class DealValue:
    amount: str
    currency_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, str) or not _AMOUNT.fullmatch(self.amount):
            raise OutcomeValidationError("invalid_deal_amount")
        # Reuse canonical precision bounds, with no float, rounding, FX or scale conversion.
        try:
            NumericFactValue(
                interval_shape="point",
                approximation="exact",
                lower=Decimal(self.amount),
                upper=Decimal(self.amount),
                lower_inclusive=True,
                upper_inclusive=True,
                currency_code=self.currency_code,
            )
        except ValueError:
            raise OutcomeValidationError("invalid_deal_currency") from None
        if not isinstance(self.currency_code, str):
            raise OutcomeValidationError("invalid_deal_currency")

    def json(self) -> dict[str, str]:
        return {"amount": self.amount, "currency_code": self.currency_code}


@dataclass(frozen=True, slots=True)
class HumanOutcome:
    outcome: str
    lost_reason: str | None = None
    follow_up_on: date | None = None
    deal_value: DealValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, str) or self.outcome not in OUTCOMES:
            raise OutcomeValidationError("invalid_outcome")
        if self.outcome == "lost":
            if (
                not isinstance(self.lost_reason, str)
                or not self.lost_reason.strip()
                or len(self.lost_reason) > 1000
                or "\x00" in self.lost_reason
            ):
                raise OutcomeValidationError("lost_reason_required")
        elif self.lost_reason is not None:
            raise OutcomeValidationError("reason_only_for_lost")
        if self.outcome == "follow_up":
            if type(self.follow_up_on) is not date:
                raise OutcomeValidationError("follow_up_date_required")
        elif self.follow_up_on is not None:
            raise OutcomeValidationError("date_only_for_follow_up")
        if self.deal_value is not None and not isinstance(self.deal_value, DealValue):
            raise OutcomeValidationError("invalid_deal_value")

    @classmethod
    def parse(cls, payload: object) -> "HumanOutcome":
        if (
            not isinstance(payload, dict)
            or "outcome" not in payload
            or set(payload) - {"outcome", "lost_reason", "follow_up_on", "deal_value"}
        ):
            raise OutcomeValidationError("invalid_outcome_fields")
        follow_up_on = payload.get("follow_up_on")
        if follow_up_on is not None:
            if not isinstance(follow_up_on, str) or not _DATE.fullmatch(follow_up_on):
                raise OutcomeValidationError("invalid_follow_up_date")
            try:
                follow_up_on = date.fromisoformat(follow_up_on)
            except ValueError:
                raise OutcomeValidationError("invalid_follow_up_date") from None
        value = payload.get("deal_value")
        if value is not None:
            if not isinstance(value, dict) or set(value) != {"amount", "currency_code"}:
                raise OutcomeValidationError("invalid_deal_value")
            value = DealValue(value["amount"], value["currency_code"])
        return cls(payload["outcome"], payload.get("lost_reason"), follow_up_on, value)

    def json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "lost_reason": self.lost_reason,
            "follow_up_on": self.follow_up_on.isoformat() if self.follow_up_on else None,
            "deal_value": self.deal_value.json() if self.deal_value else None,
        }


@dataclass(frozen=True, slots=True)
class HumanOutcomeCommand:
    """Prepared optimistic intent, never proof of call, person or manager authority.

    The future store must re-admit the active actor and lock/check these three
    current revisions in the same transaction as append-only outcome/stage audit.
    An unlinked call explicitly pins null membership AND null stage revision.
    """

    value: HumanOutcome
    expected_revision: int
    expected_membership_id: UUID | None
    expected_prospect_stage_revision: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.value, HumanOutcome):
            raise OutcomeValidationError("invalid_outcome_command_value")
        if (
            type(self.expected_revision) is not int
            or not 0 <= self.expected_revision < MAX_SAFE_REVISION
        ):
            raise OutcomeValidationError("invalid_expected_outcome_revision")
        if self.expected_membership_id is None:
            if self.expected_prospect_stage_revision is not None:
                raise OutcomeValidationError("invalid_expected_prospect_binding")
        elif (
            not isinstance(self.expected_membership_id, UUID)
            or type(self.expected_prospect_stage_revision) is not int
            or not 0 <= self.expected_prospect_stage_revision <= MAX_SAFE_REVISION
        ):
            raise OutcomeValidationError("invalid_expected_prospect_binding")

    @classmethod
    def parse(cls, payload: object) -> "HumanOutcomeCommand":
        if not isinstance(payload, dict) or set(payload) != {
            "value",
            "expected_revision",
            "expected_membership_id",
            "expected_prospect_stage_revision",
        }:
            raise OutcomeValidationError("invalid_outcome_command_fields")
        membership = payload["expected_membership_id"]
        if membership is not None:
            if not isinstance(membership, str):
                raise OutcomeValidationError("invalid_expected_prospect_binding")
            try:
                parsed_membership = UUID(membership)
            except ValueError:
                raise OutcomeValidationError("invalid_expected_prospect_binding") from None
            if str(parsed_membership) != membership:
                raise OutcomeValidationError("invalid_expected_prospect_binding")
            membership = parsed_membership
        return cls(
            HumanOutcome.parse(payload["value"]),
            payload["expected_revision"],
            membership,
            payload["expected_prospect_stage_revision"],
        )

    def json(self) -> dict[str, Any]:
        return {
            "value": self.value.json(),
            "expected_revision": self.expected_revision,
            "expected_membership_id": (
                str(self.expected_membership_id)
                if self.expected_membership_id is not None
                else None
            ),
            "expected_prospect_stage_revision": self.expected_prospect_stage_revision,
        }
