"""Evals for Lead Desk AI replies against the real model, on fictional businesses.

Runs every case in ``tests/unit/lead_desk_ai_replies/businesses.py`` (the rule cases
and the cases only the model can judge) through the same path a lead's message takes:
the rules, then the model Admin can choose (``registry.ProviderModel``), then the
checks on its draft. Prints one line per case and a pass count; exits non-zero if any
case fails. Fictional businesses only; no customer data, and nothing is written.

The key comes the way the AI replies runner gets it: run this inside the worker's
provider launcher (``infisical run`` with the gemini entry of the service config), e.g.
    infisical run ... -- uv run python scripts/evals/lead_desk_ai_replies.py [--model M]
The model defaults to Admin's default (the first Gemini model of the call data menu).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID, uuid4

from ac_platform.lead_desk.ai_replies import admin_settings, prompt, registry, service
from tests.unit.lead_desk_ai_replies.businesses import CASES, MODEL_CASES, Case


async def one(model: service.Model, case: Case, tenant: UUID) -> tuple[bool, str]:
    ready = service.Prepared(
        tenant_id=tenant,
        lead_id=uuid4(),
        lead_name="Asha Fictional",
        owner_person_id=None,
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


async def main(tenant: UUID, model_name: str | None) -> int:
    config = admin_settings.validate({"model": model_name} if model_name else {})
    model = registry.ProviderModel(config)
    print(f"model {config['provider']}/{config['model']}")
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
    parser.add_argument("--model", default=None, help="a model from Admin's menu")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.tenant or uuid4(), args.model)))
