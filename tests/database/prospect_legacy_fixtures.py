"""Scoped old-person mapping for populated 0076/0077 Prospect upgrade proofs.

Production uses the current model. These tests populate the actual historical
schema, then restore every model binding before upgrading and checking drift.
"""

from typing import Any

from sqlalchemy import MetaData, Table


def legacy_person_projection(engine: Any, mapper_registry: Any, patch: Any) -> type:
    table = Table("persons", MetaData(), autoload_with=engine)
    assert "username" not in table.c and "password_change_required" not in table.c

    class LegacyPerson:
        # These fields had not been introduced. No temporary credential or
        # username proof existed in the historical fixture being migrated.
        username = None
        username_verified_at = None
        password_change_required = False
        temporary_password_expires_at = None

    mapper_registry.map_imperatively(LegacyPerson, table)
    for module in (
        "tests.database.test_conversation_postgresql",
        "tests.database.test_conversation_submission_http_postgresql",
        "ac_platform.conversation_intelligence.guest_ownership",
        "ac_platform.conversation_intelligence.application",
    ):
        patch.setattr(f"{module}.Person", LegacyPerson)
    return LegacyPerson


def legacy_admission_uses(patch: Any) -> None:
    """0076/0077 predate report minute events (0080), so admission there reads uses as
    it did then: settled seconds, else reserved seconds. Today's ledger also reads the
    latest minute event (a released call uses nothing)."""

    from sqlalchemy import select

    from ac_platform.billing.ledger import BillingLedger, _utc
    from ac_platform.billing.projection import Use
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionSettlement as Settlement,
    )
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )

    async def uses(self: Any, tenant_id: Any, owner: Any) -> list[Use]:
        rows = await self.database.execute(
            select(Usage.id, Usage.created_at, Usage.reserved_seconds, Settlement.charged_seconds)
            .select_from(Usage)
            .outerjoin(Settlement, Settlement.usage_id == Usage.id)
            .where(Usage.tenant_id == tenant_id, owner)
        )
        return [
            Use(
                use_id=str(usage_id),
                at=_utc(created_at),
                seconds=reserved if charged is None else charged,
                pending=charged is None,
            )
            for usage_id, created_at, reserved, charged in rows
        ]

    patch.setattr(BillingLedger, "_acquisition_uses", uses)
