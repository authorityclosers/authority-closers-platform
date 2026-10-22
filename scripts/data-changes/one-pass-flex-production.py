#!/usr/bin/env python3
"""Prepare, switch and switch back the Gemini Flash-Lite C2 provider configuration (Flex or
standard), from the CLI.

Owner order, 21 Oct 2026 (AUT-2177, relayed by the orchestrator): "Don't make me do this,
do this using hardcore backend commands and CLI, I need this to be live very very quick and
done properly now." His message is the approval for both production actions that Admin ->
One pass -> Transcription would otherwise take: Prepare (save the configuration as a
provider revision) and Switch (activate it once Root has sealed it). Owner order, 21 Oct
2026 (relayed): "Switch production to the standard (non-Flex) Gemini profile: about
₹0.64/min, reports in about 1 minute (add the standard prepare to the script)." Owner-
approved data change (AGENTS.md, OWNER-APPROVED DATA CHANGES): dry run by default, before
and after printed, one transaction, idempotent, audited with the approver and the issue.

``--tier flex`` (the default) is the Flex configuration (profile
``gemini-flash-lite-c2-flex``); ``--tier standard`` is the standard one (profile
``gemini-flash-lite-c2``): the same Flash-Lite C2 and Gemini 3.8 Flash C4/C5, without Flex.

``--one-pass`` makes the facts route the one-pass C4 request (profiles ``gemini-one-pass``,
``-flex``; owner, 21 Oct 2026, relayed: "Switch production to Gemini one-pass on standard
after v0.76 ... Keep Luna sealed and ready but off."). ``--one-pass --luna`` puts that
request on OpenAI GPT-6 Luna (owner, 21 Oct 2026: "build B together with the Luna route";
"Yes, I have signed the OpenAI DPA for Authority Closers"); ``--report-on gemini`` (the
default, the hybrid the orchestrator chose on the real-call trial: Luna's own coaching read
worse) keeps C5 on Gemini 3.8 Flash (profiles ``luna-c4-one-pass``, ``-flex``),
``--report-on luna`` moves C5 to Luna too (``luna-one-pass``, ``-flex``). Luna's provider
entry is built from existing records only and lives in the Luna configuration itself, so
today's classic configuration, its sealed Gemini profiles and the ``back`` fallback stay
exactly as they are: ``--openai-credential-ref`` (the hosted service manifest's OpenAI
credential, AUT-2179) and ``--openai-permission-ref`` (the real-call processing permission)
must be given; the terms, privacy and endpoint approval references default to those the
OpenAI C5 adapter's entry already carries (25 Sep 2026); a fictional-benchmark permission is
refused. When the classic configuration already carries a GPT-6 Luna entry, that one is used
and none may be given. Switching onto OpenAI asks Admin's OpenAI word
(``openai_dpa_signed``: the owner confirmed the DPA).

``--brain4`` (with ``--one-pass``; P1, orchestrator 22 Oct 2026) makes that request recipe
v2, the same read plus the Brain 4.0 part (``one_pass.brain4_part``), on its own profiles
(``gemini-one-pass-v2``, ``luna-c4-one-pass-v2``, each with ``-flex``) and variants
(``one_pass_v2[_flex]``, ``luna_c4_v2[_flex]``). No owner words are recorded for it yet, so
prepare and switch need ``--reason`` with the owner's words, verbatim.

It calls the same service functions as the Admin actions, nothing reimplemented:

- ``prepare``: ``c2_route.derive_configuration(classic, flex=<tier is flex>)`` from today's
  Scribe configuration, saved through ``ConversationProviderAdmin.save``, with Admin's
  audit event ``analysis_pipeline.gemini_transcription_prepared``. Prints the configuration
  digest and the provider revision Root exports for the seal (``export``, below). Already
  saved: nothing more.
- ``switch --digest D``: ``ConversationProviderAdmin.activate`` of that saved revision,
  with the owner's confirm word and his words as the reason. Refused unless D is the
  configuration of that tier derived from today's classic one AND the deployment's pinned
  approval bundle (``load_pinned_approval``, the host's sealed file) approves it. Audited
  as the Admin switch is (the ``provider_activation`` receipt, and
  ``conversation.providers.gemini_transcription_on`` when the owner's check applies:
  onto Gemini or onto Flex), plus ``conversation.providers.owner_approved_switch`` on
  every switch, carrying the approval (Flex to standard needs no owner check in Admin, so
  this is the event that names the owner there). Already active: nothing more. The pointer
  review follows: it reads the newest activation on every pass (``_active_flex``).
- ``back``: the classic (Scribe) revision activated again, the one-click fallback; no
  owner check, as in Admin. Already active: nothing more.
- ``status`` (read only: both tiers' digests, saved revisions, and whether the pinned
  approval seals each) and ``export classic|flex|standard`` (read only: the saved
  configuration's JSON, the ``--classic`` and ``--configuration`` files for
  scripts/ops/one_pass_c2_seal.py).

Who acts: the AC control account named by ``--control-email`` (one of the provider
control accounts), through its newest current Admin session in the operations workspace.
The script never reads or prints a session token; it uses that session row as the actor's
session, exactly as an Admin request would. The owner's relayed approval stands in only
for the ten-minute fresh sign-in; the confirm word and the reason still apply. No current
session: refused (sign in to Admin once; no button needed).

Run inside the deployed API container (the baked package provides ac_platform and the
container's environment the database URL, operations tenant and approval file):

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --control-email <control account> status \\
      < scripts/data-changes/one-pass-flex-production.py

    ... prepare [--tier standard] [--apply]
    ... export classic > classic-configuration.json      (Root, for the seal)
    ... export flex > gemini-flex-configuration.json
    ... export standard > gemini-standard-configuration.json
    ... switch [--tier standard] --digest <digest> [--apply]  (after Root's seal is deployed)
    ... back [--apply]                                     (the fallback)

    ... --tier standard --one-pass --luna --openai-credential-ref R1 \\
          --openai-permission-ref R2 prepare [--apply]
    ... (the same options) export target > luna-configuration.json   (Root, for the seal)
    ... (the same options) switch --digest <digest> [--apply]

On production: take a database snapshot before ``--apply``, show the owner the dry run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

APPROVER = "Suyash Kulkarni (owner, relayed)"
ISSUE = "AUT-2177"
REASON = (
    'Owner, 21 Oct 2026: "So at least get this on prod now!!!" and "Don\'t make me do this, '
    "do this using hardcore backend commands and CLI, I need this to be live very very quick "
    'and done properly now."'
)
STANDARD_REASON = (
    'Owner, 21 Oct 2026 (relayed): "Switch production to the standard (non-Flex) Gemini '
    "profile: about ₹0.64/min, reports in about 1 minute (add the standard prepare to "
    'the script)."'
)
REASONS = {"flex": REASON, "standard": STANDARD_REASON}
LUNA_REASON = (
    'Owner, 21 Oct 2026: "build B together with the Luna route (one-pass in the sealed plan, '
    'beta-labelled calibrated scores, call data written in production)" and (relayed) "Yes, '
    'I have signed the OpenAI DPA for Authority Closers".'
)
ONE_PASS_REASON = (
    "Owner, 21 Oct 2026 (relayed): "  # noqa: S105 - the owner's words, not a secret
    '"Switch production to Gemini one-pass on standard after v0.76 (about ₹0.39–0.43/min, '
    'reports in about 1 minute). Keep Luna sealed and ready but off."'
)
TIERS = ("flex", "standard")
# The references the OpenAI C5 adapter's provider entry already carries (25 Sep 2026); its
# permission was for fictional benchmark calls only, so the real-call one must be given.
OPENAI_RECORDS = {
    "provider_terms_ref": "ref:provider-terms/openai-api-20260925",
    "privacy_ref": "ref:privacy/openai-api-20260925",
    "endpoint_approval_ref": "ref:approval/openai-responses-20260925",
}
OPENAI_REQUIRED = ("credential_ref", "permission_ref")
DATA_CHANGE = "scripts/data-changes/one-pass-flex-production.py"
OPERATOR = "claude-laptop:one-pass-flex-production"
PREPARED = "analysis_pipeline.gemini_transcription_prepared"
SWITCHED = "conversation.providers.owner_approved_switch"
COMMANDS = ("status", "prepare", "switch", "back", "export")


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


@dataclass(frozen=True)
class Command:
    action: str
    environment: str
    control_email: str
    apply: bool = False
    digest: str | None = None
    export: str | None = None
    tier: str = "flex"
    one_pass: bool = False
    luna: bool = False
    report_on: str = "gemini"
    brain4: bool = False  # recipe v2: the one-pass request plus the Brain 4.0 part
    openai: tuple[tuple[str, str], ...] = ()  # the Luna entry's references, given
    approver: str = APPROVER
    issue: str = ISSUE
    reason: str | None = None  # the owner's words for this switch, verbatim (--reason)

    @property
    def variant(self) -> str:
        """standard, flex, one_pass[_flex], luna_c4[_flex] (C5 on Gemini) or luna[_flex];
        with --brain4, ``_v2`` after the base (one_pass_v2_flex)."""
        if not self.one_pass:
            return self.tier
        base = ("luna_c4" if self.report_on == "gemini" else "luna") if self.luna else "one_pass"
        return base + ("_v2" if self.brain4 else "") + ("_flex" if self.tier == "flex" else "")

    @property
    def words(self) -> str:
        if self.reason:
            return self.reason
        if self.luna:
            return LUNA_REASON
        return ONE_PASS_REASON if self.one_pass else REASONS[self.tier]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="one-pass-flex-production", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tier", choices=TIERS, default="flex")
    parser.add_argument("--one-pass", action="store_true")
    parser.add_argument("--luna", action="store_true")
    parser.add_argument("--report-on", choices=("gemini", "luna"), default="gemini")
    parser.add_argument("--brain4", action="store_true")
    for field in (*OPENAI_REQUIRED, *OPENAI_RECORDS):
        parser.add_argument("--openai-" + field.removesuffix("_ref").replace("_", "-") + "-ref")
    parser.add_argument("action", choices=COMMANDS)
    parser.add_argument("what", nargs="?", choices=("classic", *TIERS, "target"))
    parser.add_argument("--digest")
    parser.add_argument(
        "--reason", help="the owner's words for this change, verbatim (else the recorded ones)"
    )
    return parser


def _openai_entry(command: Command, classic: Any) -> Any:
    """The GPT-6 Luna provider entry for a Luna configuration: None when the classic
    configuration carries one (it is used as it is), else built from the given references
    and the records above; pricing and ceiling are the code's own (c2_route)."""
    import hashlib

    from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
    from ac_platform.conversation_intelligence.provider_registry import ProviderConfig
    from ac_platform.one_pass import c2_route

    given = dict(command.openai)
    existing = next(
        (
            item
            for item in classic.providers
            if (item.provider_id, item.model_id) == ("openai", c2_route.LUNA_MODEL)
        ),
        None,
    )
    if existing is not None:
        if given:
            raise Refused("the_classic_configuration_already_has_a_luna_entry_give_no_refs")
        entry = existing
    else:
        missing = [field for field in OPENAI_REQUIRED if not given.get(field)]
        if missing:
            raise Refused("openai_refs_needed:" + ",".join(missing))
        refs = {**OPENAI_RECORDS, **given}
        if any(not str(value).startswith("ref:") for value in refs.values()):
            raise Refused("openai_refs_must_be_ref_strings")
        endpoint = c2_route.LUNA_ENDPOINT
        entry = ProviderConfig(
            provider_id="openai",
            model_id=c2_route.LUNA_MODEL,
            endpoint=endpoint,
            endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
            credential_ref=refs["credential_ref"],
            provider_terms_ref=refs["provider_terms_ref"],
            privacy_ref=refs["privacy_ref"],
            pricing_ref=PRICING_SNAPSHOTS[("openai", c2_route.LUNA_MODEL)].pricing_ref,
            free_allowance_ref=None,
            permission_ref=refs["permission_ref"],
            endpoint_approval_ref=refs["endpoint_approval_ref"],
            local_endpoint_approval_ref=None,
            max_cost_paise=c2_route.LUNA_MAX_COST_PAISE,
        )
    if "fictional" in str(entry.permission_ref or "") or "benchmark" in str(
        entry.permission_ref or ""
    ):
        raise Refused("a_fictional_benchmark_permission_never_covers_real_calls")
    return None if existing is not None else entry


