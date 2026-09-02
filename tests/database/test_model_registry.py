from __future__ import annotations

from sqlalchemy import UniqueConstraint

from ac_platform.db.models import model_metadata


def test_g1_model_registry_contains_every_migrated_table() -> None:
    expected = {
        "persons",
        "password_credentials",
        "email_challenges",
        "provider_identities",
        "sessions",
        "deletion_requests",
        "authentication_replays",
        "provider_authorization_transactions",
        "identity_command_idempotency",
        "tenants",
        "memberships",
        "programs",
        "program_versions",
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
        "media_renditions",
        "media_caption_tracks",
        "media_playback_grants",
        "media_resume_states",
        "media_webhook_inbox",
        "media_quota_usage",
        "learning_plan_items",
        "learning_next_action_projections",
        "analytics_events",
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
