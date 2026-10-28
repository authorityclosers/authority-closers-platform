"""Opt-in small-box worker; pinned provider policy and stage leases stay unchanged."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.gold_review_job import run_gold_reader
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.reporting_runtime import compose_hosted_reporting
from ac_platform.conversation_intelligence.runner import PipelinedConversationWorkerRunner
from ac_platform.conversation_intelligence.service import (
    configured_launchers,
    safe_failure_code,
    validate_bootstrap_configuration,
    validate_service_environment,
)
from ac_platform.conversation_intelligence.service_config import (
    WorkerServiceConfig,
    load_database_url,
    load_service_config,
    verify_installed_release,
)
from ac_platform.conversation_intelligence.stage_handoff import committed_work_listener
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from ac_platform.worker.load_gate import LoadGate, worker_job_limit


def cap_consumers(config: WorkerServiceConfig, requested: int) -> int:
    if type(requested) is not int or not 1 <= requested <= 2:
        raise ValueError("worker_lean_provider_cap_invalid")
    # Runtime CLI may reduce, never expand the signed manifest's concurrency.
    return min(config.provider_consumers, requested)


async def run_lean(
    config: WorkerServiceConfig,
    stop: asyncio.Event,
    *,
    consumers: int,
    max_jobs: int,
    pooled_database_url_file: Path,
    gate: LoadGate | None = None,
) -> None:
    if config.bootstrap_only:
        validate_bootstrap_configuration(config)
        await stop.wait()
        return
    direct_url = load_database_url(Path(config.database_url_file))
    pooled_url = load_database_url(pooled_database_url_file)
    if pooled_url.host != "pgbouncer" or pooled_url.port != 6432 or direct_url.host == "pgbouncer":
        raise ValueError("worker_lean_database_route_invalid")
    engine = create_async_engine(
        pooled_url,
        echo=False,
        hide_parameters=True,
        pool_size=consumers + 1,
        max_overflow=0,
        pool_timeout=10,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10, "prepare_threshold": None},
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        reporting = compose_hosted_reporting(
            config, sessions, launchers=configured_launchers(config)
        )
        if reporting is None:
            raise ValueError("worker_reporting_configuration_required")
        offline = HostedConversationWorker(
            sessions,
            storage=reporting.storage,
            scratch=PrivateLocalRecordingStorage(Path(config.sales_xray_scratch_root)),
            environment=config.environment,
            native_runtime=SocketNativeRuntime(
                socket_path=Path(config.native_socket_path),
                workspace_root=Path(config.sales_xray_scratch_root),
                expected_image_ref=config.native_image_ref,
            ),
        )
        gold = asyncio.create_task(
            run_gold_reader(sessions, config.operations_tenant_id, stop), name="gold-review-reader"
        )
        try:
            # LISTEN is session-scoped: it must bypass transaction pooling.
            async with committed_work_listener(direct_url) as wakeups:
                await PipelinedConversationWorkerRunner(
                    reporting.retention,
                    offline,
                    reporting.plans,
                    reporting.inference,
                    wakeups=wakeups,
                    provider_consumers=consumers,
                    max_jobs=max_jobs,
                    admission=gate.wait if gate else None,
                ).run(stop)
        finally:
            gold.cancel()
            with suppress(asyncio.CancelledError):
                await gold
    finally:
        await engine.dispose()


async def serve(config: WorkerServiceConfig, args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run_lean(
            config,
            stop,
            consumers=cap_consumers(config, args.provider_consumers),
            max_jobs=worker_job_limit(str(args.max_jobs)),
            pooled_database_url_file=args.pooled_database_url_file,
        )
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit lean hosted worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--provider-consumers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--max-jobs", type=int, default=100)
    parser.add_argument("--pooled-database-url-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_service_environment(os.environ)
        config = load_service_config(args.config, args.sha256)
        verify_installed_release(config, Path("/app/.ac-release-id"))
        cap_consumers(config, args.provider_consumers)
        if not 1 <= args.max_jobs <= 100_000:
            raise ValueError("worker_job_limit_invalid")
        os.umask(0o077)
        asyncio.run(serve(config, args))
        return 0
    except Exception as error:
        code = safe_failure_code(error)
        print("worker_service_failed" + (f":{code}" if code else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