def _approval(command: Command) -> dict[str, str]:
    return {
        "approver": command.approver,
        "issue": command.issue,
        "data_change": DATA_CHANGE,
        "operator": OPERATOR,
    }


def _derive(command: Command, classic: Any, variant: str) -> Any:
    from ac_platform.one_pass import c2_route, markers

    flex = variant.endswith("flex")
    if variant in TIERS:
        return c2_route.derive_configuration(classic, flex=flex)
    luna = variant.startswith("luna")
    return c2_route.derive_configuration(
        classic,
        flex=flex,
        one_pass=True,
        luna=luna,
        openai=_openai_entry(command, classic) if luna else None,
        luna_report=not variant.startswith("luna_c4"),
        recipe=markers.RECIPE_V2 if "_v2" in variant else markers.RECIPE,
    )


async def _actor(database: Any, command: Command, operations_tenant_id: UUID) -> Any:
    """The control account's newest current Admin session in the operations workspace."""
    from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNTS
    from ac_platform.identity.models import Person
    from ac_platform.identity.models import Session as IdentitySession
    from ac_platform.kernel.authz import ActorContext

    email = command.control_email.strip().casefold()
    if email not in CONTROL_ACCOUNTS:
        raise Refused("control_email_is_not_a_provider_control_account")
    people = list(await database.scalars(select(Person).where(Person.email.ilike(email)).limit(2)))
    if len(people) != 1:
        raise Refused("exactly_one_person_must_match_the_control_email")
    now = datetime.now(UTC)
    session = await database.scalar(
        select(IdentitySession)
        .where(
            IdentitySession.person_id == people[0].id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.expires_at > now,
            IdentitySession.selected_tenant_id == operations_tenant_id,
        )
        .order_by(IdentitySession.created_at.desc())
        .limit(1)
    )
    if session is None:
        raise Refused("no_current_admin_session_sign_in_to_admin_once")
    return ActorContext(
        person_id=people[0].id,
        session_id=session.id,
        tenant_id=operations_tenant_id,
        permissions=frozenset({"admin_surface"}),
    )


