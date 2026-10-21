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
        **options: Any,
    ) -> Any:
        command = script.Command(
            action=action,
            environment="test",
            control_email=email,
            apply=apply,
            digest=digest,
            tier=tier,
            **options,
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


GOVERNANCE = {
    "privacy_revision": "privacy-openai-20261021-v1",
    "privacy_notice": "Synthetic test notice: OpenAI processes this call under a signed DPA.",
    "retention_ref": "ref:retention/openai-zero",
    "professional_gate_ref": "ref:professional/openai-1",
}
REFS = (
    ("credential_ref", "ref:credential/openai/v1"),
    ("permission_ref", "ref:permission/openai-real-calls-20261021"),
)


def test_luna_from_records_on_the_standard_tier_with_c5_on_gemini(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """Orchestrator, 21 Oct 2026: production on Luna (the one-pass C4 request) with C5 on
    Gemini, no owner clicks. The OpenAI entry is built from records inside the Luna
    configuration; today's classic configuration and its Gemini seals stay as they are."""
    from ac_platform.conversation_intelligence.provider_admin import OPENAI_DPA_CONFIRMED

    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=25
        )
        try:
            unsealed = _with_policy(setup)
            do = await _runner(setup, unsealed)
            luna = {"tier": "standard", "one_pass": True, "luna": True}

            # The references: the two not on record must be given; a benchmark one never.
            with pytest.raises(script.Refused, match="openai_refs_needed:credential_ref"):
                await do("prepare", apply=False, **luna)
            with pytest.raises(script.Refused, match="fictional_benchmark"):
                await do(
                    "prepare",
                    apply=False,
                    openai=(
                        REFS[0],
                        ("permission_ref", "ref:permission/openai-fictional-benchmark-20260925"),
                    ),
                    **luna,
                )
            with pytest.raises(script.Refused, match="luna_is_the_one_pass_route"):
                await do("status", apply=False, luna=True, openai=REFS)
            status = await do("status", apply=False, openai=REFS, **luna)
            digest = status["before"]["luna_c4_digest"]
            standard = status["before"]["standard_digest"]
            assert digest not in (None, standard)
            assert status["sealed"]["luna_c4"] is False
            assert status["before"]["openai_entries"] == []

            prepared = await do("prepare", apply=True, openai=REFS, **luna)
            assert prepared["status"] == "applied"
            assert prepared["after"]["luna_c4_saved"]["configuration_sha256"] == digest
            # The classic configuration and the standard Gemini one derive as before.
            assert prepared["after"]["classic"] == status["before"]["classic"]
            assert prepared["after"]["standard_digest"] == standard
            (entry,) = prepared["after"]["openai_entries"]
            assert entry["credential_ref"] == "ref:credential/openai/v1"
            assert entry["permission_ref"] == "ref:permission/openai-real-calls-20261021"
            assert entry["provider_terms_ref"] == script.OPENAI_RECORDS["provider_terms_ref"]
            exported = await do("export", apply=False, openai=REFS, **luna, export="target")
            saved = parse_registry_config(exported["configuration"])
            routes = {route.task: (route.provider_id, route.model_id) for route in saved.routes}
            assert routes["facts"] == ("openai", "gpt-6-luna")
            assert routes["coaching"][0] == "gemini"

            # Sealed as Root seals it (the entry taken from the saved configuration).
            classic = parse_registry_config(setup.config.as_dict())
            openai = next(item for item in saved.providers if item.provider_id == "openai")
            derived = c2_route.derive_configuration(
                classic, one_pass=True, luna=True, openai=openai, luna_report=False
            )
            assert derived.digest == digest
            with pytest.raises(script.Refused, match="sealed_approval_does_not_contain"):
                await do("switch", apply=True, digest=digest, openai=REFS, **luna)
            sealed = c2_route.seal(
                unsealed,
                classic,
                derived,
                one_pass=True,
                luna=GOVERNANCE,
                luna_report=False,
            )
            switched = await do(
                "switch", apply=True, digest=digest, bundle=sealed, openai=REFS, **luna
            )
            assert switched["status"] == "applied"
            assert switched["after"]["active"]["configuration_sha256"] == digest
            again = await do(
                "switch", apply=True, digest=digest, bundle=sealed, openai=REFS, **luna
            )
            assert again["status"] == "no_op"
            # Back to Scribe is the one-click fallback, as before.
            assert (await do("back", apply=True, bundle=sealed))["status"] == "applied"

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action.in_(
                                [
                                    script.SWITCHED,
                                    OPENAI_DPA_CONFIRMED,
                                    "conversation.providers.gemini_transcription_on",
                                ]
                            )
                        )
                    )
                ).all()
            actions = sorted(event.action for event in events)
            assert actions == [
                "conversation.providers.gemini_transcription_on",
                OPENAI_DPA_CONFIRMED,
                script.SWITCHED,
            ]
            on = next(e for e in events if e.action.endswith("gemini_transcription_on"))
            assert on.payload["confirm"] == "openai_dpa_signed" and on.payload["openai"] is True
            switch = next(e for e in events if e.action == script.SWITCHED)
            assert switch.payload["variant"] == "luna_c4" and switch.payload["tier"] == "standard"
            assert "OpenAI DPA" in switch.payload["reason"]
            assert switch.payload["approval"]["issue"] == "AUT-2177"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_commands() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--control-email", "x@y", "bogus"])
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--control-email", "x@y", "--tier", "slow", "status"])


def test_each_switch_carries_the_owners_own_words() -> None:
    base = {"action": "prepare", "environment": "test", "control_email": "x@y"}
    assert script.Command(**base, tier="standard").words == script.STANDARD_REASON
    one_pass = script.Command(**base, tier="standard", one_pass=True)
    assert one_pass.words == script.ONE_PASS_REASON and one_pass.variant == "one_pass"
    assert "Gemini one-pass on standard after v0.76" in script.ONE_PASS_REASON
    assert "Keep Luna sealed and ready but off." in script.ONE_PASS_REASON
    assert script.Command(**base, one_pass=True, luna=True).words == script.LUNA_REASON
    given = "Owner, 22 Oct 2026: other words"
    assert script.Command(**base, one_pass=True, reason=given).words == given
    # A reason too short to be the owner's words is refused before anything runs.
    arguments = ["--environment", "test", "--control-email", "x@y", "--reason", "ok", "status"]
    assert script.main(arguments) == 2
