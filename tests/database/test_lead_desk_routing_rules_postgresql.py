"""Routing rules, saved and used on PostgreSQL through the API (owner, 27 Oct 2026:
"smarter" lead rules; lead_desk/routing_rules.py). The owner's own example: big budgets to
two sellers in turn, website forms to one, everything else by the lead rules."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_routing_rules_give_leads_by_value_source_and_turn(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            asha = UUID(str(here.seller.person_id))
            ravi_seed = await seed(
                here.setup.engine, tenant_id=here.setup.state.tenant_id, role="member"
            )
            ravi = UUID(str(ravi_seed.person_id))
            here.as_admin()

            async def team_rules(person: UUID, **rules: Any) -> None:
                team = (await here.client.get(f"{BASE}/team")).json()
                revision = next(
                    (rep["revision"] for rep in team["reps"] if rep["person_id"] == str(person)), 0
                )
                saved = await here.client.put(
                    f"{BASE}/team/{person}",
                    json={
                        "expected_revision": revision,
                        "available": True,
                        "max_open": 50,
                        **rules,
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text

            await team_rules(ravi)
            source = await here.client.post(
                f"{BASE}/sources",
                json={"kind": "webhook", "label": "Fictional website"},
                headers=WRITE,
            )
            assert source.status_code == 201, source.text
            capture = f"/v1/lead-desk/capture/{source.json()['source_id']}"
            key = source.json()["token"]

            async def website(name: str, phone: str, budget: str | None = None) -> dict[str, Any]:
                body = {"name": name, "phone": phone, **({"budget": budget} if budget else {})}
                sent = await here.client.post(capture, json=body, headers={"X-Lead-Desk-Key": key})
                assert sent.status_code == 202, sent.text
                here.as_admin()
                shown = await here.client.get(f"{BASE}/leads/{sent.json()['lead_id']}")
                assert shown.status_code == 200, shown.text
                return {**shown.json()["lead"], "owner_reason": shown.json()["owner_reason"]}

            empty = await here.client.get(f"{BASE}/routing-rules")
            assert empty.status_code == 200, empty.text
            view = empty.json()
            assert view["rules"] == [] and view["value_answer"] is None
            assert view["sources"]["google_ads"] == "Google Ads lead forms"
            assert {str(asha), str(ravi)} <= {item["person_id"] for item in view["people"]}

            rules = {
                "expected_revision": view["revision"],
                "value_answer": "budget",
                "rules": [
                    {
                        "name": "Big budgets",
                        "when": [{"field": "value", "op": "at_least", "low": 100000}],
                        "give_to": [str(asha), str(ravi)],
                    },
                    {
                        "name": "Website forms",
                        "when": [{"field": "source", "values": ["webhook"]}],
                        "give_to": [str(ravi)],
                    },
                ],
            }
            saved = await here.client.put(f"{BASE}/routing-rules", json=rules, headers=WRITE)
            assert saved.status_code == 200, saved.text
            assert [rule["name"] for rule in saved.json()["rules"]] == [
                "Big budgets",
                "Website forms",
            ]
            assert all(rule["id"] for rule in saved.json()["rules"])

            # Big budgets go to the two in turn; the reason names the rule.
            first = await website("Fictional Big One", "98760 83001", "₹1,50,000")
            second = await website("Fictional Big Two", "98760 83002", "2 lakh")
            assert {first["owner_person_id"], second["owner_person_id"]} == {str(asha), str(ravi)}
            assert "rule 1" in first["owner_reason"]
            # A small budget from the website form: the second rule.
            small = await website("Fictional Small", "98760 83003", "₹20,000")
            assert small["owner_person_id"] == str(ravi)
            assert "rule 2" in small["owner_reason"]
            # Added by hand, no budget: no rule matches, so the lead rules decide.
            typed = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Fictional Typed",
                    "phone": "98760 83004",
                },
                headers=WRITE,
            )
            assert typed.status_code == 201, typed.text
            assert typed.json()["lead"]["owner_person_id"] is not None
            assert "(rule " not in (typed.json()["owner_reason"] or "")

            # Asha away: the big budget goes to Ravi, whose turn it now is anyway.
            await team_rules(asha, available=False)
            away = await website("Fictional Big Three", "98760 83005", "5 lakh")
            assert away["owner_person_id"] == str(ravi)
            # Both away: the rule is passed over, the lead rules find nobody, and it says so.
            await team_rules(ravi, available=False)
            nobody = await website("Fictional Big Four", "98760 83006", "5 lakh")
            assert nobody["owner_person_id"] is None
            assert nobody["owner_reason"].startswith("Rule 1:")

            # Try a lead without saving one.
            await team_rules(asha)
            tried = await here.client.post(
                f"{BASE}/routing-rules/try", json={"value": "3 lakh"}, headers=WRITE
            )
            assert tried.status_code == 200, tried.text
            assert tried.json()["rule"] == 1 and tried.json()["rule_name"] == "Big budgets"
            assert tried.json()["person_id"] == str(asha)
            plain = await here.client.post(
                f"{BASE}/routing-rules/try", json={"source": "manual"}, headers=WRITE
            )
            assert plain.json()["rule"] is None
            assert plain.json()["why"].startswith("Lead rules:")

            # Recent leads' form questions are offered, with their answers.
            questions = (await here.client.get(f"{BASE}/routing-rules")).json()["questions"]
            budget = next(item for item in questions if item["key"] == "budget")
            assert budget["answered"] >= 5 and "2 lakh" in budget["examples"]

            # A stranger in a rule, or an old revision, is refused.
            current = (await here.client.get(f"{BASE}/routing-rules")).json()["revision"]
            stranger = {
                **rules,
                "expected_revision": current,
                "rules": [{**rules["rules"][1], "give_to": [str(uuid4())]}],
            }
            refused = await here.client.put(f"{BASE}/routing-rules", json=stranger, headers=WRITE)
            assert refused.status_code == 422, refused.text
            stale = await here.client.put(
                f"{BASE}/routing-rules", json={**rules, "expected_revision": 0}, headers=WRITE
            )
            assert stale.status_code == 409, stale.text

    run(exercise())
