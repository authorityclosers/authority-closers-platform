"""Sales X-Ray unit economics, pure (owner, 23 Oct 2026: "making economically strong app which
can earn money according to how much we overall spend from all points").

What each plan earns after GST and the payment fee, what its minutes cost on each analysis
route, its margin at 25%, 50% and 100% minute use, how many plans cover the fixed costs, and
what a free trial costs. Prices come from the plans table as sold; costs per audio minute come
from the metrics store (measured) and the analysis engine registry (each plan's projection on
production's real call mix); fixed costs and fee rates from Admin's economics settings.

Rupees a month, list prices, never a bill. Admin only: nothing here reaches a user screen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

USES = (0.25, 0.5, 1.0)

Channel = Literal["web", "play"]
Interval = Literal["monthly", "yearly"]


@dataclass(frozen=True)
class TopUp:
    key: str
    minutes: int
    price_paise: int


@dataclass(frozen=True)
class PlanTerms:
    """One active plan as sold (the plans table)."""

    key: str
    name: str
    per_seat: bool
    prices_include_gst: bool
    monthly_paise: int | None
    yearly_paise: int | None
    minutes: int | None
    top_ups: tuple[TopUp, ...] = ()


@dataclass(frozen=True)
class Route:
    """An analysis route's cost per audio minute on the real call mix."""

    id: str
    label: str
    source: str  # measured | projection
    per_audio_minute: float


@dataclass(frozen=True)
class Fees:
    gst_rate: float
    razorpay_rate: float
    razorpay_gst_on_fee: bool
    play_rate: float

    def charge(self, gross: float, channel: Channel) -> tuple[float, float, float]:
        """(price without GST, payment fee, what is left) for one charge of ``gross``.

        Razorpay takes its rate of the amount charged, plus GST on its fee; Play Billing
        takes its rate of the price without tax.
        """
        ex_gst = gross / (1 + self.gst_rate)
        if channel == "play":
            fee = ex_gst * self.play_rate
        else:
            fee = (
                gross
                * self.razorpay_rate
                * ((1 + self.gst_rate) if self.razorpay_gst_on_fee else 1)
            )
        return ex_gst, fee, ex_gst - fee


def _gross(price_paise: int, include_gst: bool, gst_rate: float) -> float:
    rupees = price_paise / 100
    return rupees if include_gst else rupees * (1 + gst_rate)


def offers(plans: Sequence[PlanTerms], play_plans: Sequence[str]) -> list[dict[str, Any]]:
    """Every way a plan is sold, priced per month (a yearly price over 12 months)."""
    rows: list[dict[str, Any]] = []
    for plan in plans:
        if not plan.minutes:
            continue
        unit = "seat" if plan.per_seat else "plan"
        for interval, paise in (("monthly", plan.monthly_paise), ("yearly", plan.yearly_paise)):
            if paise is None:
                continue
            per_month = paise if interval == "monthly" else paise / 12
            channels: tuple[Channel, ...] = ("web", "play") if plan.key in play_plans else ("web",)
            for channel in channels:
                where = "web" if channel == "web" else "Play Store"
                rows.append(
                    {
                        "id": f"{plan.key}.{interval}.{channel}",
                        "plan": plan.key,
                        "label": f"{plan.name}, {interval}, {where}",
                        "unit": unit,
                        "interval": interval,
                        "channel": channel,
                        "price_paise_per_month": round(per_month),
                        "prices_include_gst": plan.prices_include_gst,
                        "minutes": plan.minutes,
                    }
                )
    return rows


def _round(value: float) -> float:
    return round(value, 2)


