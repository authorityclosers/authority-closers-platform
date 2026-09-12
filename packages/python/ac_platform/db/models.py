"""Canonical SQLAlchemy model registry.

Importing this module loads every permanent G1 persistence model into the
shared :class:`~ac_platform.db.base.Base` metadata.  Alembic and integration
tests use this registry so a model cannot silently exist outside migration
drift checks.
"""

from __future__ import annotations

from sqlalchemy import MetaData

from ac_platform.app_updates import models as app_update_models
from ac_platform.audit import models as audit_models
from ac_platform.authorization import models as authorization_models
from ac_platform.catalog import models as catalog_models
from ac_platform.certificates import models as certificate_models
from ac_platform.community import models as community_models
from ac_platform.db.base import Base
from ac_platform.enrollment import models as enrollment_models
from ac_platform.identity import models as identity_models
from ac_platform.knowledge import models as knowledge_models
from ac_platform.learning import models as learning_models
from ac_platform.learning import planning_models
from ac_platform.media import models as media_models
from ac_platform.outbox import models as outbox_models
from ac_platform.practice import focus_models
from ac_platform.practice import models as practice_models
from ac_platform.providers import models as provider_models
from ac_platform.tenancy import models as tenancy_models

MODEL_MODULES = (
    identity_models,
    tenancy_models,
    app_update_models,
    community_models,
    authorization_models,
    knowledge_models,
    catalog_models,
    enrollment_models,
    learning_models,
    media_models,
    planning_models,
    certificate_models,
    outbox_models,
    provider_models,
    practice_models,
    focus_models,
    audit_models,
)


def model_metadata() -> MetaData:
    """Return metadata after all governed model modules have been loaded."""

    # Operations control models intentionally use isolated declarative
    # registries so importing a single service does not configure every domain
    # mapper.  Their tables still belong to the canonical Alembic schema: copy
    # the table definitions into the shared metadata used by migrations and
    # fresh-database tooling.
    for control_metadata in (
        outbox_models.operations_control_metadata(),
        audit_models.audit_control_metadata(),
    ):
        for table in control_metadata.tables.values():
            if table.name not in Base.metadata.tables:
                table.to_metadata(Base.metadata)
    return Base.metadata


__all__ = ["MODEL_MODULES", "model_metadata"]
