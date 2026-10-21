"""scripts/data-changes/one-pass-flex-production.py on PostgreSQL (AUT-2177): prepare, switch
and back (Flex or standard) through the same service functions as Admin, dry run by default,
idempotent, refused unless the sealed approval contains the digest, audited with the owner's
approval. Fictional fixture only."""

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


async def _runner(setup: Any, unsealed: Any) -> Any:
    """``do(action, ...)``: one script command in its own transaction, committed only when
    applied, acting as the fixture's control account in its operations workspace."""
    from ac_platform.identity.models import Person

    async with setup.sessions() as db:
        email = (await db.get(Person, setup.actor.person_id)).email
    ops = setup.prepared.state.tenant_id

    async def do(
        action: str,
        *,
        apply: bool,
        digest: str | None = None,
        bundle: Any = None,
        tier: str = "flex",
    ) -> Any:
        command = script.Command(
            action=action,
            environment="test",
            control_email=email,
            apply=apply,
            digest=digest,
            tier=tier,
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

    return do


def test_prepare_switch_and_back_from_the_cli(postgres_harness: Any, tmp_path: Any) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=25
        )
        try:
            unsealed = _with_policy(setup)
            do = await _runner(setup, unsealed)

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


def test_the_standard_tier_from_flex_and_from_scribe(postgres_harness: Any, tmp_path: Any) -> None:
    """Owner, 21 Oct 2026: production on the standard (non-Flex) profile. Flex to standard
    needs no owner check in Admin, so the script's own event names the approval there; the
    pointer review follows the active configuration off Flex."""
    from ac_platform.conversation_intelligence.pointer_review_cli import _active_flex

    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=25
        )
        try:
            unsealed = _with_policy(setup)
            do = await _runner(setup, unsealed)

            async def review_on_flex() -> bool:
                async with setup.sessions() as db:
                    return bool(await db.run_sync(lambda sync: _active_flex(sync.connection())))

            classic = parse_registry_config(setup.config.as_dict())
            flex = c2_route.derive_configuration(classic, flex=True)
            standard = c2_route.derive_configuration(classic)
            assert flex.digest != standard.digest
            status = await do("status", apply=False)
            assert status["before"]["standard_digest"] == standard.digest
            assert status["before"]["standard_saved"] is None
            assert status["sealed"] == {"flex": False, "standard": False}
            flex_only = c2_route.seal(unsealed, classic, flex, flex=True)
            sealed = c2_route.seal(flex_only, classic, standard)
            assert (await do("status", apply=False, bundle=sealed))["sealed"] == {
                "flex": True,
                "standard": True,
            }
            assert (await do("prepare", apply=True))["status"] == "applied"
            prepared = await do("prepare", apply=True, tier="standard")
            assert prepared["status"] == "applied"
            assert prepared["after"]["standard_saved"]["configuration_sha256"] == standard.digest
            assert (await do("prepare", apply=True, tier="standard"))["status"] == "no_op"

            # Production today: Flex is active.
            await do("switch", apply=True, digest=flex.digest, bundle=sealed)
            assert await review_on_flex()
            with pytest.raises(script.Refused, match="standard_configuration_derived_from_today"):
                await do("switch", apply=True, tier="standard", digest=flex.digest, bundle=sealed)
            with pytest.raises(script.Refused, match="sealed_approval_does_not_contain"):
                await do(
                    "switch", apply=True, tier="standard", digest=standard.digest, bundle=flex_only
                )
            dry = await do(
                "switch", apply=False, tier="standard", digest=standard.digest, bundle=sealed
            )
            assert dry["status"] == "dry_run"
            assert dry["after"]["active"]["configuration_sha256"] == standard.digest
            assert await review_on_flex()  # the dry run changed nothing
            switched = await do(
                "switch", apply=True, tier="standard", digest=standard.digest, bundle=sealed
            )
            assert switched["status"] == "applied"
            assert switched["after"]["active"]["configuration_sha256"] == standard.digest
            assert switched["after"]["active"]["transcription"] == "gemini"
            assert not await review_on_flex()  # the pointer review is off Flex too
            assert (
                await do(
                    "switch", apply=True, tier="standard", digest=standard.digest, bundle=sealed
                )
            )["status"] == "no_op"
            # Back to Scribe, then straight onto standard: Admin's owner check applies.
            assert (await do("back", apply=True, bundle=sealed))["status"] == "applied"
            again = await do(
                "switch", apply=True, tier="standard", digest=standard.digest, bundle=sealed
            )
            assert again["status"] == "applied"
            assert not await review_on_flex()

            async with setup.sessions() as db:
                switches = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.action == script.SWITCHED))
                ).all()
                owner_checks = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "conversation.providers.gemini_transcription_on"
                        )
                    )
                ).all()
            assert sorted(event.payload["tier"] for event in switches) == [
                "flex",
                "standard",
                "standard",
            ]
            for event in switches:
                assert event.payload["approval"]["approver"] == "Suyash Kulkarni (owner, relayed)"
                assert event.payload["approval"]["issue"] == "AUT-2177"
                if event.payload["tier"] == "standard":
                    assert "standard (non-Flex) Gemini profile" in event.payload["reason"]
                    assert event.payload["configuration_sha256"] == standard.digest
            # Scribe to Flex and Scribe to standard; Flex to standard had no owner check.
            assert sorted(event.payload["flex"] for event in owner_checks) == [False, True]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_commands() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--control-email", "x@y", "bogus"])
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--control-email", "x@y", "--tier", "slow", "status"])
