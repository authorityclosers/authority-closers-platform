"""Send one approved existing verification email while recovery is held."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import ReleaseIdentityError, require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.bootstrap.verification_email import (
    VerificationEmailBootstrapApplication,
    VerificationEmailBootstrapCommand,
    VerificationEmailBootstrapError,
    VerificationEmailBootstrapResult,
)
from ac_platform.providers import (
    AmbiguousDeliveryProviderError,
    PermanentProviderError,
    TransientProviderError,
    create_email_provider_from_settings,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default=os.getenv("AC_ENVIRONMENT"))
    parser.add_argument("--person-id", type=UUID, required=True)
    parser.add_argument("--challenge-id", type=UUID, required=True)
    parser.add_argument("--command-id", type=UUID, required=True)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--operator-reference", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--allow-production", action="store_true")
    return parser


def _required(value: str | None, flag: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise VerificationEmailBootstrapError(f"{flag} is required")
    return normalized


async def _run(args: argparse.Namespace) -> int:
    environment = _required(args.environment, "--environment").lower()
    configured_environment = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured_environment and configured_environment != environment:
        raise VerificationEmailBootstrapError("--environment must match AC_ENVIRONMENT")
    if environment == "production" and not args.allow_production:
        raise VerificationEmailBootstrapError("production requires --allow-production")
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise VerificationEmailBootstrapError("--environment is not supported")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise VerificationEmailBootstrapError("AC_DATABASE_URL is required")
    settings = Settings(environment=environment)
    if settings.operations_tenant_id is None:
        raise VerificationEmailBootstrapError("AC_OPERATIONS_TENANT_ID is required")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
        if settings.email_provider != "resend":
            raise VerificationEmailBootstrapError(
                "staging and production require the reviewed Resend provider"
            )
    # Validate provider composition before opening a database transaction. A
    # missing key/sender must never leave an audited intent or held job behind.
    provider = create_email_provider_from_settings(settings)
    command = VerificationEmailBootstrapCommand(
        command_id=args.command_id,
        person_id=args.person_id,
        challenge_id=args.challenge_id,
        expected_email=args.expected_email,
        operator_reference=args.operator_reference,
        reason=args.reason,
    )

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            prepared = await VerificationEmailBootstrapApplication(
                session,
                operations_tenant_id=settings.operations_tenant_id,
            ).prepare(command)

        async with sessions() as session, session.begin():
            application = VerificationEmailBootstrapApplication(
                session,
                operations_tenant_id=settings.operations_tenant_id,
            )
            lease = await application.claim(prepared)
            if lease is None:
                result = await application.result_for_succeeded(prepared)
                print(json.dumps(asdict(result), default=str, sort_keys=True))
                return 0

        try:
            async with sessions() as session, session.begin():
                message = await VerificationEmailBootstrapApplication(
                    session,
                    operations_tenant_id=settings.operations_tenant_id,
                ).begin_dispatch(prepared, lease, settings=settings)
        except Exception as error:
            async with sessions() as session, session.begin():
                await VerificationEmailBootstrapApplication(
                    session,
                    operations_tenant_id=settings.operations_tenant_id,
                ).record_failure(prepared, lease, error, ambiguous=False)
            raise VerificationEmailBootstrapError(
                "verification email could not be prepared; inspect the durable job"
            ) from error

        try:
            async with sessions() as session, session.begin():
                receipt = await VerificationEmailBootstrapApplication(
                    session,
                    operations_tenant_id=settings.operations_tenant_id,
                ).dispatch(prepared, lease, message=message, provider=provider)
        except Exception as error:
            ambiguous = not isinstance(error, TransientProviderError | PermanentProviderError)
            if isinstance(error, TimeoutError | AmbiguousDeliveryProviderError):
                ambiguous = True
            async with sessions() as session, session.begin():
                await VerificationEmailBootstrapApplication(
                    session,
                    operations_tenant_id=settings.operations_tenant_id,
                ).record_failure(prepared, lease, error, ambiguous=ambiguous)
            raise VerificationEmailBootstrapError(
                "verification email delivery did not complete; inspect the durable job"
            ) from error

        result = VerificationEmailBootstrapResult(
            command_id=prepared.command.command_id,
            person_id=prepared.command.person_id,
            challenge_id=prepared.command.challenge_id,
            event_id=prepared.event_id,
            job_id=prepared.job_id,
            recovery_generation=prepared.recovery_generation,
            provider_message_id=receipt.provider_message_id,
            deduplicated=receipt.deduplicated,
            replayed=prepared.replayed,
        )
        print(json.dumps(asdict(result), default=str, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_async(_run(args))
    except ValidationError:
        print(
            "verification email bootstrap refused: deployment configuration is invalid",
            file=sys.stderr,
        )
        return 2
    except (
        VerificationEmailBootstrapError,
        PermanentProviderError,
        OSError,
        ReleaseIdentityError,
        ValueError,
    ) as exc:
        print(f"verification email bootstrap refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("verification email bootstrap refused: database operation failed", file=sys.stderr)
        return 2


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - exercised by the release command
    raise SystemExit(main())
