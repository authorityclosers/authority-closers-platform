"""Finite output bounds; larger C5 requests still require fresh exact approval."""


def completion_ceiling(provider: str, model: str, stage: str) -> int:
    if (provider, model, stage) == ("gemini", "gemini-3.8-flash", "C5"):
        return 8_000
    return 4_000


def require_approval_completion_bound(
    provider: str, model: str, stage: str, maximum: int, cost_basis: str, cost_paise: int
) -> None:
    if maximum > completion_ceiling(provider, model, stage):
        raise ValueError("stage_completion_tokens_exceed_route_limit")
    if maximum > 4_000 and cost_basis == "paid_pricing_evidence" and cost_paise < 1_000:
        raise ValueError("extended_coaching_cost_approval_required")
