"""AC's real monthly cost, who each cost serves, and what each product earns and spends
(owner, 30 Oct 2026: "Fixed costs a month ₹52,214 … is not how much AC really spends").

- **The register:** Admin's economics settings until Pulse finance can be read (the Pulse
  team's ``pulse.costs.read``); then Pulse. Each cost has a vendor, a rupee amount (the
  original currency kept beside it), a cadence, a category, the cost centre that owns it
  and an allocation rule.
- **A cost a month:** monthly as charged, quarterly / 3, yearly / 12, usage as the monthly
  average entered, and a one-time purchase spread evenly over its stated life from the
  month it was bought (devices: 24 months). A cost stops after the month it ended.
- **Allocation to the products:**
  - ``direct``: one product;
  - ``token_burn``: the agents' work per project, measured from the agent logs;
  - ``cpu_share``: the server's time for the apps against the agents;
  - ``revenue_share``: overhead by what each product earns;
  - ``fixed``: stated shares (people, by the time they give each product).

  Platform and ops work (shared code, infrastructure, CI) goes to the products in
  proportion to their own work, or stays a company cost (``platform_work``). A key not
  measured yet keeps the cost with the company and says so.
- **Profit and loss per product:** money in (net of GST and the payment fee) less the costs
  allocated to it; break-even as Personal plans (or Organisation seats) needed to cover them.

People cost is one monthly total and debt one line, never one line per person. Rupees a
month, Admin only; nothing here reaches a user screen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

CATEGORIES: dict[str, str] = {
    "servers": "Servers and cloud",
    "ai_subscriptions": "AI subscriptions for the agents",
    "ai_product": "AI for the product",
    "ai_other": "Other AI APIs",
    "tools": "Software and tools",
    "workspace": "Workspace, email and domains",
    "store_fees": "Store and platform fees",
    "devices": "Devices and studio",
    "marketing": "Marketing",
    "people": "People",
    "professional": "Professional fees",
    "financing": "Debt and interest",
    "other": "Other",
}
CENTRES: dict[str, str] = {
    "sales_xray": "Sales X-Ray",
    "company": "AC company-wide",
    "agents": "Agents and AI tooling",
    "people": "People",
}
PRODUCTS: dict[str, str] = {
    "sales_xray": "Sales X-Ray",
    "learner": "Learner app",
    "other_companies": "Other companies",
    "company": "AC company, not allocated",
}
CADENCES = ("monthly", "quarterly", "yearly", "one_time", "usage")
RULES = ("direct", "token_burn", "cpu_share", "revenue_share", "fixed")
TOOLS = ("claude", "codex", "all")
PLATFORM_WORK = ("pro_rata", "company")
# One total each: never one line per person or per loan.
SINGLE = ("people", "financing")
DEFAULT_LIFE_MONTHS = 24

# Where each measured area of agent work belongs. Platform and ops work (shared code,
# infrastructure, CI) and work the logs can't place follow ``platform_work``.
AREA_PRODUCT: dict[str, str] = {
    "sales_xray": "sales_xray",
    "learner": "learner",
    "pulse_ea": "other_companies",
    "naya": "other_companies",
}
SHARED_AREAS = ("ops", "unattributed")
# The products shared platform work is spread over.
BUILT_PRODUCTS = ("sales_xray", "learner")


@dataclass(frozen=True)
class Keys:
    """The measured allocation keys: agent work per area for each tool (list-price
    weighted tokens), the server's CPU shares, and each product's net money in a month."""

    tokens: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    cpu: Mapping[str, float] | None = None
    revenue: Mapping[str, float] = field(default_factory=dict)


def _month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def _day(value: Any) -> date | None:
    return None if not value else date.fromisoformat(str(value))


def monthly(item: Mapping[str, Any], month: date) -> float:
    """What one register item costs in ``month`` (any day of it)."""
    started, ended = _day(item.get("started")), _day(item.get("ended"))
    now = _month_index(month)
    if started is not None and now < _month_index(started):
        return 0.0
    if ended is not None and now > _month_index(ended):
        return 0.0
    rupees = float(item["rupees"])
    cadence = item["cadence"]
    if cadence == "quarterly":
        return rupees / 3
    if cadence == "yearly":
        return rupees / 12
    if cadence == "one_time":
        life = int(item.get("life_months") or DEFAULT_LIFE_MONTHS)
        if started is None or now >= _month_index(started) + life:
            return 0.0
        return rupees / life
    return rupees


def _normal(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(value for value in weights.values() if value > 0)
    if total <= 0:
        return {}
    return {key: value / total for key, value in weights.items() if value > 0}


def _merge(target: dict[str, float], shares: Mapping[str, float], scale: float) -> None:
    for key, value in shares.items():
        target[key] = target.get(key, 0.0) + value * scale


def token_shares(keys: Keys, tool: str, platform_work: str) -> dict[str, float]:
    """Each product's share of the agents' work on ``tool`` ("all": the tools' shares
    averaged), shared platform work spread or kept, as ``platform_work`` says."""
    tools = [name for name in keys.tokens if tool in ("all", name)]
    if not tools:
        return {}
    combined: dict[str, float] = {}
    for name in tools:
        areas = _normal(keys.tokens[name])
        direct: dict[str, float] = {}
        shared = 0.0
        for area, value in areas.items():
            if area in AREA_PRODUCT:
                product = AREA_PRODUCT[area]
                direct[product] = direct.get(product, 0.0) + value
            else:
                shared += value
        if shared:
            built = _normal({key: direct.get(key, 0.0) for key in BUILT_PRODUCTS})
            if platform_work == "pro_rata" and built:
                _merge(direct, built, shared)
            else:
                direct["company"] = direct.get("company", 0.0) + shared
        _merge(combined, direct, 1 / len(tools))
    return _normal(combined)


def allocate(
    item: Mapping[str, Any], keys: Keys, platform_work: str
) -> tuple[dict[str, float], str]:
    """(each product's share of the item, the basis in words)."""
    rule = item["allocation"]
    kind = rule["rule"]
    if kind == "direct":
        return {rule["product"]: 1.0}, "direct"
    if kind == "fixed":
        return _normal(rule["shares"]), "stated shares"
    if kind == "token_burn":
        shares = token_shares(keys, rule.get("tool", "all"), platform_work)
        if shares:
            return shares, "agent work measured"
        return {"company": 1.0}, "agent work not measured yet"
    if kind == "cpu_share":
        cpu = _normal(keys.cpu or {})
        if not cpu:
            return {"company": 1.0}, "server time not measured yet"
        server: dict[str, float] = {}
        _merge(server, {"sales_xray": 1.0}, cpu.get("apps", 0.0))
        agents = token_shares(keys, "codex", platform_work) or {"company": 1.0}
        _merge(server, agents, cpu.get("agents", 0.0))
        _merge(server, {"company": 1.0}, cpu.get("other", 0.0))
        return _normal(server), "server time measured"
    revenue = _normal(keys.revenue)
    if revenue:
        return revenue, "money in"
    return {"company": 1.0}, "no money in yet"


def _round(value: float) -> float:
    return round(value, 2)


def analysis(
    items: Sequence[Mapping[str, Any]],
    *,
    month: date,
    keys: Keys,
    platform_work: str,
    contribution: Mapping[str, float | None],
) -> dict[str, Any]:
    """The real cost picture for one month. ``contribution`` is what one Personal plan
    and one Organisation seat leave a month after their minutes (at 50% use), for
    break-even; ``keys.revenue`` is each product's net money in a month."""
    rows: list[dict[str, Any]] = []
    by_category: dict[str, float] = {}
    by_centre: dict[str, float] = {}
    by_product: dict[str, float] = {key: 0.0 for key in PRODUCTS}
    for item in items:
        amount = monthly(item, month)
        shares, basis = allocate(item, keys, platform_work)
        split = {product: amount * share for product, share in shares.items()}
        for product, rupees in split.items():
            by_product[product] = by_product.get(product, 0.0) + rupees
        by_category[item["category"]] = by_category.get(item["category"], 0.0) + amount
        by_centre[item["centre"]] = by_centre.get(item["centre"], 0.0) + amount
        started = _day(item.get("started"))
        life = item.get("life_months") or DEFAULT_LIFE_MONTHS
        left = None
        if item["cadence"] == "one_time" and started is not None:
            left = max(0, _month_index(started) + int(life) - _month_index(month) - 1)
        rows.append(
            {
                **{key: value for key, value in item.items() if key != "allocation"},
                "allocation": dict(item["allocation"]),
                "monthly": _round(amount),
                "active": amount > 0,
                "months_left": left,
                "basis": basis,
                "split": {product: _round(rupees) for product, rupees in split.items()},
            }
        )
    total = sum(by_category.values())
    personal, seat = contribution.get("personal"), contribution.get("seat")

    def plans(cost: float, per_unit: float | None) -> float | None:
        if per_unit is None or per_unit <= 0:
            return None
        return round(cost / per_unit, 1)

    products = []
    for key, label in PRODUCTS.items():
        money_in = float(keys.revenue.get(key, 0.0))
        cost = by_product.get(key, 0.0)
        if not cost and not money_in:
            continue
        profit = money_in - cost
        products.append(
            {
                "key": key,
                "label": label,
                "money_in": _round(money_in),
                "costs": _round(cost),
                "profit": _round(profit),
                "margin": None if money_in <= 0 else round(profit / money_in, 4),
                "break_even_personal": plans(cost, personal) if key == "sales_xray" else None,
                "break_even_seats": plans(cost, seat) if key == "sales_xray" else None,
            }
        )
    money_in = sum(float(value) for value in keys.revenue.values())
    return {
        "month": month.strftime("%Y-%m"),
        "total": _round(total),
        "by_category": [
            {"key": key, "label": CATEGORIES[key], "rupees": _round(by_category[key])}
            for key in sorted(by_category, key=lambda name: -by_category[name])
            if by_category[key] > 0
        ],
        "by_centre": [
            {"key": key, "label": label, "rupees": _round(by_centre.get(key, 0.0))}
            for key, label in CENTRES.items()
        ],
        "items": rows,
        "products": products,
        "overall": {
            "money_in": _round(money_in),
            "costs": _round(total),
            "profit": _round(money_in - total),
            "break_even_personal": plans(total, personal),
            "break_even_seats": plans(total, seat),
        },
        "platform_work": platform_work,
    }
