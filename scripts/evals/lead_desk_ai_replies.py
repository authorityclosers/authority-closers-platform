"""Evals for Lead Desk AI replies against the real model, on fictional businesses.

Runs every case in ``tests/unit/lead_desk_ai_replies/businesses.py`` (the rule cases
and the cases only the model can judge) through the same path a lead's message takes:
the rules, then the model through the AI provider registry and its budget caps, then
the checks on its draft. Prints one line per case and a pass count; exits non-zero if
any case fails. Fictional businesses only; no customer data.

Usage (on a machine with the AI provider settings, e.g. dev):
    uv run python scripts/evals/lead_desk_ai_replies.py [--tenant <uuid>]
The tenant (default: a new random id) is only what the budget cap and usage rows are
counted against.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID, uuid4

from ac_platform.lead_desk.ai_replies import prompt, registry, service
from tests.unit.lead_desk_ai_replies.businesses import CASES, MODEL_CASES, Case


async def one(model: service.Model, case: Case, tenant: UUID) -> tuple[bool, str]:
    ready = service.Prepared(
        tenant_id=tenant,
        lead_id=uuid4(),
        lead_name="Asha Fictional",
        owner_person_id=None,
        payload=None,
        channel="whatsapp",
        account_id=None,
        settings=case.business,
        turns=[prompt.Turn("in", case.message)],
        last_in_id=uuid4(),
        last_in_text=case.message,
        window_open=True,
    )
    result = await service.think(model, ready)
    got = (
        "reply"
        if result.outcome == "drafted"
        else "opt_out"
        if result.outcome == "opted_out"
        else (result.reason or result.outcome)
    )
    shown = result.draft or ""
    return got == case.expect, f"{got:<12} {case.message[:50]!r} {shown[:80]!r}"


async def main(tenant: UUID) -> int:
    from ac_platform.db.session import session_factory  # the API's own sessions

    sessions = session_factory
    model = registry.model_for(sessions)
    passed = 0
    cases = (*CASES, *MODEL_CASES)
    for case in cases:
        ok, line = await one(model, case, tenant)
        passed += ok
        print(
            ("PASS " if ok else "FAIL ")
            + f"[{case.business.business_name}] want {case.expect}: {line}"
        )
    print(f"{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", type=UUID, default=None)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.tenant or uuid4())))
