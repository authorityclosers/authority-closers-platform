"""Supervised hosted conversation worker; no HTTP listener or API identity.

Run explicitly with a digest-pinned, non-secret service manifest. The separate
native helper owns its container runtime. Provider identities are opened only
by their bounded children. SIGTERM drains accepted work before disposing the DB.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import signal
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.hosted_runtime import PinnedApprovalLoader
from ac_platform.conversation_intelligence.inference_broker import InfisicalLauncher
from ac_platform.conversation_intelligence.reporting_runtime import (
    compose_hosted_reporting,
    validate_bootstrap_approval,
)
from ac_platform.conversation_intelligence.runner import (
    ConversationWorkerRunner,
    ConversationWorkerRunnerSummary,
)
from ac_platform.conversation_intelligence.service_config import (
    WorkerServiceConfig,
    load_database_url,
    load_service_config,
    verify_installed_release,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.conversation_intelligence.worker import HostedConversationWorker

_INSTALLED_RELEASE = Path("/app/.ac-release-id")
_ALLOWED_ENV = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "HOME",
        "HOSTNAME",
        "TMPDIR",
        "TERM",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "PYTHONUTF8",
        "GPG_KEY",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "PYTHON_PIP_VERSION",
        "PYTHON_GET_PIP_SHA256",
        "PYTHON_GET_PIP_URL",
        "PYTHON_SETUPTOOLS_VERSION",
    }
)
_SAFE_FAILURE_CODE = re.compile(r"^worker_[a-z0-9_]+$")


def safe_failure_code(error: BaseException) -> str | None:
    """Return only stable internal codes; never echo provider/DB payloads."""

    candidate = str(error).strip()
    if _SAFE_FAILURE_CODE.fullmatch(candidate):
        return candidate
    return None


def validate_service_environment(environment: Mapping[str, str]) -> None:
    # A dedicated service must not inherit the API/ordinary queue worker's env.
    # Reject rather than forwarding or silently retaining unrelated secrets.
    if any(key not in _ALLOWED_ENV for key in environment):
        raise ValueError("worker_environment_not_isolated")


def configured_launchers(config: WorkerServiceConfig) -> dict[str, InfisicalLauncher]:
    return {
        item.credential_ref: InfisicalLauncher(
            executable=item.executable,
            provider_id=item.provider_id,
            project_ref=item.project_ref,
            environment_ref=item.environment_ref,
            secret_path_ref=item.secret_path_ref,
            token_file_ref=item.token_file_ref,
        )
        for item in config.providers
    }


def validate_bootstrap_configuration(config: WorkerServiceConfig) -> None:
    """Validate the pinned inert approval before entering bootstrap idle mode."""

    if not config.bootstrap_only:
        raise ValueError("worker_bootstrap_mode_required")
    bundle = PinnedApprovalLoader(
        Path(config.sales_xray_approval_path),
        config.sales_xray_approval_sha256,
        config.environment,
        config.operations_tenant_id,
    )()
    validate_bootstrap_approval(bundle)


async def run_service(
    config: WorkerServiceConfig, stop: asyncio.Event
) -> ConversationWorkerRunnerSummary:
    """Compose the four real database workers and run one serial consumer."""
    if config.bootstrap_only:
        validate_bootstrap_configuration(config)
        await stop.wait()
        return ConversationWorkerRunnerSummary()

    from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime

    launchers = configured_launchers(config)
    native = SocketNativeRuntime(
        socket_path=Path(config.native_socket_path),
        workspace_root=Path(config.sales_xray_scratch_root),
        expected_image_ref=config.native_image_ref,
    )
    # All validation above is inert. No API Settings or dotenv loading occurs.
    database_url = load_database_url(Path(config.database_url_file))
    engine = create_async_engine(
        database_url,
        echo=False,
        hide_parameters=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=10,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        reporting = compose_hosted_reporting(config, sessions, launchers=launchers)
        if reporting is None:
            raise ValueError("worker_reporting_configuration_required")
        offline = HostedConversationWorker(
            sessions,
            storage=reporting.storage,
            scratch=PrivateLocalRecordingStorage(Path(config.sales_xray_scratch_root)),
            environment=config.environment,
            native_runtime=native,
        )
        runner = ConversationWorkerRunner(
            reporting.retention, offline, reporting.plans, reporting.inference
        )
        return await runner.run(stop)
    finally:
        await engine.dispose()


async def serve(config: WorkerServiceConfig) -> ConversationWorkerRunnerSummary:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed: list[signal.Signals] = []
    try:
        for item in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(item, stop.set)
            installed.append(item)
        return await run_service(config, stop)
    finally:
        for item in installed:
            loop.remove_signal_handler(item)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated Sales Xray hosted worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="Validate references only; no dispatch"
    )
    action.add_argument(
        "--prepare-storage",
        action="store_true",
        help="Initialize new private roots through the storage adapter; no DB/provider execution",
    )
    args = parser.parse_args(argv)
    try:
        config = load_service_config(args.config, args.sha256)
        verify_installed_release(config, _INSTALLED_RELEASE)
        if config.bootstrap_only:
            validate_bootstrap_configuration(config)
        else:
            configured_launchers(config)
        if args.check:
            print("worker_config_valid")
            return 0
        if sys.platform != "linux":
            raise ValueError("worker_linux_required")
        validate_service_environment(os.environ)
        os.umask(0o077)
        if args.prepare_storage:
            PrivateLocalRecordingStorage(Path(config.sales_xray_storage_root))
            PrivateLocalRecordingStorage(Path(config.sales_xray_scratch_root))
            print("worker_storage_prepared")
            return 0
        asyncio.run(serve(config))
        print("worker_stopped")
        return 0
    except Exception as error:
        # Keep payloads/DSNs/provider bodies out of logs, but retain stable
        # admission/configuration codes so a restart loop is diagnosable.
        code = safe_failure_code(error)
        suffix = f":{code}" if code is not None else ""
        print(f"worker_service_failed{suffix}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
