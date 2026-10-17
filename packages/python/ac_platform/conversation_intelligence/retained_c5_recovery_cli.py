"""Run one source-bound retained-C5 recovery command from the AC Admin workspace.

The CLI accepts the same strict intent used by the Admin HTTP surface.  It
opens the configured private response storage and the existing database
transaction, then records an append-only recovery version.  It never creates a
new inference task or contacts a provider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Never
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    RetainedC5Correction,
    RetainedC5CorrectionIntent,
    RetainedC5RecoveryService,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.kernel.authz import ActorContext


class CommandError(ValueError):
    """A safe operator-facing command validation failure."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CommandError("Invalid arguments; use --help for the command contract.")


def parser() -> argparse.ArgumentParser:
    command = _Parser(description=__doc__, allow_abbrev=False)
    command.add_argument("action", choices=("revalidate", "correct"))
    command.add_argument("--environment", required=True)
    command.add_argument("--allow-production", action="store_true")
    command.add_argument("--tenant-id", required=True, type=UUID)
    command.add_argument("--person-id", required=True, type=UUID)
    command.add_argument("--session-id", required=True, type=UUID)
    command.add_argument("--run-id", required=True, type=UUID)
    command.add_argument("--original-raw-sha256", required=True)
    command.add_argument("--idempotency-key", required=True)
    command.add_argument(
        "--historical-input-file",
        type=Path,
        required=True,
        help="Private file containing the exact canonical C5 request bytes from the failed run.",
    )
    command.add_argument(
        "--recording-tenant-id",
        type=UUID,
        help="Tenant owning the retained recording; defaults to the configured learner tenant.",
    )
    command.add_argument(
        "--correction-file",
        type=Path,
        help="Private JSON file containing the exact correction intent for 'correct'.",
    )
    return command


def validate_environment(args: argparse.Namespace) -> str:
    environment = str(args.environment).strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CommandError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and not args.allow_production:
        raise CommandError("Production requires --allow-production.")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise CommandError("An explicit AC_DATABASE_URL is required.")
    raw_hash = str(args.original_raw_sha256).strip()
    if len(raw_hash) != 64 or any(value not in "0123456789abcdef" for value in raw_hash):
        raise CommandError("The original response hash must be a lowercase SHA-256 digest.")
    if not isinstance(args.idempotency_key, str) or not 1 <= len(args.idempotency_key) <= 128:
        raise CommandError("The idempotency key must be 1 to 128 characters.")
    if args.action == "correct" and args.correction_file is None:
        raise CommandError("The correct action requires --correction-file.")
    if args.action == "revalidate" and args.correction_file is not None:
        raise CommandError("The revalidate action does not accept --correction-file.")
    return environment


def _patch_path(value: object) -> str:
    if isinstance(value, str) and value.startswith("/"):
        return value
    if not isinstance(value, str) or not value.strip():
        raise CommandError("A correction path is unavailable.")
    tokens = value.split()
    escaped = [item.replace("~", "~0").replace("/", "~1") for item in tokens]
    return "/" + "/".join(escaped)


def _load_correction(path: Path, original_raw_sha256: str) -> RetainedC5CorrectionIntent:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "corrections" in payload:
            intent_payload = {
                **payload,
                "original_raw_sha256": payload.get("original_raw_sha256", original_raw_sha256),
            }
        else:
            patches = payload.get("patches") if isinstance(payload, dict) else payload
            if not isinstance(patches, list):
                raise CommandError("The correction file has no bounded correction list.")
            corrections: list[dict[str, object]] = []
            for patch in patches:
                if not isinstance(patch, dict):
                    raise CommandError("The correction file contains an invalid patch.")
                new_value = patch.get("new_value")
                if isinstance(patch.get("new_text"), str) and patch["new_text"]:
                    new_value = patch["new_text"]
                corrections.append(
                    {
                        "path": _patch_path(patch.get("json_pointer", patch.get("path"))),
                        "old_sha256": patch.get("old_value_sha256", patch.get("old_sha256")),
                        "new_text": new_value,
                        "source_segment_ids": patch.get("source_segment_ids"),
                        "rationale": patch.get("rationale"),
                    }
                )
            normalized = [RetainedC5Correction.model_validate(item) for item in corrections]
            intent_payload = {
                "original_raw_sha256": original_raw_sha256,
                "corrections": normalized,
                "correction_payload_sha256": content_hash(
                    [item.model_dump(mode="json") for item in normalized]
                ),
            }
        return RetainedC5CorrectionIntent.model_validate(intent_payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        raise CommandError(
            "The correction file is unavailable or fails the recovery contract."
        ) from None


def _load_historical_input(path: Path) -> bytes:
    try:
        value = path.read_bytes()
    except (OSError, ValueError):
        raise CommandError("The historical C5 request file is unavailable.") from None
    if not 1 <= len(value) <= 512 * 1024:
        raise CommandError("The historical C5 request file is outside its size bound.")
    return value


async def execute(args: argparse.Namespace) -> dict[str, object]:
    environment = validate_environment(args)
    settings = Settings(environment=environment)
    operations_tenant_id = settings.operations_tenant_id
    if operations_tenant_id is None or args.tenant_id != operations_tenant_id:
        raise CommandError("The tenant must match the configured AC operations workspace.")
    recording_tenant_id = args.recording_tenant_id or settings.public_learner_tenant_id
    if recording_tenant_id is None:
        raise CommandError("A configured retained-recording tenant is required.")
    if settings.sales_xray_storage_root is None:
        raise CommandError("The private Sales Xray storage root is not configured.")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    correction = None
    historical_input = _load_historical_input(args.historical_input_file)
    if args.action == "correct":
        correction = _load_correction(args.correction_file, args.original_raw_sha256)
        if correction.original_raw_sha256 != args.original_raw_sha256:
            raise CommandError("The correction file is bound to a different response hash.")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            actor = ActorContext(
                person_id=args.person_id,
                session_id=args.session_id,
                tenant_id=args.tenant_id,
                permissions=frozenset({"admin_surface"}),
            )
            result = await RetainedC5RecoveryService(
                ConversationApplication(database),
                operations_tenant_id=operations_tenant_id,
                recording_tenant_ids=(recording_tenant_id,),
            ).revalidate(
                actor,
                args.run_id,
                original_raw_sha256=args.original_raw_sha256,
                key=args.idempotency_key,
                storage=PrivateLocalRecordingStorage(Path(settings.sales_xray_storage_root)),
                correction=correction,
                historical_input=historical_input,
            )
    finally:
        await engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(execute(parser().parse_args(argv)))
    except CommandError as exc:
        print(f"Retained C5 recovery refused: {exc}", file=sys.stderr)
        return 2
    except (OSError, SQLAlchemyError, ValueError):
        print(
            "Retained C5 recovery refused; check the Admin identity, private storage "
            "and database state.",
            file=sys.stderr,
        )
        return 2
    # Keep private report content out of routine operator stdout.  The command
    # still returns proof metadata needed for a receipt; callers that need the
    # draft can use the Admin read boundary after authorization.
    summary = dict(result)
    summary.pop("report", None)
    summary["report_available"] = result.get("report") is not None
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
