"""Gemini 3.1 Flash-Lite as the sealed C2 route: the derived configuration, the bundle
that keeps every classic route, and the owner's gate on the switch. Fictional ids only."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import gemini_audio
from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.identity import sign_in_methods
from ac_platform.one_pass import c2_route
from tests.unit.conversation_intelligence.test_provider_activation import (
    _approved_bundle,
    _registry_config,
    _row,
)


def _classic() -> tuple[object, object]:
    config = _registry_config(
        "approved-gemini-base-v1", funded=True, text_provider="gemini", text_cost_paise=40
    )
    bundle = _approved_bundle(config, funded=True, text_provider="gemini", text_cost_paise=40)
    # Room for one more paid route in the project cap (as production's cap has).
    return config, bundle.model_copy(update={"budget_cap_paise": 1_000_000})


def test_the_derived_configuration_changes_only_the_transcription_route() -> None:
    classic, _ = _classic()
    new = c2_route.derive_configuration(classic)
    routes = {route.task: route for route in new.routes}
    assert (routes["asr"].provider_id, routes["asr"].model_id) == ("gemini", gemini_audio.MODEL)
    assert routes["asr"].recipe_revision == gemini_audio.RECIPE
    old = {route.task: route for route in classic.routes}
    assert routes["facts"] == old["facts"] and routes["coaching"] == old["coaching"]
    entry = next(item for item in new.providers if item.model_id == gemini_audio.MODEL)
    gemini = next(item for item in classic.providers if item.provider_id == "gemini")
    assert entry.credential_ref == gemini.credential_ref
    assert entry.privacy_ref == gemini.privacy_ref and entry.permission_ref == gemini.permission_ref
    assert entry.max_cost_paise == c2_route.MAX_COST_PAISE
    assert new.policy == classic.policy and new.digest != classic.digest
    with pytest.raises(c2_route.SealError, match="already_transcribes_on_gemini"):
        c2_route.derive_configuration(new)


def test_the_sealed_bundle_keeps_every_classic_route_and_approves_the_new_one() -> None:
    classic, bundle = _classic()
    new = c2_route.derive_configuration(classic)
    sealed = c2_route.seal(bundle, classic, new)
    policy, before = sealed.acquisition_policy, bundle.acquisition_policy
    assert policy is not None and before is not None
    assert policy.stages == before.stages  # every classic route kept
    assert [profile.profile_id for profile in policy.profiles] == [c2_route.PROFILE_ID]
    # Both configurations activate; only their C2 routes differ.
    old = ConversationProviderAdmin._approved_configuration(_row(classic), sealed)
    now = ConversationProviderAdmin._approved_configuration(_row(new), sealed)
    assert [(d.provider_id, d.model_id) for d in old][0] == ("elevenlabs", "scribe_v2")
    assert [(d.provider_id, d.model_id, d.max_cost_paise) for d in now][0] == (
        "gemini",
        gemini_audio.MODEL,
        c2_route.MAX_COST_PAISE,
    )
    assert [(d.provider_id, d.model_id) for d in now][1:] == [
        (d.provider_id, d.model_id) for d in old
    ][1:]
    # The file Root installs reads back as the same bundle; sealing again changes nothing.
    assert load_hosted_approval_bundle(sealed.to_json()).digest == sealed.digest
    assert c2_route.seal(sealed, classic, new).digest == sealed.digest
    # A bundle that does not approve the classic configuration is refused.
    other = _registry_config("other-v1", funded=True, text_provider="gemini", text_cost_paise=40)
    with pytest.raises(c2_route.SealError, match="does_not_approve_the_classic"):
        c2_route.seal(bundle, other, c2_route.derive_configuration(other))


class _Database:
    def __init__(self, current: object) -> None:
        self.current = current

    async def get(self, _model: object, _key: object) -> object:
        return self.current


def _admin(current_config: object | None) -> ConversationProviderAdmin:
    admin = ConversationProviderAdmin.__new__(ConversationProviderAdmin)
    admin.application = SimpleNamespace(clock=lambda: datetime.now(UTC))  # type: ignore[assignment]
    admin.database = _Database(None if current_config is None else _row(current_config))  # type: ignore[assignment]

    async def active(_tenant: object) -> object:
        return None if current_config is None else SimpleNamespace(configuration_id=uuid4())

    admin._active = active  # type: ignore[method-assign]
    return admin


@pytest.mark.asyncio
async def test_switching_transcription_to_gemini_is_the_owners_action(monkeypatch) -> None:
    classic, _ = _classic()
    new = c2_route.derive_configuration(classic)
    actor = SimpleNamespace(tenant_id=uuid4(), person_id=uuid4(), session_id=uuid4())
    fresh = {"value": True}

    async def is_fresh(_database: object, _session: object, _now: object) -> bool:
        return fresh["value"]

    monkeypatch.setattr(sign_in_methods, "session_is_fresh", is_fresh)
    admin = _admin(classic)
    reason = "Owner, 21 Oct: So at least get this on prod now"
    for confirm, said, words in (
        (None, reason, "Type one_pass"),
        ("yes", reason, "Type one_pass"),
        ("one_pass", "ok", "owner's words"),
    ):
        with pytest.raises(ConversationDenied, match=words):
            await admin._owner_gate(actor, _row(new), confirm=confirm, reason=said)
    fresh["value"] = False
    with pytest.raises(ConversationDenied, match="Sign in again"):
        await admin._owner_gate(actor, _row(new), confirm="one_pass", reason=reason)
    fresh["value"] = True
    assert await admin._owner_gate(actor, _row(new), confirm="one_pass", reason=reason)
    # Back to Scribe, or any other change, needs nothing more: the one-click fallback.
    assert not await _admin(new)._owner_gate(actor, _row(classic), confirm=None, reason=None)
    assert not await _admin(new)._owner_gate(actor, _row(new), confirm=None, reason=None)


def test_the_host_script_seals_only_the_derived_configuration(tmp_path, capsys) -> None:
    import json

    from scripts.ops import one_pass_c2_seal

    classic, bundle = _classic()
    derived = c2_route.derive_configuration(classic)
    (tmp_path / "bundle.json").write_bytes(bundle.to_json())
    (tmp_path / "classic.json").write_text(json.dumps(classic.as_dict()))
    (tmp_path / "gemini.json").write_text(json.dumps(derived.as_dict()))
    out = tmp_path / "out"
    arguments = [
        "--bundle",
        str(tmp_path / "bundle.json"),
        "--classic",
        str(tmp_path / "classic.json"),
        "--configuration",
        str(tmp_path / "gemini.json"),
        "--out",
        str(out),
    ]
    assert one_pass_c2_seal.main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    sealed = load_hosted_approval_bundle((out / "hosted-approval.json").read_bytes())
    assert (out / "hosted-approval.sha256").read_text().strip() == sealed.digest
    assert summary["bundle_after"] == sealed.digest != summary["bundle_before"]
    assert summary["gemini_c2_configuration"] == derived.digest
    # A configuration other than the derived one is never sealed.
    other = classic.as_dict()
    other["revision"] = "slipped-in"
    (tmp_path / "gemini.json").write_text(json.dumps(other))
    assert one_pass_c2_seal.main(arguments) == 2


def test_the_flex_configuration_and_profile_keep_standard_ceilings() -> None:
    classic, bundle = _classic()
    flex = c2_route.derive_configuration(classic, flex=True)
    routes = {route.task: route for route in flex.routes}
    assert routes["asr"].model_id == gemini_audio.MODEL + ":flex"
    assert routes["facts"].model_id == routes["coaching"].model_id == "gemini-3.8-flash:flex"
    standard = c2_route.derive_configuration(classic)
    sealed = c2_route.seal(c2_route.seal(bundle, classic, standard), classic, flex, flex=True)
    policy = sealed.acquisition_policy
    assert policy is not None and policy.stages == bundle.acquisition_policy.stages
    assert [p.profile_id for p in policy.profiles] == [
        c2_route.PROFILE_ID,
        c2_route.FLEX_PROFILE_ID,
    ]
    dispatches = ConversationProviderAdmin._approved_configuration(_row(flex), sealed)
    old = ConversationProviderAdmin._approved_configuration(_row(classic), sealed)
    assert [(d.model_id, d.max_cost_paise) for d in dispatches] == [
        (gemini_audio.MODEL + ":flex", c2_route.MAX_COST_PAISE),
        ("gemini-3.8-flash:flex", old[1].max_cost_paise),
        ("gemini-3.8-flash:flex", old[2].max_cost_paise),
    ]
    # Both Gemini configurations and the classic one stay activatable.
    assert ConversationProviderAdmin._approved_configuration(_row(standard), sealed)


@pytest.mark.asyncio
async def test_switching_to_flex_is_the_owners_action_and_back_is_one_click(monkeypatch) -> None:
    classic, _ = _classic()
    standard = c2_route.derive_configuration(classic)
    flex = c2_route.derive_configuration(classic, flex=True)
    actor = SimpleNamespace(tenant_id=uuid4(), person_id=uuid4(), session_id=uuid4())

    async def is_fresh(_database: object, _session: object, _now: object) -> bool:
        return True

    monkeypatch.setattr(sign_in_methods, "session_is_fresh", is_fresh)
    with pytest.raises(ConversationDenied, match="Type one_pass"):
        await _admin(standard)._owner_gate(actor, _row(flex), confirm=None, reason=None)
    assert await _admin(standard)._owner_gate(
        actor, _row(flex), confirm="one_pass", reason="Owner: Flex after the latency check"
    )
    assert not await _admin(flex)._owner_gate(actor, _row(standard), confirm=None, reason=None)
    assert not await _admin(flex)._owner_gate(actor, _row(classic), confirm=None, reason=None)


def test_the_one_pass_configuration_and_profile() -> None:
    from ac_platform.one_pass import markers

    classic, bundle = _classic()
    for flex in (False, True):
        one_pass = c2_route.derive_configuration(classic, flex=flex, one_pass=True)
        text_model = "gemini-3.8-flash" + (":flex" if flex else "")
        routes = {route.task: route for route in one_pass.routes}
        assert routes["asr"].model_id == gemini_audio.MODEL + (":flex" if flex else "")
        assert (routes["facts"].model_id, routes["facts"].recipe_revision) == (
            text_model,
            markers.RECIPE,
        )
        assert routes["facts"].prompt_revision == markers.PROMPT_REVISION
        old = {route.task: route for route in classic.routes}
        assert routes["coaching"].recipe_revision == old["coaching"].recipe_revision
        entry = next(item for item in one_pass.providers if item.model_id == text_model)
        assert entry.max_cost_paise == c2_route.ONE_PASS_MAX_COST_PAISE
        sealed = c2_route.seal(bundle, classic, one_pass, flex=flex, one_pass=True)
        policy, before = sealed.acquisition_policy, bundle.acquisition_policy
        assert policy is not None and before is not None
        assert policy.stages == before.stages  # every classic route kept
        (profile,) = policy.profiles
        assert profile.profile_id == (
            c2_route.ONE_PASS_FLEX_PROFILE_ID if flex else c2_route.ONE_PASS_PROFILE_ID
        )
        _, c4, c5 = profile.stages
        assert (c4.recipe_revision, c4.max_requests, c4.max_completion_tokens) == (
            markers.RECIPE,
            1,
            c2_route.ONE_PASS_COMPLETION_TOKENS,
        )
        assert c4.max_input_bytes >= markers.MAX_INPUT_BYTES
        assert c4.max_cost_paise == c5.max_cost_paise == c2_route.ONE_PASS_MAX_COST_PAISE
        assert c5.recipe_revision == before.stages[2].recipe_revision
        dispatches = ConversationProviderAdmin._approved_configuration(_row(one_pass), sealed)
        assert [(d.model_id, d.recipe_revision) for d in dispatches][1] == (
            text_model,
            markers.RECIPE,
        )
        # The classic configuration stays activatable: one click back.
        assert ConversationProviderAdmin._approved_configuration(_row(classic), sealed)
    # Today's profiles are unchanged by the one-pass option.
    standard = c2_route.derive_configuration(classic)
    assert standard.digest == c2_route.derive_configuration(classic, one_pass=False).digest


@pytest.mark.asyncio
async def test_switching_to_one_pass_is_the_owners_action_and_back_is_one_click(
    monkeypatch,
) -> None:
    classic, _ = _classic()
    standard = c2_route.derive_configuration(classic)
    one_pass = c2_route.derive_configuration(classic, one_pass=True)
    actor = SimpleNamespace(tenant_id=uuid4(), person_id=uuid4(), session_id=uuid4())

    async def is_fresh(_database: object, _session: object, _now: object) -> bool:
        return True

    monkeypatch.setattr(sign_in_methods, "session_is_fresh", is_fresh)
    with pytest.raises(ConversationDenied, match="Type one_pass"):
        await _admin(standard)._owner_gate(actor, _row(one_pass), confirm=None, reason=None)
    assert await _admin(standard)._owner_gate(
        actor, _row(one_pass), confirm="one_pass", reason="Owner, 21 Oct: build B now"
    )
    assert not await _admin(one_pass)._owner_gate(actor, _row(standard), confirm=None, reason=None)
    assert not await _admin(one_pass)._owner_gate(actor, _row(classic), confirm=None, reason=None)


GOVERNANCE = {
    "privacy_revision": "privacy-openai-20261021-v1",
    "privacy_notice": "Synthetic test notice: OpenAI processes this call under a signed DPA.",
    "retention_ref": "ref:retention/openai-zero",
    "professional_gate_ref": "ref:professional/openai-1",
}


def _with_openai(config: object) -> object:
    from dataclasses import replace

    from tests.database.test_conversation_authority_postgresql import _provider, _refs

    openai = replace(
        _provider("openai", "gpt-6-luna", c2_route.LUNA_ENDPOINT, max_cost_paise=40),
        **{key: value for key, value in _refs("openai", paid=True).items() if key != "pricing_ref"},
    )
    return replace(config, providers=(*config.providers, openai))


def test_the_luna_configuration_and_profile() -> None:
    from ac_platform.one_pass import markers

    classic, bundle = _classic()
    with pytest.raises(c2_route.SealError, match="no_openai_luna_provider"):
        c2_route.derive_configuration(classic, one_pass=True, luna=True)
    with pytest.raises(c2_route.SealError, match="luna_is_the_one_pass_route"):
        c2_route.derive_configuration(_with_openai(classic), luna=True)
    with_openai = _with_openai(classic)
    for flex in (False, True):
        luna = c2_route.derive_configuration(with_openai, flex=flex, one_pass=True, luna=True)
        model = "gpt-6-luna" + (":flex" if flex else "")
        routes = {route.task: route for route in luna.routes}
        assert routes["asr"].model_id == gemini_audio.MODEL + (":flex" if flex else "")
        assert (routes["facts"].provider_id, routes["facts"].model_id) == ("openai", model)
        assert routes["facts"].recipe_revision == markers.RECIPE
        assert (routes["coaching"].provider_id, routes["coaching"].model_id) == ("openai", model)
        entry = next(item for item in luna.providers if item.model_id == model)
        assert entry.max_cost_paise == c2_route.LUNA_MAX_COST_PAISE
        assert entry.credential_ref == "ref:credential:openai"
    # The classic bundle approves the Scribe configuration; the Luna profile needs Root's
    # OpenAI governance.
    with_bundle = bundle.model_copy(
        update={
            "acquisition_policy": bundle.acquisition_policy.model_copy(
                update={
                    "stages": tuple(
                        stage.model_copy(update={"configuration_sha256": with_openai.digest})
                        for stage in bundle.acquisition_policy.stages
                    )
                }
            )
        }
    )
    luna = c2_route.derive_configuration(with_openai, flex=True, one_pass=True, luna=True)
    with pytest.raises(c2_route.SealError, match="openai_governance"):
        c2_route.seal(with_bundle, with_openai, luna, flex=True, one_pass=True, luna={})
    sealed = c2_route.seal(
        with_bundle, with_openai, luna, flex=True, one_pass=True, luna=GOVERNANCE
    )
    (profile,) = sealed.acquisition_policy.profiles
    assert profile.profile_id == c2_route.LUNA_FLEX_PROFILE_ID
    _, c4, c5 = profile.stages
    assert (c4.provider_id, c4.model_id, c4.recipe_revision) == (
        "openai",
        "gpt-6-luna:flex",
        markers.RECIPE,
    )
    assert (c4.max_requests, c4.max_completion_tokens) == (1, c2_route.LUNA_COMPLETION_TOKENS)
    assert c5.provider_id == "openai" and c5.max_completion_tokens <= 8_000
    for stage in (c4, c5):
        assert stage.privacy_notice == GOVERNANCE["privacy_notice"]
        assert stage.retention_ref == GOVERNANCE["retention_ref"]
        assert stage.max_cost_paise == c2_route.LUNA_MAX_COST_PAISE
    assert ConversationProviderAdmin._approved_configuration(_row(luna), sealed)
    assert ConversationProviderAdmin._approved_configuration(_row(with_openai), sealed)


@pytest.mark.asyncio
async def test_switching_onto_openai_needs_the_owners_dpa_word(monkeypatch) -> None:
    classic, _ = _classic()
    with_openai = _with_openai(classic)
    standard = c2_route.derive_configuration(with_openai)
    luna = c2_route.derive_configuration(with_openai, one_pass=True, luna=True)
    actor = SimpleNamespace(tenant_id=uuid4(), person_id=uuid4(), session_id=uuid4())

    async def is_fresh(_database: object, _session: object, _now: object) -> bool:
        return True

    monkeypatch.setattr(sign_in_methods, "session_is_fresh", is_fresh)
    reason = "Owner, 21 Oct: I have signed the OpenAI DPA"
    with pytest.raises(ConversationDenied, match="openai_dpa_signed"):
        await _admin(standard)._owner_gate(actor, _row(luna), confirm="one_pass", reason=reason)
    assert await _admin(standard)._owner_gate(
        actor, _row(luna), confirm="openai_dpa_signed", reason=reason
    )
    # Off OpenAI again is one click.
    assert not await _admin(luna)._owner_gate(actor, _row(standard), confirm=None, reason=None)
