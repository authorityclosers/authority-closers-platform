"""Optional guest acquisition composition; no inference credential loading."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import (
    UPLOAD_ACTION,
    UploadChallenge,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.acquisition_usage import ALLOWANCE_SECONDS
from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    latest_analysis_settings,
)
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.kernel.errors import DomainError


def _challenge_secret(path: Path) -> SecretStr:
    """Read one fixed external file; never include its path/content in errors."""
    try:
        if (
            not path.is_absolute()
            or ".." in path.parts
            or any(p.is_symlink() for p in (path, *path.parents))
            or any((p / ".git").exists() for p in (path.parent, *path.parents))
        ):
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 1 <= info.st_size <= 258
                or (os.name != "nt" and info.st_mode & 0o077)
            ):
                raise ValueError
            raw = stream.read(259).rstrip(b"\r\n")
        value = raw.decode("ascii")
        if re.fullmatch(r"[A-Za-z0-9_-]{16,256}", value) is None:
            raise ValueError
        return SecretStr(value)
    except (OSError, ValueError, UnicodeError):
        raise ValueError("acquisition_challenge_unavailable") from None


@dataclass(frozen=True)
class AcquisitionRuntime:
    intake: ConversationIntakeRuntime
    challenge: UploadChallenge
    preflight: NativeUploadPreflight
    site_key: str
    policy_revision: str
    tester_policy: InternalTesterPolicy | None = None


def compose_acquisition(
    settings: Settings, intake: ConversationIntakeRuntime | None
) -> AcquisitionRuntime | None:
    if not settings.sales_xray_acquisition_enabled:
        return None
    if (
        intake is None
        or settings.sales_xray_app_url is None
        or settings.public_learner_tenant_id not in intake.policy.tenant_ids
        or not settings.sales_xray_challenge_secret_file
        or not settings.sales_xray_native_socket_path
        or not settings.sales_xray_native_image_ref
        or not isinstance(settings.sales_xray_challenge_site_key, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{10,128}", settings.sales_xray_challenge_site_key) is None
        or not isinstance(settings.sales_xray_acquisition_policy_revision, str)
        or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", settings.sales_xray_acquisition_policy_revision)
        is None
    ):
        raise ValueError("acquisition_configuration_unavailable")
    socket_path = Path(settings.sales_xray_native_socket_path)
    native = SocketNativeRuntime(
        socket_path,
        workspace_root=intake.scratch.root,
        expected_image_ref=settings.sales_xray_native_image_ref,
    )
    if settings.environment in {"staging", "production"}:
        try:
            info = socket_path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o007:
                raise ValueError
        except (OSError, ValueError):
            raise ValueError("acquisition_native_helper_unavailable") from None
    secret = _challenge_secret(Path(settings.sales_xray_challenge_secret_file))
    return AcquisitionRuntime(
        intake,
        UploadChallenge(secret=secret, hostname=str(settings.sales_xray_app_url.host)),
        NativeUploadPreflight(native),
        settings.sales_xray_challenge_site_key,
        settings.sales_xray_acquisition_policy_revision,
        None if intake.authority is None else intake.authority.tester_policy,
    )


def install_acquisition_runtime(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    runtime: AcquisitionRuntime | None,
) -> None:
    sales_host = settings.sales_xray_app_url.host if settings.sales_xray_app_url else None
    learner_host = settings.public_app_url.host

    def surface(request: Request) -> str | None:
        if request.url.hostname == sales_host:
            return "sales"
        if request.url.hostname == learner_host:
            return "learner"
        return None

    read_require_actor = getattr(require_actor, "read_only", require_actor)

    @asynccontextmanager
    async def learner_account(
        request: Request, *, read_only: bool = False
    ) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            dependency = read_require_actor if read_only else require_actor
            async with asynccontextmanager(dependency)(request) as auth:
                if auth.resolved.actor.tenant_id != settings.public_learner_tenant_id:
                    raise HTTPException(
                        403,
                        "The public Academy account is required for this upload workspace.",
                    )
                yield auth
        except DomainError:
            raise HTTPException(
                401,
                "Sign in to the public Academy to use this upload workspace.",
                headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
            ) from None

    @application.get("/v1/conversation/acquisition/entry")
    async def entry(request: Request, response: Response) -> dict[str, object]:
        response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})
        host = surface(request)
        if host is None or request.query_params:
            raise HTTPException(
                404, "Upload entry not found.", headers={"Cache-Control": "no-store"}
            )
        if host == "learner":
            async with learner_account(request, read_only=True):
                pass
        value: dict[str, object] = {
            "enabled": runtime is not None,
            "site_key": runtime.site_key if runtime else None,
            "challenge_action": UPLOAD_ACTION if runtime else None,
            "policy_revision": runtime.policy_revision if runtime else None,
            "allowance_seconds": ALLOWANCE_SECONDS if runtime else None,
        }
        if runtime is None:
            # Optional acquisition must remain disabled without touching its
            # database or advertising language capabilities it cannot execute.
            return value
        operations_tenant_id = (
            runtime.intake.authority.operations_tenant_id
            if runtime.intake.authority is not None
            else settings.operations_tenant_id
        )
        analysis_settings = DEFAULT_ANALYSIS_SETTINGS
        if operations_tenant_id is not None:
            async with sessions() as database:
                _, analysis_settings = await latest_analysis_settings(
                    database, operations_tenant_id
                )
        value.update(
            report_languages=(
                ["en"]
                if analysis_settings.c5_coaching_prompt_revision == "coaching-v3"
                else ["en", "hi-Deva+en", "mr-Deva+en"]
            ),
            report_language_default=analysis_settings.report_language_default,
        )
        if host == "learner":
            # The learner mount uses the existing account session. It never
            # receives the guest challenge or a guest bearer cookie.
            value.update({"site_key": None, "challenge_action": None, "auth_mode": "account"})
        return value

    if runtime is None:
        return

    def factory(database: AsyncSession) -> AcquisitionSessions:
        tenant = settings.public_learner_tenant_id
        if tenant is None:
            raise RuntimeError("The configured public Academy is required.")
        authority = runtime.intake.authority
        operations_tenant_id = (
            authority.operations_tenant_id
            if authority is not None and authority.operations_tenant_id is not None
            else settings.operations_tenant_id
        )
        return AcquisitionSessions(
            database,
            tenant_id=tenant,
            policy_revision=runtime.policy_revision,
            tester_policy=runtime.tester_policy,
            operations_tenant_id=operations_tenant_id,
        )

    install_acquisition_http(
        application,
        settings=settings,
        sessions=sessions,
        require_actor=require_actor,
        factory=factory,
        challenge=runtime.challenge,
    )
    install_submission_http(
        application,
        settings=settings,
        sessions=sessions,
        require_actor=require_actor,
        factory=factory,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
