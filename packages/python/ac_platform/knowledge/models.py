"""SQLAlchemy metadata for the immutable knowledge snapshot read model."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv
from sqlalchemy.sql.expression import ColumnElement

from ac_platform.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class _KnowledgeSearchVectorExpression(ColumnElement[str]):
    """Compile the PostgreSQL generated-column expression on every test dialect."""

    inherit_cache = True


class _KnowledgeDigestHexExpression(ColumnElement[bool]):
    """Compile the PostgreSQL digest-hex check while keeping SQLite metadata usable."""

    inherit_cache = True


class _KnowledgeChunkDigestExpression(ColumnElement[bool]):
    """Compile the PostgreSQL passage digest check while keeping SQLite metadata usable."""

    inherit_cache = True


@compiles(_KnowledgeSearchVectorExpression, "postgresql")
def _compile_postgresql_search_vector(
    _element: _KnowledgeSearchVectorExpression, _compiler: object, **_kw: object
) -> str:
    return "to_tsvector('simple'::regconfig, passage)"


@compiles(_KnowledgeSearchVectorExpression, "sqlite")
def _compile_sqlite_search_vector(
    _element: _KnowledgeSearchVectorExpression, _compiler: object, **_kw: object
) -> str:
    # SQLite is used only for model-level tests; a generated passthrough keeps
    # metadata.create_all usable without pretending SQLite implements FTS.
    return "passage"


@compiles(_KnowledgeSearchVectorExpression)
def _compile_default_search_vector(
    _element: _KnowledgeSearchVectorExpression, _compiler: object, **_kw: object
) -> str:
    return "passage"


@compiles(_KnowledgeDigestHexExpression, "postgresql")
def _compile_postgresql_digest_hex(
    _element: _KnowledgeDigestHexExpression, _compiler: object, **_kw: object
) -> str:
    return "content_sha256 ~ '^[0-9a-f]{64}$'"


@compiles(_KnowledgeDigestHexExpression)
def _compile_default_digest_hex(
    _element: _KnowledgeDigestHexExpression, _compiler: object, **_kw: object
) -> str:
    return "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)"


@compiles(_KnowledgeChunkDigestExpression, "postgresql")
def _compile_postgresql_chunk_digest(
    _element: _KnowledgeChunkDigestExpression, _compiler: object, **_kw: object
) -> str:
    return "content_sha256 = encode(sha256(convert_to(passage, 'UTF8')), 'hex')"


@compiles(_KnowledgeChunkDigestExpression)
def _compile_default_chunk_digest(
    _element: _KnowledgeChunkDigestExpression, _compiler: object, **_kw: object
) -> str:
    return "content_sha256 = lower(content_sha256)"


_SEARCH_VECTOR_TYPE = Text().with_variant(postgresql.TSVECTOR(), "postgresql")


class KnowledgeSource(Base):
    """Immutable tenant-owned source identity."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "length(trim(source_key)) > 0", name=conv("ck_knowledge_sources_key_nonblank")
        ),
        CheckConstraint(
            "length(trim(title)) > 0", name=conv("ck_knowledge_sources_title_nonblank")
        ),
        CheckConstraint(
            "length(trim(provenance_uri)) > 0", name=conv("ck_knowledge_sources_uri_nonblank")
        ),
        CheckConstraint(
            "length(trim(source_kind)) > 0", name=conv("ck_knowledge_sources_kind_nonblank")
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_knowledge_sources_tenant_id_tenants"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_knowledge_sources_scope_identity"),
        UniqueConstraint("tenant_id", "source_key", name="uq_knowledge_sources_tenant_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_key: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    provenance_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class KnowledgeSourceVersion(Base):
    """Immutable content version whose lifecycle is guarded in PostgreSQL."""

    __tablename__ = "knowledge_source_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name=conv("ck_knowledge_versions_positive_number")),
        CheckConstraint(
            "status IN ('active', 'superseded', 'withdrawn')",
            name=conv("ck_knowledge_versions_status_supported"),
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=conv("ck_knowledge_versions_valid_window"),
        ),
        CheckConstraint(
            "(status = 'active' AND valid_until IS NULL) OR "
            "(status IN ('superseded', 'withdrawn') AND valid_until IS NOT NULL)",
            name=conv("ck_knowledge_versions_terminal_timestamp"),
        ),
        CheckConstraint(
            "length(content_sha256) = 64", name=conv("ck_knowledge_versions_digest_length")
        ),
        CheckConstraint(
            "content_sha256 = lower(content_sha256)",
            name=conv("ck_knowledge_versions_digest_lowercase"),
        ),
        CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name=conv("ck_knowledge_versions_not_self_superseding"),
        ),
        CheckConstraint(
            _KnowledgeDigestHexExpression(),
            name=conv("ck_knowledge_versions_digest_hex"),
        ),
        ForeignKeyConstraint(
            ["source_id", "tenant_id"],
            ["knowledge_sources.id", "knowledge_sources.tenant_id"],
            name="fk_knowledge_versions_source_scope",
        ),
        ForeignKeyConstraint(
            ["supersedes_version_id", "source_id", "tenant_id"],
            [
                "knowledge_source_versions.id",
                "knowledge_source_versions.source_id",
                "knowledge_source_versions.tenant_id",
            ],
            name="fk_knowledge_versions_supersedes_same_source",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_knowledge_versions_scope_identity"),
        UniqueConstraint("id", "source_id", name="uq_knowledge_versions_source_identity"),
        UniqueConstraint(
            "id", "source_id", "tenant_id", name="uq_knowledge_versions_source_scope_identity"
        ),
        UniqueConstraint("source_id", "version_no", name="uq_knowledge_versions_source_number"),
        Index("ix_knowledge_versions_tenant_status", "tenant_id", "status", "valid_from"),
        Index(
            "uq_knowledge_versions_active_source",
            "tenant_id",
            "source_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class KnowledgeVersionPurpose(Base):
    """Purpose admission for one immutable source version."""

    __tablename__ = "knowledge_version_purposes"
    __table_args__ = (
        CheckConstraint(
            "purpose = 'support_assistance'", name=conv("ck_knowledge_purposes_supported")
        ),
        ForeignKeyConstraint(
            ["source_version_id", "tenant_id"],
            ["knowledge_source_versions.id", "knowledge_source_versions.tenant_id"],
            name="fk_knowledge_purposes_version_scope",
        ),
    )

    source_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(64), primary_key=True)


class KnowledgeChunk(Base):
    """Immutable passage with a database-populated lexical search vector."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name=conv("ck_knowledge_chunks_ordinal_nonnegative")),
        CheckConstraint(
            "length(trim(locator)) > 0", name=conv("ck_knowledge_chunks_locator_nonblank")
        ),
        CheckConstraint(
            "length(trim(passage)) > 0 AND length(passage) <= 8000",
            name=conv("ck_knowledge_chunks_passage_bound"),
        ),
        CheckConstraint(
            "length(content_sha256) = 64", name=conv("ck_knowledge_chunks_digest_length")
        ),
        CheckConstraint(
            "content_sha256 = lower(content_sha256)",
            name=conv("ck_knowledge_chunks_digest_lowercase"),
        ),
        CheckConstraint(
            _KnowledgeChunkDigestExpression(),
            name=conv("ck_knowledge_chunks_digest_matches_passage"),
        ),
        CheckConstraint(
            _KnowledgeDigestHexExpression(),
            name=conv("ck_knowledge_chunks_digest_hex"),
        ),
        ForeignKeyConstraint(
            ["source_version_id", "tenant_id"],
            ["knowledge_source_versions.id", "knowledge_source_versions.tenant_id"],
            name="fk_knowledge_chunks_version_scope",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_knowledge_chunks_scope_identity"),
        UniqueConstraint(
            "source_version_id", "ordinal", name="uq_knowledge_chunks_version_ordinal"
        ),
        Index("ix_knowledge_chunks_tenant_version", "tenant_id", "source_version_id", "ordinal"),
        Index(
            "ix_knowledge_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(512), nullable=False)
    passage: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        _SEARCH_VECTOR_TYPE,
        Computed(_KnowledgeSearchVectorExpression(), persisted=True),
        nullable=False,
    )


class KnowledgeChunkACL(Base):
    """Immutable chunk-level ACL subject admission."""

    __tablename__ = "knowledge_chunk_acl"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chunk_id", "tenant_id"],
            ["knowledge_chunks.id", "knowledge_chunks.tenant_id"],
            name="fk_knowledge_chunk_acl_chunk_scope",
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    acl_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)


__all__ = [
    "KnowledgeChunk",
    "KnowledgeChunkACL",
    "KnowledgeSource",
    "KnowledgeSourceVersion",
    "KnowledgeVersionPurpose",
]
