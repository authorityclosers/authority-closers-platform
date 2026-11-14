"""The AI credit runway email: its outbox route, its checked numbers and its reasoning.

Owner, 13 Nov 2026 (via the orchestrator): "before the budget ends we get an email exactly
where to add what budget, with the clear estimate how much needs to be added… two to three
thousand is more than enough for testing." ``credit_runway`` works the numbers out and
queues the alert; this module stays light so the worker and the email adapter can load it.
The email itself is drawn in ``providers.resend_email`` in the tester welcome's style.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute
from ac_platform.providers.ports import EmailMessage, PermanentProviderError

TEMPLATE = "ai-credit-runway"
EVENT = "ai_spend.credit_runway.alert.v1"
JOB = "email.ai_credit_runway.v1"
# The owner's own address (his order): the alert never goes anywhere else.
EMAIL_TO = "admin@authorityclosers.com"
# Where Gemini credit is bought: AI Studio's billing page for the prepaid
# account, with Buy credits on it (the orchestrator's confirmed link, 14 Nov 2026).
PAY_URL = "https://aistudio.google.com/billing?billing=0146E3-722EE0-47B3D5"
PAY_PATH = "AI Studio → Billing → Buy credits"
GOOGLE_IS_THE_TRUTH = (
    "These numbers are our own estimate from the cost ledger. If Google's billing page "
    "shows a different balance, Google's figure is the truth: our ledger can undercount."
)

INT_KEYS = frozenset(
    {
        "topup_inr",
        "spent_inr",
        "balance_inr",
        "burn_inr_per_day",
        "add_inr",
        "days_to_month_end",
        "floor_inr",
    }
)
TEXT_KEYS = frozenset({"day", "provider", "account", "topup_on", "month"})
ROUTE = OutboxJobRoute(
    job_kind=JOB,
    required_payload_keys=INT_KEYS | TEXT_KEYS | {"days_left"},
    allowed_payload_values={"provider": frozenset({"Gemini"})},
)
_DAY = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]")
_ACCOUNT = re.compile(r"[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}")
_MONTHS = frozenset(
    {
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    }
)


def checked(variables: Mapping[str, Any]) -> dict[str, Any]:
    """The alert's numbers, exactly as the route allows them, or a permanent refusal."""
    values: dict[str, Any] = {}
    for key in INT_KEYS:
        value = variables.get(key)
        if type(value) is not int or not -10_000_000 <= value <= 10_000_000:
            raise PermanentProviderError("credit runway numbers are invalid")
        values[key] = value
    days = variables.get("days_left")
    if days is not None and (type(days) is not int or not 0 <= days <= 10_000):
        raise PermanentProviderError("credit runway days are invalid")
    values["days_left"] = days
    if (
        variables.get("provider") != "Gemini"
        or not isinstance(variables.get("account"), str)
        or _ACCOUNT.fullmatch(variables["account"]) is None
        or not isinstance(variables.get("day"), str)
        or _DAY.fullmatch(variables["day"]) is None
        or not isinstance(variables.get("topup_on"), str)
        or _DAY.fullmatch(variables["topup_on"]) is None
        or variables.get("month") not in _MONTHS
    ):
        raise PermanentProviderError("credit runway labels are invalid")
    for key in TEXT_KEYS:
        values[key] = variables[key]
    if values["add_inr"] < values["floor_inr"] or values["floor_inr"] < 1:
        raise PermanentProviderError("credit runway amount is below its floor")
    return values


def rupees(value: int) -> str:
    return f"Rs {value:,}"


def reason(values: Mapping[str, Any]) -> str:
    """Why this amount, in one line."""
    burn, left = values["burn_inr_per_day"], max(values["balance_inr"], 0)
    add, floor, days = values["add_inr"], values["floor_inr"], values["days_to_month_end"]
    if burn <= 0:
        return (
            f"Nothing was spent on {values['provider']} in the last 7 days, so the "
            f"{rupees(floor)} minimum is enough."
        )
    cover = burn * days
    need = max(cover - left, 0)
    line = (
        f"About {rupees(burn)} a day over the last 7 days × {days} "
        f"{'day' if days == 1 else 'days'} left in {values['month']} = {rupees(cover)}; with "
        f"{rupees(left)} left, that needs {rupees(need)}"
    )
    if need <= floor:
        return f"{line}, so the {rupees(floor)} minimum covers it."
    return f"{line}, rounded up to {rupees(add)}."


def subject(values: Mapping[str, Any]) -> str:
    days = values["days_left"]
    if values["balance_inr"] <= 0 or days == 0:
        return f"{values['provider']} credit is about to run out: add {rupees(values['add_inr'])}"
    if days is None:
        left = f"{rupees(values['balance_inr'])} left"
    else:
        left = f"about {days} {'day' if days == 1 else 'days'} left"
    return f"{values['provider']} credit: {left}, add {rupees(values['add_inr'])}"


async def resolve_runway_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    del database, settings
    if job.kind != JOB:
        raise PermanentProviderError("credit runway route is unavailable")
    payload = ROUTE.normalize_payload(job.payload)
    checked(payload)
    return EmailMessage(
        to=EMAIL_TO,
        template=TEMPLATE,
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={"first_name": "Suyash", **payload},
    )


__all__ = [
    "EMAIL_TO",
    "EVENT",
    "GOOGLE_IS_THE_TRUTH",
    "JOB",
    "PAY_PATH",
    "PAY_URL",
    "ROUTE",
    "TEMPLATE",
    "checked",
    "reason",
    "resolve_runway_message",
    "subject",
]
