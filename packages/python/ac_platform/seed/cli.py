"""Package-native CLI for reviewed or STAGING-ONLY seed application."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import (
    ReleaseIdentityError,
    read_baked_release_id,
)
from ac_platform.application.settings import Settings
from ac_platform.kernel.authz import ActorContext
from ac_platform.seed.application import SeedApplicationError, StagingSeedApplication
from ac_platform.seed.contract import (
    CONTROLLED_FOUNDATION_SEED_PATH,
    FreeCourseSeed,
    SeedContractError,
    TechnicalValidationSeed,
    load_seed,
)
from ac_platform.seed.technical_validation_fixture import technical_validation_seed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-data", type=Path)
    parser.add_argument(
        "--controlled-foundation-v1",
        action="store_true",
        help="select the packaged AC-IMP-04 four-shift/Module-1 foundation seed",
    )
    parser.add_argument("--actor-person-id", required=True, type=UUID)
    parser.add_argument("--release-id", default=os.getenv("AC_RELEASE_ID"))
    parser.add_argument("--environment", default=os.getenv("AC_ENVIRONMENT"))
    parser.add_argument(
        "--technical-validation",
        action="store_true",
        help="select the synthetic STAGING-ONLY technical validation catalog",
    )
    parser.add_argument(
        "--acknowledge-staging-technical-validation",
        action="store_true",
        help="acknowledge that technical validation is not approved product content",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    environment = str(args.environment or "").strip().lower()
    configured_environment = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if environment == "production" or configured_environment == "production":
        raise SeedApplicationError("production is never an allowed target for the staging seed")
    if configured_environment != "staging":
        raise SeedApplicationError("AC_ENVIRONMENT=staging is required")
    if environment != "staging":
        raise SeedApplicationError("--environment must be staging")

    configured_release_id = os.getenv("AC_RELEASE_ID", "").strip()
    if not configured_release_id:
        raise SeedApplicationError("AC_RELEASE_ID is required for the staging seed")
    release_id = str(args.release_id or configured_release_id).strip()
    if configured_release_id != release_id:
        raise SeedApplicationError("--release-id must match AC_RELEASE_ID")
    try:
        baked_release_id = read_baked_release_id()
    except ReleaseIdentityError as error:
        raise SeedApplicationError(str(error)) from error
    if configured_release_id != baked_release_id:
        raise SeedApplicationError("AC_RELEASE_ID does not match the baked API release marker")
    if release_id != baked_release_id:
        raise SeedApplicationError("--release-id does not match the baked API release marker")

    seed: FreeCourseSeed | TechnicalValidationSeed
    if args.technical_validation:
        if not args.acknowledge_staging_technical_validation:
            raise SeedApplicationError(
                "technical validation requires --acknowledge-staging-technical-validation"
            )
        if args.seed_data is not None:
            raise SeedApplicationError(
                "technical validation uses its package fixture, not --seed-data"
            )
        if args.controlled_foundation_v1:
            raise SeedApplicationError(
                "--controlled-foundation-v1 cannot be combined with technical validation"
            )
        seed = technical_validation_seed(release_id)
    else:
        if args.acknowledge_staging_technical_validation:
            raise SeedApplicationError(
                "--acknowledge-staging-technical-validation requires --technical-validation"
            )
        if args.seed_data is not None and args.controlled_foundation_v1:
            raise SeedContractError(
                "choose either --seed-data or --controlled-foundation-v1, not both"
            )
        seed_path = (
            CONTROLLED_FOUNDATION_SEED_PATH if args.controlled_foundation_v1 else args.seed_data
        )
        if seed_path is None:
            raise SeedContractError(
                "--seed-data or --controlled-foundation-v1 is required for reviewed content"
            )
        seed = load_seed(
            seed_path,
            environment=environment,
            expected_release_id=release_id,
        )

    settings = Settings(environment=environment, release_id=release_id)

    actor = ActorContext(
        person_id=args.actor_person_id,
        session_id=uuid4(),
        tenant_id=None,
        # The application verifies an active persisted admin/owner membership.
        # CLI input must never self-assert catalog authority.
        permissions=frozenset(),
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            application = StagingSeedApplication(
                session,
                environment=environment,
                expected_release_id=release_id,
            )
            if isinstance(seed, TechnicalValidationSeed):
                result = await application.apply_technical_validation(seed, actor=actor)
            else:
                result = await application.apply(seed, actor=actor)
    finally:
        await engine.dispose()
    print(
        json.dumps(
            {"environment": settings.environment, **asdict(result)},
            default=str,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_async(_run(args))
    except (SeedApplicationError, SeedContractError, OSError, ValueError) as exc:
        print(f"seed refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("seed refused: database operation failed", file=sys.stderr)
        return 2


__all__ = ["main"]
