"""Finite output bounds; larger C5 requests still require fresh exact approval."""

from ac_platform.one_pass.markers import MAX_COMPLETION_TOKENS as ONE_PASS_MAX_COMPLETION_TOKENS
from ac_platform.one_pass.markers import RECIPE as ONE_PASS_RECIPE
from ac_platform.one_pass.markers import ROUTES as ONE_PASS_ROUTES


def completion_ceiling(provider: str, model: str, stage: str, *, recipe: str | None = None) -> int:
    # The one-pass C4 request (one_pass.stage) answers call data, notes and the review
    # in one read; only its own recipe on its own routes is that large. Every other C4
    # request (the fact chunks) keeps 4,000.
    if stage == "C4" and recipe == ONE_PASS_RECIPE and (provider, model) in ONE_PASS_ROUTES:
        return ONE_PASS_MAX_COMPLETION_TOKENS
    # A Flex route (gemini_tiers) has its model's own bounds.
    if provider == "gemini" and model.endswith(":flex"):
        model = model[: -len(":flex")]
    if (provider, model, stage) == ("gemini", "gemini-3.8-flash", "C5"):
        return 8_000
    if (provider, model, stage) in {
        ("openai", "gpt-6-luna", "C5"),
        ("openai", "gpt-6-sol", "C5"),
        ("openai", "gpt-6-astra", "C5"),
    }:
        return 8_000
    return 4_000


def require_approval_completion_bound(
    provider: str,
    model: str,
    stage: str,
    maximum: int,
    cost_basis: str,
    cost_paise: int,
    *,
    recipe: str | None = None,
) -> None:
    if maximum > completion_ceiling(provider, model, stage, recipe=recipe):
        raise ValueError("stage_completion_tokens_exceed_route_limit")
    if maximum > 4_000 and cost_basis == "paid_pricing_evidence" and cost_paise < 1_000:
        raise ValueError("extended_coaching_cost_approval_required")
