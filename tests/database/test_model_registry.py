from __future__ import annotations

from pathlib import Path

from sqlalchemy import UniqueConstraint

from ac_platform.db.models import model_metadata


def test_g1_model_registry_contains_every_migrated_table() -> None:
    expected = {
        "persons",
        "password_credentials",
        "email_challenges",
        "email_login_codes",
        "sales_xray_profiles",
        "reviewer_auth_challenges",
        "provider_identities",
        "sessions",
        "deletion_requests",
        "authentication_replays",
        "provider_authorization_transactions",
        "identity_command_idempotency",
        "tenants",
        "memberships",
        "academy_public_profiles",
        "community_public_profiles",
        "academy_leaderboard_preferences",
        "app_update_read_receipts",
        "capability_grants",
        "capability_revocations",
        "programs",
        "program_versions",
        "catalog_authoring_commands",
        "catalog_publish_commands",
        "modules",
        "module_prerequisites",
        "activities",
        "learner_version_pins",
        "enrollments",
        "command_idempotency",
        "enrollment_provenance",
        "entitlements",
        "activity_progress",
        "activity_drafts",
        "playback_sessions",
        "video_watch_intervals",
        "learning_evidence",
        "evidence_submissions",
        "evidence_corrections",
        "learning_progress_projections",
        "completion_snapshots",
        "course_completion_certificates",
        "certificate_events",
        "outbox_events",
        "jobs",
        "knowledge_chunk_acl",
        "knowledge_chunks",
        "knowledge_source_versions",
        "knowledge_sources",
        "knowledge_version_purposes",
        "provider_inbox",
        "audit_events",
        "learning_command_idempotency",
        "enrollment_eligibility_facts",
        "certificate_command_idempotency",
        "operations_recovery_state",
        "audit_chain_heads",
        "media_assets",
        "media_versions",
        "media_upload_intents",
        "studio_video_uploads",
        "media_renditions",
        "media_caption_tracks",
        "media_playback_grants",
        "media_resume_states",
        "media_webhook_inbox",
        "media_quota_usage",
        "activity_media_bindings",
        "learning_plan_items",
        "learning_next_action_projections",
        "analytics_events",
        "practice_profiles",
        "practice_set_versions",
        "practice_attempts",
        "practice_responses",
        "practice_feedback_acks",
        "practice_participations",
        "practice_reward_claims",
        "practice_ledger_entries",
        "practice_commands",
        "practice_focus_runs",
        "practice_focus_events",
        "conversation_permissions",
        "conversation_recordings",
        "conversation_runs",
        "conversation_checkpoints",
        "conversation_minute_accounts",
        "conversation_budget_accounts",
        "conversation_quotes",
        "conversation_commands",
        "conversation_quote_acceptances",
        "conversation_reviews",
        "conversation_review_cursors",
        "conversation_review_assignments",
        "conversation_review_revocations",
        "conversation_review_feedback",
        "conversation_review_invitations",
        "conversation_review_invitation_revocations",
        "conversation_review_invitation_acceptances",
        "conversation_provider_configurations",
        "conversation_provider_activations",
        "conversation_report_drafts",
        "conversation_inference_tasks",
        "community_discovery_preferences",
        "community_connections",
        "community_connection_events",
        "community_blocks",
        "community_reports",
        "conversation_processing_plans",
        "conversation_plan_stage_authorizations",
        "conversation_processing_continuations",
        "conversation_execution_controls",
        "conversation_visitors",
        "conversation_visitor_claims",
        "conversation_acquisition_usage",
        "conversation_acquisition_settlements",
        "conversation_processing_principals",
        "conversation_processing_leases",
        "conversation_guest_submissions",
        "conversation_analysis_settings",
        "conversation_retained_c5_versions",
    }

    assert set(model_metadata().tables) == expected


def test_media_caption_supersession_target_is_uniquely_addressable() -> None:
    table = model_metadata().tables["media_caption_tracks"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("tenant_id", "version_id", "id") in unique_columns


def test_media_upload_intent_model_keeps_fail_closed_checks() -> None:
    table = model_metadata().tables["media_upload_intents"]
    check_names = {constraint.name for constraint in table.constraints}

    assert "ck_media_upload_intents_request_fingerprint_sha256" in check_names
    assert "ck_media_upload_intents_state_supported" in check_names


def test_academy_public_profile_migration_is_forward_only() -> None:
    migration = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260910_0027_academy_public_profiles.py"
    ).read_text(encoding="utf-8")

    downgrade = migration.split("def downgrade() -> None:", 1)[1]
    assert "raise RuntimeError" in downgrade
    assert "drop_table" not in downgrade


def test_global_community_identity_migration_is_forward_only_and_collision_safe() -> None:
    migration = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260910_0028_global_community_identity.py"
    ).read_text(encoding="utf-8")

    downgrade = migration.split("def downgrade() -> None:", 1)[1]
    assert "raise RuntimeError" in downgrade
    assert "drop_table" not in downgrade
    assert "count(DISTINCT username) > 1" in migration
    assert "count(DISTINCT person_id) > 1" in migration
    assert "No username was selected or renamed" in migration


def test_app_update_receipts_are_unique_append_only_and_forward_only() -> None:
    table = model_metadata().tables["app_update_read_receipts"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("tenant_id", "person_id", "release_id") in unique_columns
    indexes = {
        (index.name, tuple(column.name for column in index.columns)) for index in table.indexes
    }
    assert (
        "ix_app_update_read_receipts_learner_read_at",
        ("tenant_id", "person_id", "read_at"),
    ) in indexes

    migration = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260910_0029_app_update_read_receipts.py"
    ).read_text(encoding="utf-8")
    downgrade = migration.split("def downgrade() -> None:", 1)[1]
    assert "raise RuntimeError" in downgrade
    assert "drop_table" not in downgrade
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "app_update_read_receipts_append_only" in migration
