"""Explicit hosted reporting composition; constructing it never starts a worker.

The API and reporting workers share the same pinned approval and private object
store. The caller supplies reviewed, non-secret Infisical launch references.
Native sandbox invocation and service scheduling remain separate composition
responsibilities; this module cannot activate the local proof importer.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.hosted_runtime import (
    HostedConversationSettings,
    compose_hosted_intake,
)
from ac_platform.conversation_intelligence.inference_broker import (
    InfisicalLauncher,
    ProcessInferenceBroker,
)
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage


@dataclass(frozen=True)
class HostedReportingRuntime:
    authority: ConversationAuthority
    storage: PrivateLocalRecordingStorage
    inference: ConversationInferenceWorker
    plans: ProcessingPlanScheduler
    retention: ConversationRetentionScheduler


def compose_hosted_reporting(
    settings: HostedConversationSettings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    launchers: Mapping[str, InfisicalLauncher],
    python_executable: str | Path = sys.executable,
) -> HostedReportingRuntime | None:
    """Bind exact approval credential references to separate provider children.

    ``launchers`` keys are opaque credential references from the approved bundle,
    not key values. Each provider currently has one release-owned credential
    mapping. No user input, alternate command, arbitrary provider URL, direct
    in-process transport or automatic fallback is accepted here.

    Inference performs the database-backed admin/owner/session/quote check just
    before dispatch. The router independently reloads the pinned approval at its
    child boundary. A changed artifact cannot be used by an already-created runtime.
    """
    intake = compose_hosted_intake(settings)
    if intake is None:
        return None
    authority = intake.authority
    if authority is None:
        raise ValueError("hosted_reporting_authority_required")
    bundle = authority.current(datetime.now(UTC))
    if not isinstance(launchers, Mapping):
        raise ValueError("hosted_reporting_launchers_required")
    references: dict[str, str] = {}
    approved_references = tuple(
        (stage.provider_id, stage.credential_ref) for stage in bundle.stages
    )
    if bundle.acquisition_policy is not None:
        # Public sources do not exist when the worker starts. Bind their
        # release-approved credential references now so a later source cannot
        # introduce a browser-selected provider or secret path.
        approved_references += bundle.acquisition_policy.provider_references()
    for provider, credential_ref in approved_references:
        previous = references.setdefault(provider, credential_ref)
        if previous != credential_ref:
            raise ValueError("hosted_reporting_provider_reference_ambiguous")
    if not references:
        raise ValueError("hosted_reporting_stage_approval_required")
    if set(launchers) != set(references.values()):
        raise ValueError("hosted_reporting_launcher_scope_mismatch")
    routes: dict[str, ProviderRoute] = {}
    for provider, reference in references.items():
        launcher = launchers[reference]
        if type(launcher) is not InfisicalLauncher or launcher.provider_id != provider:
            raise ValueError("hosted_reporting_launcher_provider_mismatch")
        routes[provider] = ProviderRoute(
            provider,
            reference,
            ProcessInferenceBroker(python_executable=python_executable, infisical=launcher),
        )
    router = FixedProviderRouter(routes, authority=authority)
    return HostedReportingRuntime(
        authority=authority,
        storage=intake.storage,
        inference=ConversationInferenceWorker(
            sessions, intake.storage, router, authority=authority
        ),
        plans=ProcessingPlanScheduler(sessions, authority),
        retention=ConversationRetentionScheduler(sessions),
    )