async def _rows(database: Any, tenant_id: UUID) -> dict[int, Any]:
    from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration

    rows = (
        await database.scalars(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(64)
        )
    ).all()
    return {row.revision: row for row in rows}


def _transcription(row: Any) -> str | None:
    from ac_platform.conversation_intelligence.provider_registry import parse_registry_config

    try:
        config = parse_registry_config(row.configuration)
    except (TypeError, ValueError, KeyError):
        return None
    route = next((item for item in config.routes if item.task == "asr"), None)
    return None if route is None else route.provider_id


async def _state(
    database: Any, actor: Any, service: Any, command: Command | None = None
) -> dict[str, Any]:
    """Today's classic configuration, the Flex and standard ones derived from it and the
    command's own variant (one pass, Luna; with their saved revisions, if any), and what is
    active."""
    from ac_platform.conversation_intelligence.provider_registry import parse_registry_config

    rows = await _rows(database, actor.tenant_id)
    active_id = await service._active(actor.tenant_id)
    active = (
        None
        if active_id is None
        else next((row for row in rows.values() if row.id == active_id.configuration_id), None)
    )
    classic = (
        active
        if active is not None and _transcription(active) not in (None, "gemini")
        else next(
            (
                row
                for _, row in sorted(rows.items(), reverse=True)
                if _transcription(row) not in (None, "gemini")
            ),
            None,
        )
    )
    variants = list(TIERS)
    if command is not None and command.variant not in variants:
        variants.append(command.variant)
    derived: dict[str, Any] = {}
    if classic is not None:
        config = parse_registry_config(classic.configuration)
        for variant in variants:
            derived[variant] = _derive(command or Command("status", "", ""), config, variant)
    saved = {
        variant: next(
            (
                row
                for _, row in sorted(rows.items(), reverse=True)
                if variant in derived and row.configuration_sha256 == derived[variant].digest
            ),
            None,
        )
        for variant in variants
    }
    return {
        "rows": rows,
        "latest_revision": max(rows) if rows else 0,
        # Each activation is its own receipt key, so back and forth always acts.
        "activation": "none" if active_id is None else str(active_id.id),
        "active": active,
        "classic": classic,
        "derived": derived,
        "saved": saved,
    }


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    def row(item: Any) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "revision": item.revision,
            "provider_revision_id": str(item.id),
            "configuration_sha256": item.configuration_sha256,
            "transcription": _transcription(item),
        }

    derived = state["derived"]
    summary: dict[str, Any] = {
        "active": row(state["active"]),
        "classic": row(state["classic"]),
        "latest_revision": state["latest_revision"],
    }
    for variant in state["saved"]:
        summary[f"{variant}_saved"] = row(state["saved"][variant])
        summary[f"{variant}_digest"] = derived[variant].digest if variant in derived else None
    # Every OpenAI provider entry saved here, references only (the records Root checks).
    entries = {
        json.dumps(
            {
                key: value
                for key, value in sorted(item.items())
                if key == "model_id" or key.endswith("_ref")
            },
            sort_keys=True,
        )
        for config in (row.configuration for row in state["rows"].values())
        if isinstance(config, dict)
        for item in config.get("providers") or []
        if isinstance(item, dict) and item.get("provider_id") == "openai"
    }
    summary["openai_entries"] = [json.loads(item) for item in sorted(entries)]
    return summary


