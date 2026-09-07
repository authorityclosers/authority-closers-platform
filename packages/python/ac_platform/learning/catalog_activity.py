"""Shared catalog-to-learning facts; no inferred scoring or evidence policy."""

from ac_platform.learning.services import ActivityDefinition


def resolve_catalog_activity(row: object, _version: object) -> ActivityDefinition:
    """Keep HTTP and byte-delivery authorization on identical catalog facts."""
    return ActivityDefinition(
        id=row.id,  # type: ignore[attr-defined]
        kind=row.kind,  # type: ignore[attr-defined]
        module_id=row.module_id,  # type: ignore[attr-defined]
        program_version_id=row.program_version_id,  # type: ignore[attr-defined]
        program_id=row.program_id,  # type: ignore[attr-defined]
        program_scope=row.scope,  # type: ignore[attr-defined]
        program_owner_key=row.owner_key,  # type: ignore[attr-defined]
        title=row.title,  # type: ignore[attr-defined]
        order=row.position,  # type: ignore[attr-defined]
        required=row.is_required,  # type: ignore[attr-defined]
        version=f"activity:{row.id}",  # type: ignore[attr-defined]
        tenant_id=row.tenant_id,  # type: ignore[attr-defined]
    )
