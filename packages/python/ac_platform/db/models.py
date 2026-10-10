"""Canonical SQLAlchemy model registry.

Importing this module loads every permanent G1 persistence model into the
shared :class:`~ac_platform.db.base.Base` metadata.  Alembic and integration
tests use this registry so a model cannot silently exist outside migration
drift checks.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import MetaData

from ac_platform.app_updates import models as app_update_models
from ac_platform.audit import models as audit_models
from ac_platform.authorization import models as authorization_models
from ac_platform.billing import credit_models as billing_credit_models
from ac_platform.billing import invoice_models as billing_invoice_models
from ac_platform.billing import models as billing_models
from ac_platform.billing import order_models as billing_order_models
from ac_platform.catalog import models as catalog_models
from ac_platform.certificates import models as certificate_models
from ac_platform.community import models as community_models
from ac_platform.conversation_intelligence import (
    acquisition_models,
    call_metrics_models,
    canary_models,
    execution_control_models,
    guest_models,
    prospect_models,
    recovery_models,
    sensitive_segment_models,
    source_object_models,
    speaker_map_models,
    submission_label_models,
)
from ac_platform.conversation_intelligence import models as conversation_models
from ac_platform.db.base import Base
from ac_platform.enrollment import models as enrollment_models
from ac_platform.identity import google_profile_models, sales_xray_profile_models
from ac_platform.identity import models as identity_models
from ac_platform.knowledge import models as knowledge_models
from ac_platform.learning import models as learning_models
from ac_platform.learning import planning_models
from ac_platform.media import models as media_models
from ac_platform.outbox import models as outbox_models
from ac_platform.plans import models as plan_models
from ac_platform.practice import focus_models
from ac_platform.practice import models as practice_models
from ac_platform.product_updates import models as product_update_models
from ac_platform.providers import models as provider_models
from ac_platform.tenancy import models as tenancy_models

MODEL_MODULES = (
    identity_models,
    google_profile_models,
    sales_xray_profile_models,
    tenancy_models,
    app_update_models,
    product_update_models,
    community_models,
    conversation_models,
    acquisition_models,
    call_metrics_models,
    canary_models,
    guest_models,
    prospect_models,
    submission_label_models,
    speaker_map_models,
    execution_control_models,
    recovery_models,
    source_object_models,
    sensitive_segment_models,
    authorization_models,
    knowledge_models,
    catalog_models,
    enrollment_models,
    learning_models,
    media_models,
    planning_models,
    certificate_models,
    outbox_models,
    plan_models,
    provider_models,
    practice_models,
    focus_models,
    audit_models,
    billing_models,
    billing_credit_models,
    billing_invoice_models,
    billing_order_models,
)


def _companion_hash(name: str) -> sa.Column[str]:
    return sa.Column(name, sa.String(64), nullable=False, unique=True)


def _companion_time(name: str, *, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


# Core tables keep this storage-only card inside the canonical registry. Native
# HTTP admission and credential transitions are implemented by subsequent cards.
companion_devices = sa.Table(
    "companion_devices",
    Base.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("tenant_id", sa.Uuid(), nullable=False),
    sa.Column("person_id", sa.Uuid(), nullable=False),
    sa.Column("name", sa.String(160), nullable=False),
    sa.Column("platform", sa.String(16), nullable=False),
    _companion_time("created_at"),
    _companion_time("revoked_at", nullable=True),
    sa.ForeignKeyConstraint(
        ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
    ),
    sa.CheckConstraint("length(name) BETWEEN 1 AND 160", name="name_bounded"),
    sa.CheckConstraint(
        "platform IN ('android', 'ios', 'windows', 'macos', 'chrome')", name="platform"
    ),
    sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation_time"),
    sa.Index("ix_companion_devices_owner", "tenant_id", "person_id"),
)
companion_pairings = sa.Table(
    "companion_pairings",
    Base.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    _companion_hash("code_sha256"),
    _companion_hash("poll_secret_sha256"),
    sa.Column("name", sa.String(160), nullable=False),
    sa.Column("platform", sa.String(16), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("device_id", sa.Uuid(), sa.ForeignKey("companion_devices.id"), unique=True),
    _companion_time("created_at"),
    _companion_time("expires_at"),
    _companion_time("decided_at", nullable=True),
    _companion_time("collected_at", nullable=True),
    sa.CheckConstraint("length(code_sha256) = 64", name="code_hash_length"),
    sa.CheckConstraint("length(poll_secret_sha256) = 64", name="poll_hash_length"),
    sa.CheckConstraint("code_sha256 ~ '^[0-9a-f]{64}$'", name="code_hash").ddl_if(
        dialect="postgresql"
    ),
    sa.CheckConstraint("poll_secret_sha256 ~ '^[0-9a-f]{64}$'", name="poll_hash").ddl_if(
        dialect="postgresql"
    ),
    sa.CheckConstraint("length(name) BETWEEN 1 AND 160", name="name_bounded"),
    sa.CheckConstraint(
        "platform IN ('android', 'ios', 'windows', 'macos', 'chrome')", name="platform"
    ),
    sa.CheckConstraint(
        "expires_at > created_at AND expires_at <= created_at + interval '10 minutes'",
        name="expiry",
    ).ddl_if(dialect="postgresql"),
    sa.CheckConstraint(
        "state IN ('pending', 'approved', 'denied', 'collected') AND "
        "(state IN ('approved', 'collected')) = (device_id IS NOT NULL) AND "
        "(state = 'pending') = (decided_at IS NULL) AND "
        "(state = 'collected') = (collected_at IS NOT NULL)",
        name="state_binding",
    ),
    sa.CheckConstraint(
        "decided_at IS NULL OR decided_at BETWEEN created_at AND expires_at", name="decision_time"
    ),
    sa.CheckConstraint(
        "collected_at IS NULL OR collected_at BETWEEN decided_at AND expires_at",
        name="collection_time",
    ),
)
companion_refresh_families = sa.Table(
    "companion_refresh_families",
    Base.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("device_id", sa.Uuid(), sa.ForeignKey("companion_devices.id"), nullable=False),
    _companion_time("created_at"),
    _companion_time("idle_expires_at"),
    _companion_time("absolute_expires_at"),
    _companion_time("revoked_at", nullable=True),
    sa.CheckConstraint(
        "absolute_expires_at > created_at AND "
        "absolute_expires_at <= created_at + interval '90 days'",
        name="absolute_expiry",
    ).ddl_if(dialect="postgresql"),
    sa.CheckConstraint(
        "idle_expires_at > created_at AND idle_expires_at <= absolute_expires_at",
        name="idle_expiry",
    ),
    sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation_time"),
    sa.Index("ix_companion_refresh_families_device_id", "device_id"),
)
companion_credentials = sa.Table(
    "companion_credentials",
    Base.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "family_id", sa.Uuid(), sa.ForeignKey("companion_refresh_families.id"), nullable=False
    ),
    sa.Column("kind", sa.String(16), nullable=False),
    _companion_hash("token_sha256"),
    _companion_time("created_at"),
    _companion_time("expires_at"),
    _companion_time("consumed_at", nullable=True),
    sa.CheckConstraint("length(token_sha256) = 64", name="token_hash_length"),
    sa.CheckConstraint("token_sha256 ~ '^[0-9a-f]{64}$'", name="token_hash").ddl_if(
        dialect="postgresql"
    ),
    sa.CheckConstraint(
        "expires_at > created_at AND "
        "((kind = 'access' AND expires_at <= created_at + interval '15 minutes') OR "
        "(kind = 'refresh' AND expires_at <= created_at + interval '30 days') OR "
        "(kind = 'web_session' AND expires_at <= created_at + interval '60 seconds'))",
        name="kind_expiry",
    ).ddl_if(dialect="postgresql"),
    sa.CheckConstraint(
        "consumed_at IS NULL OR consumed_at BETWEEN created_at AND expires_at",
        name="consumption_time",
    ),
    sa.Index("ix_companion_credentials_family_id", "family_id"),
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
