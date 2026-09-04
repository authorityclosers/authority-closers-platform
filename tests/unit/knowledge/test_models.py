"""Metadata parity tests for the immutable knowledge snapshot schema."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Computed, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from ac_platform.db.models import model_metadata

KNOWLEDGE_TABLES = {
    "knowledge_sources",
    "knowledge_source_versions",
    "knowledge_version_purposes",
    "knowledge_chunks",
    "knowledge_chunk_acl",
}


def test_knowledge_models_are_registered_with_faithful_schema_metadata() -> None:
    metadata = model_metadata()

    assert set(metadata.tables) >= KNOWLEDGE_TABLES
    versions = metadata.tables["knowledge_source_versions"]
    chunks = metadata.tables["knowledge_chunks"]
    assert {
        constraint.name
        for constraint in versions.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_knowledge_versions_positive_number",
        "ck_knowledge_versions_status_supported",
        "ck_knowledge_versions_valid_window",
        "ck_knowledge_versions_terminal_timestamp",
        "ck_knowledge_versions_digest_length",
        "ck_knowledge_versions_digest_lowercase",
        "ck_knowledge_versions_digest_hex",
        "ck_knowledge_versions_not_self_superseding",
    }
    assert {
        constraint.name
        for constraint in chunks.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_knowledge_chunks_ordinal_nonnegative",
        "ck_knowledge_chunks_locator_nonblank",
        "ck_knowledge_chunks_passage_bound",
        "ck_knowledge_chunks_digest_length",
        "ck_knowledge_chunks_digest_lowercase",
        "ck_knowledge_chunks_digest_matches_passage",
        "ck_knowledge_chunks_digest_hex",
    }
    assert {
        constraint.name
        for constraint in versions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    } == {
        "fk_knowledge_versions_source_scope",
        "fk_knowledge_versions_supersedes_same_source",
    }
    assert {
        constraint.name
        for constraint in versions.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        "uq_knowledge_versions_scope_identity",
        "uq_knowledge_versions_source_identity",
        "uq_knowledge_versions_source_scope_identity",
        "uq_knowledge_versions_source_number",
    }
    assert {index.name for index in versions.indexes} == {
        "ix_knowledge_versions_tenant_status",
        "uq_knowledge_versions_active_source",
    }
    assert {index.name for index in chunks.indexes} == {
        "ix_knowledge_chunks_tenant_version",
        "ix_knowledge_chunks_search_vector",
    }


def test_knowledge_chunk_search_vector_matches_postgresql_generated_column() -> None:
    chunks = model_metadata().tables["knowledge_chunks"]
    search_vector = chunks.c.search_vector

    assert isinstance(search_vector.computed, Computed)
    create_table = str(CreateTable(chunks).compile(dialect=postgresql.dialect()))
    search_index = next(
        index for index in chunks.indexes if index.name == "ix_knowledge_chunks_search_vector"
    )
    create_index = str(CreateIndex(search_index).compile(dialect=postgresql.dialect()))
    assert (
        "TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, passage)) STORED NOT NULL"
        in create_table
    )
    assert "USING gin" in create_index