def _sealed(state: dict[str, Any], tenant_id: UUID, bundle: Any) -> dict[str, bool]:
    """Whether the pinned approval approves each tier's derived configuration, checked as
    the activation checks it (a transient row; nothing is saved)."""
    from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
    from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin

    result: dict[str, bool] = {}
    for tier, derived in state["derived"].items():
        row = state["saved"][tier] or ConversationProviderConfiguration(
            tenant_id=tenant_id,
            revision=0,
            configuration=derived.as_dict(),
            configuration_sha256=derived.digest,
        )
        try:
            ConversationProviderAdmin._approved_configuration(row, bundle)
        except Exception:  # noqa: BLE001 - any refusal means: not in the sealed file
            result[tier] = False
        else:
            result[tier] = True
    return result


def _governance_draft(state: dict[str, Any], bundle: Any) -> dict[str, Any]:
    """A draft of Root's ``--openai-governance`` JSON from the existing records only: the
    pinned approval's own values for today's classic C4 stage (privacy revision, notice,
    retention and professional gate). Root verifies it; when the notice does not name
    OpenAI, the OpenAI stage needs a notice that does, which is Root's and the owner's
    wording, never this script's."""
    from ac_platform.one_pass import c2_route

    classic = state["classic"]
    if classic is None:
        return {"refused": "no_classic_configuration"}
    policies = [
        *(() if bundle.acquisition_policy is None else (bundle.acquisition_policy,)),
        *bundle.organisation_acquisition_policies,
    ]
    drafts = []
    for policy in policies:
        for stages in policy.stage_sets():
            if {item.configuration_sha256 for item in stages} == {classic.configuration_sha256}:
                c4 = next(item for item in stages if item.stage == "C4")
                drafts.append(
                    {field: getattr(c4, field) for field in c2_route.LUNA_GOVERNANCE_FIELDS}
                )
    if not drafts:
        return {"refused": "the_pinned_approval_does_not_approve_the_classic_configuration"}
    draft = drafts[0]
    return {
        "governance": draft,
        "notice_names_openai": "openai" in str(draft["privacy_notice"]).casefold(),
        "same_in_every_policy": all(item == draft for item in drafts),
        "policies": len(drafts),
    }


