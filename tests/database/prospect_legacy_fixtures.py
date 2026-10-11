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
