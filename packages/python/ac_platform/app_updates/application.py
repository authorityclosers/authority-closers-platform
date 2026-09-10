"""Self-scoped app-release catalogue and idempotent read acknowledgements."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.app_updates.catalogue import (
    CURRENT_ARTIFACT_RELEASES,
    AppRelease,
    AppReleaseCatalogue,
)
from ac_platform.app_updates.models import AppUpdateReadReceipt
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError


class AppUpdateError(DomainError):
    status = 400
    code = "app_update_error"
    title = "App update request could not be completed"


class AppUpdateUnavailable(AppUpdateError):
    status = 404
    code = "app_update_unavailable"
    title = "App update is unavailable"


class AppUpdateReceiptConflict(AppUpdateError):
    status = 409
    code = "app_update_receipt_conflict"
    title = "App update read state changed"


class AppUpdatesApplication:
    def __init__(
        self,
        database: AsyncSession,
        *,
        catalogue: AppReleaseCatalogue = CURRENT_ARTIFACT_RELEASES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.catalogue = catalogue
        self.clock = clock or (lambda: datetime.now(UTC))

    def _require_transaction(self) -> None:
        transaction = self.database.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise AppUpdateError("App update mutations require a caller-owned transaction.")

    @staticmethod
    def _tenant(actor: ActorContext) -> UUID:
        if actor.tenant_id is None:
            raise AppUpdateError("Select your learner academy before reading app updates.")
        return actor.tenant_id

    @staticmethod
    def _item(release: AppRelease, *, read: bool) -> dict[str, Any]:
        return {
            "id": release.id,
            "title": release.title,
            "message": release.message,
            "version": release.version,
            "highlights": list(release.highlights),
            "target_href": release.target_href,
            "created_at": release.created_at,
            "read": read,
        }

    async def list_updates(self, actor: ActorContext) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        visible = self.catalogue.available(self.clock())
        release_ids = {release.id for release in visible}
        if release_ids:
            result = await self.database.scalars(
                select(AppUpdateReadReceipt.release_id).where(
                    AppUpdateReadReceipt.tenant_id == tenant_id,
                    AppUpdateReadReceipt.person_id == actor.person_id,
                    AppUpdateReadReceipt.release_id.in_(release_ids),
                )
            )
            read_ids = set(result.all())
        else:
            read_ids = set()
        items = [self._item(release, read=release.id in read_ids) for release in visible]
        return {
            "person_id": actor.person_id,
            "tenant_id": tenant_id,
            "items": items,
            "unread_count": sum(not item["read"] for item in items),
        }

    async def mark_read(self, actor: ActorContext, release_id: str) -> dict[str, Any]:
        self._require_transaction()
        tenant_id = self._tenant(actor)
        if self.catalogue.resolve_available(release_id, self.clock()) is None:
            raise AppUpdateUnavailable("The requested app update is unavailable.")
        existing = await self.database.scalar(
            select(AppUpdateReadReceipt).where(
                AppUpdateReadReceipt.tenant_id == tenant_id,
                AppUpdateReadReceipt.person_id == actor.person_id,
                AppUpdateReadReceipt.release_id == release_id,
            )
        )
        if existing is None:
            try:
                async with self.database.begin_nested():
                    self.database.add(
                        AppUpdateReadReceipt(
                            tenant_id=tenant_id,
                            person_id=actor.person_id,
                            release_id=release_id,
                        )
                    )
                    await self.database.flush()
            except IntegrityError as error:
                existing = cast(
                    AppUpdateReadReceipt | None,
                    await self.database.scalar(
                        select(AppUpdateReadReceipt).where(
                            AppUpdateReadReceipt.tenant_id == tenant_id,
                            AppUpdateReadReceipt.person_id == actor.person_id,
                            AppUpdateReadReceipt.release_id == release_id,
                        )
                    ),
                )
                if existing is None:
                    raise AppUpdateReceiptConflict(
                        "Refresh app updates and try marking this item read again."
                    ) from error
        return await self.list_updates(actor)


__all__ = [
    "AppUpdateError",
    "AppUpdateReceiptConflict",
    "AppUpdateUnavailable",
    "AppUpdatesApplication",
]