async def execute(
    database: Any,
    command: Command,
    *,
    operations_tenant_id: UUID,
    load_bundle: Callable[[], Any],
    clock: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """One command in the caller's transaction (the caller commits only with --apply)."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.conversation_intelligence.application import ConversationApplication
    from ac_platform.conversation_intelligence.provider_admin import (
        OPENAI_CONFIRM_WORD,
        OWNER_CONFIRM_WORD,
        ConversationProviderAdmin,
    )

    tier = command.tier
    if tier not in TIERS:
        raise Refused("tier_must_be_flex_or_standard")
    if command.luna and not command.one_pass:
        raise Refused("luna_is_the_one_pass_route_add_one_pass")
    if command.openai and not command.luna:
        raise Refused("openai_refs_are_for_luna_only")
    if command.brain4 and not command.one_pass:
        raise Refused("brain4_is_the_one_pass_request_add_one_pass")
    if command.brain4 and command.action in {"prepare", "switch"} and not command.reason:
        raise Refused("brain4_needs_the_owners_words_reason")
    actor = await _actor(database, command, operations_tenant_id)
    application = (
        ConversationApplication(database)
        if clock is None
        else ConversationApplication(database, clock=clock)
    )
    service = ConversationProviderAdmin(application)
    state = await _state(database, actor, service, command)
    before = _summary(state)
    result: dict[str, Any] = {"action": command.action, "apply": command.apply, "before": before}
    if command.action == "status":
        governance: Any = None
        try:
            bundle = load_bundle()
            sealed: Any = _sealed(state, actor.tenant_id, bundle)
            if command.luna:
                governance = _governance_draft(state, bundle)
        except Exception as error:  # noqa: BLE001 - no pinned approval here: say which
            sealed = f"approval_unreadable:{type(error).__name__}"
        return {
            **result,
            "after": before,
            "sealed": sealed,
            **({"openai_governance_draft": governance} if command.luna else {}),
            "status": "read_only",
        }
    variant = command.variant
    if command.action == "export":
        name = variant if command.export == "target" else command.export
        item = state["classic"] if name == "classic" else state["saved"].get(name or "")
        if item is None:
            raise Refused(f"no_saved_{name}_configuration")
        return {"export": name, "configuration": item.configuration}
    if state["classic"] is None or not state["derived"]:
        raise Refused("no_classic_scribe_configuration_to_start_from")
    derived, saved = state["derived"][variant], state["saved"][variant]

    if command.action == "prepare":
        if saved is not None:
            status = "no_op"
        else:
            await service.save(
                actor,
                derived.as_dict(),
                expected_revision=state["latest_revision"],
                key=f"one-pass-c2:{derived.digest}",
            )
            await AuditRepository(database).append_for_actor(
                actor,
                action=PREPARED,
                resource_type="conversation_provider_configuration",
                resource_id=derived.digest,
                payload={
                    "from_revision": state["classic"].revision,
                    "configuration_sha256": derived.digest,
                    "tier": tier,
                    "variant": variant,
                    "reason": command.words,
                    "approval": _approval(command),
                },
            )
            status = "applied" if command.apply else "dry_run"
    elif command.action == "switch":
        if command.digest is None or command.digest != derived.digest:
            raise Refused(f"digest_is_not_the_{variant}_configuration_derived_from_today")
        if saved is None:
            raise Refused(f"{variant}_configuration_not_prepared_run_prepare_first")
        bundle = load_bundle()
        try:
            ConversationProviderAdmin._approved_configuration(saved, bundle)
        except Exception:  # noqa: BLE001 - any refusal means: not in the sealed file
            raise Refused("the_pinned_sealed_approval_does_not_contain_this_digest") from None
        if state["active"] is not None and state["active"].id == saved.id:
            status = "no_op"
        else:
            # Onto OpenAI, Admin's word confirms the owner signed its DPA.
            onto_openai = ConversationProviderAdmin._uses_openai(
                saved
            ) and not ConversationProviderAdmin._uses_openai(state["active"])
            await service.activate(
                actor,
                target_revision=saved.revision,
                expected_revision=state["latest_revision"],
                key=f"one-pass-{variant}-switch:{saved.configuration_sha256[:24]}:"
                f"{state['activation']}",
                bundle=bundle,
                confirm=OPENAI_CONFIRM_WORD if onto_openai else OWNER_CONFIRM_WORD,
                reason=command.words,
                owner_approval=_approval(command),
            )
            # Admin's owner check (and its audit event) applies only onto Gemini or onto
            # Flex; this names the owner's approval on every switch, Flex to standard too.
            await AuditRepository(database).append_for_actor(
                actor,
                action=SWITCHED,
                resource_type="conversation_provider_configuration",
                resource_id=saved.configuration_sha256,
                payload={
                    "tier": tier,
                    "variant": variant,
                    "target_revision": saved.revision,
                    "configuration_sha256": saved.configuration_sha256,
                    "from_configuration_sha256": None
                    if state["active"] is None
                    else state["active"].configuration_sha256,
                    "approval_bundle_sha256": bundle.digest,
                    "reason": command.words,
                    "approval": _approval(command),
                },
            )
            status = "applied" if command.apply else "dry_run"
    elif command.action == "back":
        classic = state["classic"]
        if state["active"] is not None and state["active"].id == classic.id:
            status = "no_op"
        else:
            bundle = load_bundle()
            await service.activate(
                actor,
                target_revision=classic.revision,
                expected_revision=state["latest_revision"],
                key=f"one-pass-back-to-scribe:{classic.configuration_sha256[:24]}:"
                f"{state['activation']}",
                bundle=bundle,
            )
            status = "applied" if command.apply else "dry_run"
    else:
        raise Refused("unknown_command")
    after = _summary(await _state(database, actor, service, command))
    return {**result, "after": after, "status": status, "approval": _approval(command)}


class _DryRun(Exception):
    pass


async def _run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, Any] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute(
                        db,
                        command,
                        operations_tenant_id=settings.operations_tenant_id,
                        load_bundle=lambda: load_pinned_approval(settings),
                    )
                    if not command.apply:
                        raise _DryRun
            except _DryRun:
                pass
        return result
    finally:
        await engine.dispose()


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.action == "export" and args.what is None:
            raise Refused("export_needs_classic_flex_standard_or_target")
        command = Command(
            action=args.action,
            environment=args.environment,
            control_email=args.control_email,
            apply=bool(args.apply) and args.action not in {"status", "export"},
            digest=args.digest,
            export=args.what,
            tier=args.tier,
            one_pass=bool(args.one_pass),
            luna=bool(args.luna),
            report_on=args.report_on,
            brain4=bool(args.brain4),
            reason=args.reason,
            openai=tuple(
                (field, value)
                for field in (*OPENAI_REQUIRED, *OPENAI_RECORDS)
                if (value := getattr(args, "openai_" + field))
            ),
        )
        if command.reason is not None and len(command.reason.strip()) < 10:
            raise Refused("reason_must_be_the_owners_words")
        from ac_platform.application.asyncio_runtime import run_async
        from ac_platform.application.release_identity import require_baked_release_id
        from ac_platform.application.settings import Settings

        settings = Settings(_env_file=None)
        if command.environment != settings.environment:
            raise Refused("environment_must_match_the_container_settings")
        if command.environment == "production" and not args.allow_production:
            raise Refused("production_requires_allow_production")
        if settings.operations_tenant_id is None:
            raise Refused("an_explicit_operations_tenant_is_required")
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        result = run_async((runner or _run)(command, settings))
    except Refused as refused:
        print(f"data change refused: {refused}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as error:
        # Settings and driver failures can contain secrets; name the type only.
        print(f"data change failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
