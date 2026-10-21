"""scripts/data-changes/one-pass-flex-production.py on PostgreSQL (AUT-2177): prepare, switch
and back through the same service functions as Admin, dry run by default, idempotent,
refused unless the sealed approval contains the digest, audited with the owner's approval.
Fictional fixture only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
)
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.one_pass import c2_route
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "one_pass_flex_production", ROOT / "scripts/data-changes/one-pass-flex-production.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

_FIELDS = tuple(AcquisitionStagePolicy.model_fields)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _with_policy(setup: Any) -> Any:
    """The fixture's bundle with an acquisition policy approving its classic stages, as a
    hosted bundle carries one."""
    bundle = setup.bundle
    policy = AcquisitionProviderPolicy(
        schema="ac.sales-xray.acquisition-provider-policy/1",
        id=uuid4(),
        tenant_id=setup.prepared.state.tenant_id,
        processing_person_id=setup.prepared.state.person_id,
        authorization_ref="ref:approval/acquisition-flex-data-change-test",
        expires_at_epoch=bundle.expires_at_epoch - 1,
        max_recordings=64,
        max_source_bytes=134_217_728,
        max_stored_source_bytes=8_589_934_592,
        stages=tuple(
            AcquisitionStagePolicy(**{field: getattr(stage, field) for field in _FIELDS})
            for stage in bundle.stages
        ),
    )
    return bundle.model_copy(update={"acquisition_policy": policy})


def test_prepare_switch_and_back_from_the_cli(postgres_harness: Any, tmp_path: Any) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=25
        )
        try:
            unsealed = _with_policy(setup)
            person = setup.actor.person_id
            async with setup.sessions() as db:
                from ac_platform.identity.models import Person

                email = (await db.get(Person, person)).email
            ops = setup.prepared.state.tenant_id

            async def do(
                action: str, *, apply: bool, digest: str | None = None, bundle: Any = None
            ) -> Any:
                command = script.Command(
                    action=action,
                    environment="test",
                    control_email=email,
                    apply=apply,
                    digest=digest,
                )
                async with setup.sessions() as db:
                    transaction = await db.begin()
                    try:
                        result = await script.execute(
                            db,
                            command,
                            operations_tenant_id=ops,
                            load_bundle=lambda: bundle or unsealed,
                        )
                    except BaseException:
                        await transaction.rollback()
                        raise
                    if apply:
                        await transaction.commit()
                    else:
                        await transaction.rollback()
                    return result

            status = await do("status", apply=False)
            assert status["before"]["classic"]["transcription"] == "elevenlabs"
            assert status["before"]["flex_saved"] is None
            digest = status["before"]["flex_digest"]
            # A dry run saves nothing.
            dry = await do("prepare", apply=False)
            assert dry["status"] == "dry_run" and dry["after"]["flex_saved"] is not None
            assert (await do("status", apply=False))["before"]["flex_saved"] is None
            prepared = await do("prepare", apply=True)
            assert prepared["status"] == "applied"
            assert prepared["after"]["flex_saved"]["configuration_sha256"] == digest
            assert (await do("prepare", apply=True))["status"] == "no_op"
            # Refused: another digest, or a digest the sealed approval does not contain.
            with pytest.raises(script.Refused, match="derived_from_today"):
                await do("switch", apply=True, digest="0" * 64)
            with pytest.raises(script.Refused, match="sealed_approval_does_not_contain"):
                await do("switch", apply=True, digest=digest)
            classic = parse_registry_config(setup.config.as_dict())
            flex = c2_route.derive_configuration(classic, flex=True)
            assert flex.digest == digest
            sealed = c2_route.seal(unsealed, classic, flex, flex=True)
            switched = await do("switch", apply=True, digest=digest, bundle=sealed)
            assert switched["status"] == "applied"
            assert switched["after"]["active"]["configuration_sha256"] == digest
            assert (await do("switch", apply=True, digest=digest, bundle=sealed))[
                "status"
            ] == "no_op"
            back = await do("back", apply=True, bundle=sealed)
            assert back["status"] == "applied"
            assert back["after"]["active"]["transcription"] == "elevenlabs"
            assert (await do("back", apply=True, bundle=sealed))["status"] == "no_op"
            # Back and forth always acts (each activation is its own receipt).
            again = await do("switch", apply=True, digest=digest, bundle=sealed)
            assert again["status"] == "applied"
            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action.in_(
                                [script.PREPARED, "conversation.providers.gemini_transcription_on"]
                            )
                        )
                    )
                ).all()
            actions = sorted(event.action for event in events)
            assert actions == [
                "analysis_pipeline.gemini_transcription_prepared",
                "conversation.providers.gemini_transcription_on",
                "conversation.providers.gemini_transcription_on",
            ]
            for event in events:
                approval = event.payload["approval"]
                assert approval["approver"] == "Suyash Kulkarni (owner, relayed)"
                assert approval["issue"] == "AUT-2177"
            on = next(e for e in events if e.action.endswith("gemini_transcription_on"))
            assert on.payload["confirm"] == "one_pass" and on.payload["flex"] is True
            assert "hardcore backend commands" in on.payload["reason"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_commands() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--control-email", "x@y", "bogus"])