def economics(
    plans: Sequence[PlanTerms],
    routes: Sequence[Route],
    *,
    audio_per_billed: float,
    fixed: Sequence[Mapping[str, Any]],
    fees: Fees,
    play_plans: Sequence[str],
    break_even_route: str,
    trial_minutes: int,
    trial_conversion: float,
    target_margin: float,
) -> dict[str, Any]:
    """The whole picture for Admin. ``audio_per_billed`` turns ₹ per audio minute into ₹ per
    plan minute (plans count billed minutes); ``fixed`` items are {key, label, rupees, kind}."""
    per_plan_minute = {route.id: route.per_audio_minute * audio_per_billed for route in routes}
    route_rows = [
        {
            "id": route.id,
            "label": route.label,
            "source": route.source,
            "per_audio_minute": round(route.per_audio_minute, 4),
            "per_plan_minute": round(per_plan_minute[route.id], 4),
        }
        for route in routes
    ]
    running = sum(float(item["rupees"]) for item in fixed if item.get("kind") == "running")
    building = sum(float(item["rupees"]) for item in fixed if item.get("kind") == "building")
    total_fixed = running + building
    base_cost = per_plan_minute.get(break_even_route)

    offer_rows = []
    warnings: list[dict[str, Any]] = []
    for offer in offers(plans, play_plans):
        gross = _gross(offer["price_paise_per_month"], offer["prices_include_gst"], fees.gst_rate)
        ex_gst, fee, net = fees.charge(gross, offer["channel"])
        minutes = offer["minutes"]
        margins = {}
        for route in routes:
            cost_minute = per_plan_minute[route.id]
            cells = []
            for use in USES:
                cost = minutes * use * cost_minute
                margin = net - cost
                cells.append(
                    {
                        "use": use,
                        "cost": _round(cost),
                        "margin": _round(margin),
                        "share": None if net <= 0 else round(margin / net, 4),
                    }
                )
                if use == 1.0 and margin < 0:
                    warnings.append(
                        {"offer": offer["id"], "route": route.id, "kind": "loss_at_full_use"}
                    )
            margins[route.id] = cells
        break_even = None
        if base_cost is not None:
            break_even = {}
            for use in (0.5, 1.0):
                contribution = net - minutes * use * base_cost
                break_even[str(use)] = {
                    "contribution": _round(contribution),
                    "running": None if contribution <= 0 else round(running / contribution, 1),
                    "total": None if contribution <= 0 else round(total_fixed / contribution, 1),
                }
            full = net - minutes * base_cost
            if net > 0 and full / net < target_margin:
                warnings.append(
                    {"offer": offer["id"], "route": break_even_route, "kind": "below_target_margin"}
                )
        offer_rows.append(
            {
                **offer,
                "gross": _round(gross),
                "ex_gst": _round(ex_gst),
                "fee": _round(fee),
                "net": _round(net),
                "margins": margins,
                "break_even": break_even,
                # The cost per plan minute at which full use still leaves the target margin.
                "ceiling_per_plan_minute": round(net * (1 - target_margin) / minutes, 3),
            }
        )

    top_ups = []
    for plan in plans:
        for pack in plan.top_ups:
            gross = _gross(pack.price_paise, plan.prices_include_gst, fees.gst_rate)
            ex_gst, fee, net = fees.charge(gross, "web")
            per_minute = net / pack.minutes
            top_ups.append(
                {
                    "plan": plan.key,
                    "key": pack.key,
                    "minutes": pack.minutes,
                    "gross": _round(gross),
                    "net": _round(net),
                    "net_per_minute": round(per_minute, 3),
                    "margin_share": {
                        route.id: None
                        if per_minute <= 0
                        else round((per_minute - per_plan_minute[route.id]) / per_minute, 4)
                        for route in routes
                    },
                }
            )

    trial_cost = None if base_cost is None else trial_minutes * base_cost
    return {
        "routes": route_rows,
        "audio_per_billed": round(audio_per_billed, 4),
        "uses": list(USES),
        "offers": offer_rows,
        "top_ups": top_ups,
        "fixed": {
            "items": [dict(item) for item in fixed],
            "running": _round(running),
            "building": _round(building),
            "total": _round(total_fixed),
        },
        "break_even_route": break_even_route,
        "target_margin": target_margin,
        "trial": {
            "minutes": trial_minutes,
            "cost": None if trial_cost is None else _round(trial_cost),
            "conversion": trial_conversion,
            "per_paying_user": None
            if trial_cost is None or trial_conversion <= 0
            else _round(trial_cost / trial_conversion),
        },
        "warnings": warnings,
    }
