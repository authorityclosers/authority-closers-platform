#!/usr/bin/env python3
"""Bounded logical PostgreSQL backup pipeline for the live application releases."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import hashlib
import json
import os
import queue
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

try:
    import grp
except ModuleNotFoundError:  # pragma: no cover - only used on the Windows dev host
    grp = None  # type: ignore[assignment]

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - only used on the Windows dev host
    fcntl = None  # type: ignore[assignment]


APPLICATION_ROOT = Path("/srv/authority-closers/application")
FOUNDATION_CURRENT = Path("/srv/authority-closers/current")
FOUNDATION_SCOPES = Path("/var/lib/authority-closers/foundation-scopes")
BACKUP_ROOT = Path("/srv/authority-closers/backups/application")
LOCK_ROOT = Path("/run/lock")
PRIVATE_LOCK_ROOT = LOCK_ROOT / "authority-closers"
INFISICAL_RUN = "/usr/local/sbin/ac-infisical-run"
R2_USAGE_GUARD = "/usr/local/sbin/ac-r2-usage-guard"
RESTIC_LOGICAL_BACKUP = "/usr/local/sbin/ac-infisical-run-backup"
RESTIC_LOGICAL_INNER = "/usr/local/libexec/authority-closers/ac-restic-postgres-backup-inner"
PG_DUMP_TIMEOUT_SECONDS = 4 * 60
PG_DUMP_KILL_AFTER_SECONDS = 30
PG_RESTORE_LIST_TIMEOUT_SECONDS = 60
SNAPSHOT_HOLDER_START_TIMEOUT_SECONDS = 30
SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS = 10 * 60
SNAPSHOT_HOLDER_ROLLBACK_TIMEOUT_SECONDS = 30
R2_GUARD_HTTP_RETRY_MAX_SECONDS = 75
R2_GUARD_HTTP_CALLS = 2
R2_GUARD_UNIT_TIMEOUT_SECONDS = R2_GUARD_HTTP_RETRY_MAX_SECONDS * R2_GUARD_HTTP_CALLS + 30
R2_GUARD_STOP_TIMEOUT_SECONDS = 30
R2_GUARD_CLIENT_GRACE_SECONDS = 30
R2_GUARD_CLIENT_TIMEOUT_SECONDS = (
    R2_GUARD_UNIT_TIMEOUT_SECONDS + R2_GUARD_STOP_TIMEOUT_SECONDS + R2_GUARD_CLIENT_GRACE_SECONDS
)
RESTIC_UPLOAD_TIMEOUT_SECONDS = 4 * 60
RESTIC_REPOSITORY_LOCK_WAIT_SECONDS = 60
RESTIC_REPOSITORY_LOCK_POLL_SECONDS = 0.25
UPLOAD_DIAGNOSTIC_MAX_BYTES = 8192
OPERATION_KILL_AFTER_SECONDS = 30
RESTIC_TAG = "authority-closers-postgres-logical"
ENVIRONMENTS = ("staging", "production")
PROFILE_KEYS = (
    "AC_COMPOSE_PROJECT",
    "AC_ENVIRONMENT",
    "AC_STATE_ROOT",
    "AC_PUBLIC_APP_URL",
    "AC_ADMIN_APP_URL",
    "AC_COACH_APP_URL",
    "AC_API_URL",
    "AC_API_HOST",
    "AC_TRUSTED_PROXY_ADDRESSES",
    "AC_EDGE_API_ALIAS",
    "AC_EDGE_LEARNER_ALIAS",
    "AC_EDGE_ADMIN_ALIAS",
    "AC_EDGE_COACH_ALIAS",
    "AC_EXTERNAL_SIDE_EFFECTS_HOLD",
    "AC_EMAIL_PROVIDER",
    "AC_RELEASE_ID",
    "AC_API_IMAGE",
    "AC_LEARNER_IMAGE",
    "AC_ADMIN_IMAGE",
    "AC_COACH_IMAGE",
)
SECRET_KEYS = (
    "AC_DATABASE_URL",
    "AC_DATABASE_MIGRATOR_URL",
    "AC_POSTGRES_OWNER_PASSWORD",
    "AC_DB_MIGRATOR_PASSWORD",
    "AC_DB_RUNTIME_PASSWORD",
    "AC_DB_BACKUP_PASSWORD",
)
EXPECTED_PROFILE_VALUES = {
    "staging": {
        "AC_COMPOSE_PROJECT": "ac-application-staging",
        "AC_ENVIRONMENT": "staging",
        "AC_STATE_ROOT": "/srv/authority-closers/state/application/staging",
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "false",
        "AC_EMAIL_PROVIDER": "resend",
    },
    "production": {
        "AC_COMPOSE_PROJECT": "ac-application-production",
        "AC_ENVIRONMENT": "production",
        "AC_STATE_ROOT": "/srv/authority-closers/state/application/production",
    },
}
POLICY_KEYS = {
    "R2_MAX_STANDARD_BYTES",
    "R2_WARN_STANDARD_BYTES",
    "R2_MAX_CLASS_A_MONTH",
    "R2_MAX_CLASS_B_MONTH",
    "R2_FORBID_INFREQUENT_ACCESS",
    "R2_BACKUP_BUCKET",
    "R2_OBJECT_BUCKET",
    "R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES",
    "R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT",
    "R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS",
}
ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@+%=-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAPTURE_DIR_RE = re.compile(r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9]+-(staging|production)$")
EXPORTED_SNAPSHOT_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[0-9]+$")
SNAPSHOT_HOLDER_START_SQL = (
    b"BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;\nSELECT pg_export_snapshot();\n"
)
PARITY_TABLES = (
    "alembic_version",
    "persons",
    "tenants",
    "memberships",
    "programs",
    "program_versions",
    "modules",
    "module_prerequisites",
    "activities",
    "learner_version_pins",
    "enrollments",
    "enrollment_eligibility_facts",
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
    "course_completion_certificates",
    "completion_snapshots",
    "certificate_events",
    "certificate_command_idempotency",
    "command_idempotency",
    "learning_command_idempotency",
    "provider_identities",
    "sessions",
    "deletion_requests",
    "authentication_replays",
    "provider_authorization_transactions",
    "outbox_events",
    "jobs",
    "operations_recovery_state",
    "provider_inbox",
    "audit_events",
    "audit_chain_heads",
)

# Explicit compatibility catalogue, not a lexical version comparison or table
# presence heuristic. Any later migration needs a reviewed parity decision.
LEGACY_PARITY_MIGRATION_HEADS = frozenset(
    {
        "20260830_0006",
        "20260830_0007",
        "20260830_0008",
        "20260830_0009",
        "20260830_0010",
        "20260830_0011",
        "20260901_0012",
        "20260902_0013",
        "20260902_0014",
        "20260903_0015",
        "20260903_0016",
        "20260904_0017",
        "20260904_0018",
    }
)
CAPABILITY_PARITY_MIGRATION_HEAD = "20260907_0019"
CAPABILITY_PARITY_CONTRACT = "ac-postgres-parity-v2"
CAPABILITY_PARITY_TABLES = PARITY_TABLES + ("capability_grants", "capability_revocations")


PRACTICE_PARITY_MIGRATION_HEAD = "20260908_0020"
PRACTICE_PARITY_CONTRACT = "ac-postgres-parity-v3"
PRACTICE_PARITY_TABLES = CAPABILITY_PARITY_TABLES + (
    "practice_set_versions",
    "practice_attempts",
    "practice_profiles",
    "practice_responses",
    "practice_commands",
    "practice_feedback_acks",
    "practice_participations",
    "practice_reward_claims",
    "practice_ledger_entries",
)
FOCUS_PARITY_MIGRATION_HEAD = "20260908_0021"
FOCUS_PARITY_CONTRACT = "ac-postgres-parity-v4"
FOCUS_PARITY_TABLES = PRACTICE_PARITY_TABLES + ("practice_focus_runs", "practice_focus_events")
AUTHORING_PARITY_MIGRATION_HEAD = "20260908_0022"
AUTHORING_PARITY_CONTRACT = "ac-postgres-parity-v5"
AUTHORING_PARITY_TABLES = FOCUS_PARITY_TABLES + ("catalog_authoring_commands",)
# 20260909_0023 extends the immutable authoring-command operation catalogue,
# and 20260909_0024/0025 add the reviewed Studio library index and course
# creation operation without changing the backed-up table inventory or parity
# contract. Each exact head remains an explicit reviewed compatibility row.
REVISION_PARITY_MIGRATION_HEAD = "20260909_0023"
REVISION_PARITY_CONTRACT = AUTHORING_PARITY_CONTRACT
REVISION_PARITY_TABLES = AUTHORING_PARITY_TABLES
MEDIA_LIBRARY_PARITY_MIGRATION_HEAD = "20260909_0024"
MEDIA_LIBRARY_PARITY_CONTRACT = REVISION_PARITY_CONTRACT
MEDIA_LIBRARY_PARITY_TABLES = REVISION_PARITY_TABLES
COURSE_CREATION_PARITY_MIGRATION_HEAD = "20260909_0025"
COURSE_CREATION_PARITY_CONTRACT = MEDIA_LIBRARY_PARITY_CONTRACT
COURSE_CREATION_PARITY_TABLES = MEDIA_LIBRARY_PARITY_TABLES
# These heads add canonical rows. They must not reuse the older 53-table
# contract or silently omit upload admission/public identity from restore proof.
STUDIO_VIDEO_PARITY_MIGRATION_HEAD = "20260910_0026"
STUDIO_VIDEO_PARITY_CONTRACT = "ac-postgres-parity-v6"
STUDIO_VIDEO_PARITY_TABLES = COURSE_CREATION_PARITY_TABLES + ("studio_video_uploads",)
COMMUNITY_PARITY_MIGRATION_HEAD = "20260910_0027"
COMMUNITY_PARITY_CONTRACT = "ac-postgres-parity-v7"
COMMUNITY_PARITY_TABLES = STUDIO_VIDEO_PARITY_TABLES + ("academy_public_profiles",)
GLOBAL_COMMUNITY_PARITY_MIGRATION_HEAD = "20260910_0028"
GLOBAL_COMMUNITY_PARITY_CONTRACT = "ac-postgres-parity-v8"
GLOBAL_COMMUNITY_PARITY_TABLES = COMMUNITY_PARITY_TABLES + (
    "community_public_profiles",
    "academy_leaderboard_preferences",
)
APP_UPDATES_PARITY_MIGRATION_HEAD = "20260910_0029"
APP_UPDATES_PARITY_CONTRACT = "ac-postgres-parity-v9"
APP_UPDATES_PARITY_TABLES = GLOBAL_COMMUNITY_PARITY_TABLES + ("app_update_read_receipts",)
SALES_XRAY_PARITY_MIGRATION_HEAD = "20260913_0030"
SALES_XRAY_PARITY_CONTRACT = "ac-postgres-parity-v10"
SALES_XRAY_PARITY_NEW_TABLES = (
    "conversation_budget_accounts",
    "conversation_review_cursors",
    "conversation_minute_accounts",
    "conversation_permissions",
    "conversation_recordings",
    "conversation_checkpoints",
    "conversation_commands",
    "conversation_quotes",
    "conversation_runs",
    "conversation_reviews",
    "conversation_quote_acceptances",
    "conversation_provider_configurations",
    "conversation_report_drafts",
)
SALES_XRAY_PARITY_TABLES = APP_UPDATES_PARITY_TABLES + SALES_XRAY_PARITY_NEW_TABLES
INFERENCE_PARITY_MIGRATION_HEAD = "20260913_0031"
INFERENCE_PARITY_CONTRACT = "ac-postgres-parity-v11"
INFERENCE_PARITY_NEW_TABLES = ("conversation_inference_tasks",)
INFERENCE_PARITY_TABLES = SALES_XRAY_PARITY_TABLES + INFERENCE_PARITY_NEW_TABLES
PLANS_PARITY_MIGRATION_HEAD = "20260913_0032"
PLANS_PARITY_CONTRACT = "ac-postgres-parity-v12"
PLANS_PARITY_NEW_TABLES = (
    "conversation_processing_plans",
    "conversation_plan_stage_authorizations",
)
PLANS_PARITY_TABLES = INFERENCE_PARITY_TABLES + PLANS_PARITY_NEW_TABLES
COMMUNITY_CONNECTIONS_PARITY_MIGRATION_HEAD = "20260913_0033"
COMMUNITY_CONNECTIONS_PARITY_CONTRACT = "ac-postgres-parity-v13"
COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES = (
    "community_discovery_preferences",
    "community_connections",
    "community_connection_events",
    "community_blocks",
    "community_reports",
)
COMMUNITY_CONNECTIONS_PARITY_TABLES = PLANS_PARITY_TABLES + COMMUNITY_CONNECTIONS_PARITY_NEW_TABLES
REVIEWS_PARITY_MIGRATION_HEAD = "20260913_0034"
REVIEWS_PARITY_CONTRACT = "ac-postgres-parity-v14"
REVIEWS_PARITY_NEW_TABLES = (
    "conversation_review_assignments",
    "conversation_review_revocations",
    "conversation_review_feedback",
)
REVIEWS_PARITY_TABLES = COMMUNITY_CONNECTIONS_PARITY_TABLES + REVIEWS_PARITY_NEW_TABLES
REVIEW_INVITATIONS_PARITY_MIGRATION_HEAD = "20260913_0035"
REVIEW_INVITATIONS_PARITY_CONTRACT = "ac-postgres-parity-v15"
REVIEW_INVITATIONS_PARITY_NEW_TABLES = (
    "conversation_review_invitations",
    "conversation_review_invitation_revocations",
    "conversation_review_invitation_acceptances",
)
REVIEW_INVITATIONS_PARITY_TABLES = REVIEWS_PARITY_TABLES + REVIEW_INVITATIONS_PARITY_NEW_TABLES
ACQUISITION_PARITY_MIGRATION_HEAD = "20260914_0036"
ACQUISITION_PARITY_CONTRACT = "ac-postgres-parity-v16"
ACQUISITION_PARITY_NEW_TABLES = (
    "conversation_visitors",
    "conversation_visitor_claims",
    "conversation_acquisition_usage",
    "conversation_acquisition_settlements",
)
ACQUISITION_PARITY_TABLES = REVIEW_INVITATIONS_PARITY_TABLES + ACQUISITION_PARITY_NEW_TABLES
PROCESSING_OWNERSHIP_PARITY_MIGRATION_HEAD = "20260914_0037"
PROCESSING_OWNERSHIP_PARITY_CONTRACT = "ac-postgres-parity-v17"
PROCESSING_OWNERSHIP_PARITY_NEW_TABLES = (
    "conversation_processing_principals",
    "conversation_processing_leases",
    "conversation_guest_submissions",
)
PROCESSING_OWNERSHIP_PARITY_TABLES = (
    ACQUISITION_PARITY_TABLES + PROCESSING_OWNERSHIP_PARITY_NEW_TABLES
)
REVIEWER_IDENTITY_PARITY_MIGRATION_HEAD = "20260914_0038"
REVIEWER_IDENTITY_PARITY_CONTRACT = "ac-postgres-parity-v18"
REVIEWER_IDENTITY_PARITY_NEW_TABLES = ("reviewer_auth_challenges",)
REVIEWER_IDENTITY_PARITY_TABLES = (
    PROCESSING_OWNERSHIP_PARITY_TABLES + REVIEWER_IDENTITY_PARITY_NEW_TABLES
)
PROVIDER_ACTIVATION_PARITY_MIGRATION_HEAD = "20260914_0039"
PROVIDER_ACTIVATION_PARITY_CONTRACT = "ac-postgres-parity-v19"
PROVIDER_ACTIVATION_PARITY_NEW_TABLES = ("conversation_provider_activations",)
PROVIDER_ACTIVATION_PARITY_TABLES = (
    REVIEWER_IDENTITY_PARITY_TABLES + PROVIDER_ACTIVATION_PARITY_NEW_TABLES
)
PROCESSING_CONTINUATION_PARITY_MIGRATION_HEAD = "20260914_0040"
PROCESSING_CONTINUATION_PARITY_CONTRACT = "ac-postgres-parity-v20"
PROCESSING_CONTINUATION_PARITY_NEW_TABLES = ("conversation_processing_continuations",)
PROCESSING_CONTINUATION_PARITY_TABLES = (
    PROVIDER_ACTIVATION_PARITY_TABLES + PROCESSING_CONTINUATION_PARITY_NEW_TABLES
)
EXECUTION_CONTROL_PARITY_MIGRATION_HEAD = "20260914_0041"
EXECUTION_CONTROL_PARITY_CONTRACT = "ac-postgres-parity-v21"
EXECUTION_CONTROL_PARITY_NEW_TABLES = ("conversation_execution_controls",)
EXECUTION_CONTROL_PARITY_TABLES = (
    PROCESSING_CONTINUATION_PARITY_TABLES + EXECUTION_CONTROL_PARITY_NEW_TABLES
)
ANALYSIS_SETTINGS_PARITY_MIGRATION_HEAD = "20260915_0042"
ANALYSIS_SETTINGS_PARITY_CONTRACT = "ac-postgres-parity-v22"
ANALYSIS_SETTINGS_PARITY_NEW_TABLES = ("conversation_analysis_settings",)
ANALYSIS_SETTINGS_PARITY_TABLES = (
    EXECUTION_CONTROL_PARITY_TABLES + ANALYSIS_SETTINGS_PARITY_NEW_TABLES
)
RETAINED_C5_RECOVERY_PARITY_MIGRATION_HEAD = "20260915_0043"
RETAINED_C5_RECOVERY_PARITY_CONTRACT = "ac-postgres-parity-v23"
RETAINED_C5_RECOVERY_PARITY_NEW_TABLES = ("conversation_retained_c5_versions",)
RETAINED_C5_RECOVERY_PARITY_TABLES = (
    ANALYSIS_SETTINGS_PARITY_TABLES + RETAINED_C5_RECOVERY_PARITY_NEW_TABLES
)
ANALYSIS_LANGUAGE_PARITY_MIGRATION_HEAD = "20260923_0044"
ANALYSIS_LANGUAGE_PARITY_CONTRACT = "ac-postgres-parity-v24"
ANALYSIS_LANGUAGE_PARITY_TABLES = RETAINED_C5_RECOVERY_PARITY_TABLES
EMAIL_LOGIN_CODES_PARITY_MIGRATION_HEAD = "20260923_0045"
EMAIL_LOGIN_CODES_PARITY_CONTRACT = "ac-postgres-parity-v25"
EMAIL_LOGIN_CODES_PARITY_NEW_TABLES = ("email_login_codes",)
EMAIL_LOGIN_CODES_PARITY_TABLES = (
    ANALYSIS_LANGUAGE_PARITY_TABLES + EMAIL_LOGIN_CODES_PARITY_NEW_TABLES
)
SALES_XRAY_PROFILES_PARITY_MIGRATION_HEAD = "20260923_0046"
SALES_XRAY_PROFILES_PARITY_CONTRACT = "ac-postgres-parity-v26"
SALES_XRAY_PROFILES_PARITY_NEW_TABLES = ("sales_xray_profiles",)
SALES_XRAY_PROFILES_PARITY_TABLES = (
    EMAIL_LOGIN_CODES_PARITY_TABLES + SALES_XRAY_PROFILES_PARITY_NEW_TABLES
)
COACHING_DEPTH_PARITY_MIGRATION_HEAD = "20260924_0047"
COACHING_DEPTH_PARITY_CONTRACT = "ac-postgres-parity-v27"
COACHING_DEPTH_PARITY_TABLES = SALES_XRAY_PROFILES_PARITY_TABLES
EMAIL_ACKNOWLEDGEMENT_PARITY_MIGRATION_HEAD = "20260924_0048"
EMAIL_ACKNOWLEDGEMENT_PARITY_CONTRACT = "ac-postgres-parity-v28"
EMAIL_ACKNOWLEDGEMENT_PARITY_TABLES = COACHING_DEPTH_PARITY_TABLES
COACHING_V6_SELECTION_PARITY_MIGRATION_HEAD = "20260925_0049"
COACHING_V6_SELECTION_PARITY_CONTRACT = "ac-postgres-parity-v29"
COACHING_V6_SELECTION_PARITY_TABLES = EMAIL_ACKNOWLEDGEMENT_PARITY_TABLES
SUBMISSION_LABELS_PARITY_MIGRATION_HEAD = "20260925_0050"
SUBMISSION_LABELS_PARITY_CONTRACT = "ac-postgres-parity-v30"
SUBMISSION_LABELS_PARITY_NEW_TABLES = ("conversation_submission_label_revisions",)
SUBMISSION_LABELS_PARITY_TABLES = (
    COACHING_V6_SELECTION_PARITY_TABLES + SUBMISSION_LABELS_PARITY_NEW_TABLES
)
SOURCE_OBJECTS_PARITY_MIGRATION_HEAD = "20260928_0051"
SOURCE_OBJECTS_PARITY_CONTRACT = "ac-postgres-parity-v31"
SOURCE_OBJECTS_PARITY_TABLES = SUBMISSION_LABELS_PARITY_TABLES + (
    "conversation_source_objects",
    "conversation_source_references",
)
CANARY_PARITY_MIGRATION_HEAD = "20260929_0052"
CANARY_PARITY_CONTRACT = "ac-postgres-parity-v32"
CANARY_PARITY_TABLES = SOURCE_OBJECTS_PARITY_TABLES + ("conversation_canary_submissions",)
GOOGLE_PROFILES_PARITY_MIGRATION_HEAD = "20260930_0053"
GOOGLE_PROFILES_PARITY_CONTRACT = "ac-postgres-parity-v33"
GOOGLE_PROFILES_PARITY_TABLES = CANARY_PARITY_TABLES + ("person_google_profiles",)
ORGANISATIONS_PARITY_MIGRATION_HEAD = "20260930_0054"
ORGANISATIONS_PARITY_CONTRACT = "ac-postgres-parity-v34"
ORGANISATIONS_PARITY_TABLES = GOOGLE_PROFILES_PARITY_TABLES + (
    "organisations",
    "organisation_domain_settings",
    "organisation_invites",
)
PLATFORM_RELEASE_MANAGE_PARITY_MIGRATION_HEAD = "20260930_0060"
PLATFORM_RELEASE_MANAGE_PARITY_CONTRACT = ORGANISATIONS_PARITY_CONTRACT
PLATFORM_RELEASE_MANAGE_PARITY_TABLES = ORGANISATIONS_PARITY_TABLES
JOB_FAILURE_DETAIL_PARITY_MIGRATION_HEAD = "20260930_0061"
JOB_FAILURE_DETAIL_PARITY_CONTRACT = "ac-postgres-parity-v35"
JOB_FAILURE_DETAIL_PARITY_TABLES = PLATFORM_RELEASE_MANAGE_PARITY_TABLES
BILLING_LEDGER_PARITY_MIGRATION_HEAD = "20261001_0062"
BILLING_LEDGER_PARITY_CONTRACT = "ac-postgres-parity-v36"
BILLING_LEDGER_PARITY_TABLES = JOB_FAILURE_DETAIL_PARITY_TABLES + (
    "billing_accounts",
    "billing_ledger_entries",
)
BILLING_ORDERS_PARITY_MIGRATION_HEAD = "20261001_0063"
BILLING_ORDERS_PARITY_CONTRACT = "ac-postgres-parity-v37"
BILLING_ORDERS_PARITY_TABLES = BILLING_LEDGER_PARITY_TABLES + (
    "billing_provider_settings",
    "billing_orders",
    "billing_payment_events",
    "billing_order_events",
    "billing_command_idempotency",
)
BILLING_SUBSCRIPTIONS_PARITY_MIGRATION_HEAD = "20261001_0064"
BILLING_SUBSCRIPTIONS_PARITY_CONTRACT = "ac-postgres-parity-v38"
BILLING_SUBSCRIPTIONS_PARITY_TABLES = BILLING_ORDERS_PARITY_TABLES + (
    "billing_subscriptions",
    "billing_subscription_events",
    "billing_periods",
    "billing_refund_events",
)
PLAN_CATALOGUE_PARITY_MIGRATION_HEAD = "20261002_0065"
PLAN_CATALOGUE_PARITY_CONTRACT = "ac-postgres-parity-v39"
PLAN_CATALOGUE_PARITY_TABLES = BILLING_SUBSCRIPTIONS_PARITY_TABLES + ("plans",)
PLATFORM_BILLING_MANAGE_PARITY_MIGRATION_HEAD = "20261002_0066"
PLATFORM_BILLING_MANAGE_PARITY_CONTRACT = PLAN_CATALOGUE_PARITY_CONTRACT
PLATFORM_BILLING_MANAGE_PARITY_TABLES = PLAN_CATALOGUE_PARITY_TABLES
SENSITIVE_SEGMENT_MARKS_PARITY_MIGRATION_HEAD = "20261002_0067"
SENSITIVE_SEGMENT_MARKS_PARITY_CONTRACT = "ac-postgres-parity-v40"
SENSITIVE_SEGMENT_MARKS_PARITY_TABLES = PLATFORM_BILLING_MANAGE_PARITY_TABLES + (
    "conversation_sensitive_segment_marks",
)
INACTIVE_PLAN_VALUES_PARITY_MIGRATION_HEAD = "20261003_0068"
INACTIVE_PLAN_VALUES_PARITY_CONTRACT = SENSITIVE_SEGMENT_MARKS_PARITY_CONTRACT
INACTIVE_PLAN_VALUES_PARITY_TABLES = SENSITIVE_SEGMENT_MARKS_PARITY_TABLES
BILLING_INVOICES_PARITY_MIGRATION_HEAD = "20261003_0069"
BILLING_INVOICES_PARITY_CONTRACT = "ac-postgres-parity-v41"
BILLING_INVOICES_PARITY_TABLES = INACTIVE_PLAN_VALUES_PARITY_TABLES + (
    "billing_invoice_counters",
    "billing_buyer_tax_details",
    "billing_invoices",
    "billing_credit_notes",
)
SPEAKER_MAPS_PARITY_MIGRATION_HEAD = "20261003_0070"
SPEAKER_MAPS_PARITY_CONTRACT = "ac-postgres-parity-v42"
SPEAKER_MAPS_PARITY_TABLES = BILLING_INVOICES_PARITY_TABLES + (
    "conversation_speaker_map_revisions",
)
CALL_METRICS_PARITY_MIGRATION_HEAD = "20261003_0071"
CALL_METRICS_PARITY_CONTRACT = "ac-postgres-parity-v43"
CALL_METRICS_PARITY_TABLES = SPEAKER_MAPS_PARITY_TABLES + ("conversation_call_metrics",)
BILLING_CREDITS_PARITY_MIGRATION_HEAD = "20261003_0073"
BILLING_CREDITS_PARITY_CONTRACT = "ac-postgres-parity-v44"
BILLING_CREDITS_PARITY_TABLES = CALL_METRICS_PARITY_TABLES + ("billing_credit_entries",)
PROSPECTS_PARITY_MIGRATION_HEAD = "20261004_0074"
PROSPECTS_PARITY_CONTRACT = "ac-postgres-parity-v45"
PROSPECTS_PARITY_TABLES = BILLING_CREDITS_PARITY_TABLES + (
    "conversation_prospects",
    "conversation_prospect_memberships",
)
PRODUCT_UPDATES_PARITY_MIGRATION_HEAD = "20261004_0075"
PRODUCT_UPDATES_PARITY_CONTRACT = "ac-postgres-parity-v46"
PRODUCT_UPDATES_PARITY_TABLES = PROSPECTS_PARITY_TABLES + (
    "product_updates",
    "update_seen",
    "notifications",
)
# Column-only organisation settings migration preserves the complete table inventory.
ORGANISATION_SETTINGS_PARITY_MIGRATION_HEAD = "20261005_0076"
ORGANISATION_SETTINGS_PARITY_CONTRACT = "ac-postgres-parity-v47"
ORGANISATION_SETTINGS_PARITY_TABLES = PRODUCT_UPDATES_PARITY_TABLES
# Column-only prospect tags migration preserves the complete table inventory.
PROSPECT_TAGS_PARITY_MIGRATION_HEAD = "20261007_0077"
PROSPECT_TAGS_PARITY_CONTRACT = "ac-postgres-parity-v48"
PROSPECT_TAGS_PARITY_TABLES = ORGANISATION_SETTINGS_PARITY_TABLES
COMPANION_DEVICES_PARITY_MIGRATION_HEAD = "20261008_0078"
COMPANION_DEVICES_PARITY_CONTRACT = "ac-postgres-parity-v49"
COMPANION_DEVICES_PARITY_TABLES = PROSPECT_TAGS_PARITY_TABLES + (
    "companion_devices",
    "companion_pairings",
    "companion_refresh_families",
    "companion_credentials",
)
PROSPECT_FIELDS_PARITY_MIGRATION_HEAD = "20261009_0079"
PROSPECT_FIELDS_PARITY_CONTRACT = "ac-postgres-parity-v50"
PROSPECT_FIELDS_PARITY_TABLES = COMPANION_DEVICES_PARITY_TABLES + (
    "conversation_prospect_field_revisions",
)
REPORT_MINUTES_PARITY_MIGRATION_HEAD = "20261010_0080"
REPORT_MINUTES_PARITY_CONTRACT = "ac-postgres-parity-v51"
REPORT_MINUTES_PARITY_TABLES = PROSPECT_FIELDS_PARITY_TABLES + (
    "conversation_report_minute_events",
)
RECORDING_IMPORTS_PARITY_MIGRATION_HEAD = "20261011_0081"
RECORDING_IMPORTS_PARITY_CONTRACT = "ac-postgres-parity-v52"
RECORDING_IMPORTS_PARITY_TABLES = REPORT_MINUTES_PARITY_TABLES + (
    "conversation_recording_imports",
    "conversation_recording_import_items",
)
SYNTHETIC_SANDBOX_PARITY_MIGRATION_HEAD = "20261011_0082"
SYNTHETIC_SANDBOX_PARITY_CONTRACT = "ac-postgres-parity-v53"
SYNTHETIC_SANDBOX_PARITY_TABLES = RECORDING_IMPORTS_PARITY_TABLES + (
    "conversation_sandbox_organisations",
    "conversation_synthetic_records",
)
REVIEW_LABELS_PARITY_MIGRATION_HEAD = "20261011_0083"
REVIEW_LABELS_PARITY_CONTRACT = "ac-postgres-parity-v54"
REVIEW_LABELS_PARITY_TABLES = SYNTHETIC_SANDBOX_PARITY_TABLES + ("conversation_review_labels",)
INSIGHT_CALLS_PARITY_MIGRATION_HEAD = "20261011_0084"
INSIGHT_CALLS_PARITY_CONTRACT = "ac-postgres-parity-v55"
INSIGHT_CALLS_PARITY_TABLES = REVIEW_LABELS_PARITY_TABLES + ("conversation_insight_calls",)
COACHING_SHARING_PARITY_MIGRATION_HEAD = "20261011_0085"
COACHING_SHARING_PARITY_CONTRACT = "ac-postgres-parity-v56"
COACHING_SHARING_PARITY_TABLES = INSIGHT_CALLS_PARITY_TABLES + (
    "coaching_share_revisions",
    "coaching_feedback",
)
COACHING_CONTEXT_PARITY_MIGRATION_HEAD = "20261011_0086"
COACHING_CONTEXT_PARITY_CONTRACT = "ac-postgres-parity-v57"
COACHING_CONTEXT_PARITY_TABLES = COACHING_SHARING_PARITY_TABLES + ("coaching_learner_context",)
CALL_OUTCOMES_PARITY_MIGRATION_HEAD = "20261011_0087"
CALL_OUTCOMES_PARITY_CONTRACT = "ac-postgres-parity-v58"
CALL_OUTCOMES_PARITY_TABLES = COACHING_CONTEXT_PARITY_TABLES + (
    "conversation_call_outcome_revisions",
)
POINTER_REVIEWS_PARITY_MIGRATION_HEAD = "20261016_0091"
POINTER_REVIEWS_PARITY_CONTRACT = "ac-postgres-parity-v59"
POINTER_REVIEWS_PARITY_TABLES = CALL_OUTCOMES_PARITY_TABLES + ("conversation_pointer_reviews",)
LEAD_DESK_PARITY_MIGRATION_HEAD = "20261016_0093"
LEAD_DESK_PARITY_CONTRACT = "ac-postgres-parity-v60"
LEAD_DESK_PARITY_TABLES = POINTER_REVIEWS_PARITY_TABLES + (
    "lead_desk_leads",
    "lead_desk_events",
    "lead_desk_reps",
    "lead_desk_sources",
    "lead_desk_settings",
)
GOLD_REVIEWS_PARITY_MIGRATION_HEAD = "20261016_0094"
GOLD_REVIEWS_PARITY_CONTRACT = "ac-postgres-parity-v61"
GOLD_REVIEWS_PARITY_TABLES = LEAD_DESK_PARITY_TABLES + (
    "conversation_gold_reviewers",
    "conversation_gold_assignments",
    "conversation_gold_rows",
)
LEAD_ALERTS_PARITY_MIGRATION_HEAD = "20261017_0095"
LEAD_ALERTS_PARITY_CONTRACT = "ac-postgres-parity-v62"
LEAD_ALERTS_PARITY_TABLES = GOLD_REVIEWS_PARITY_TABLES + ("lead_desk_devices",)
PARTNER_WEBHOOKS_PARITY_MIGRATION_HEAD = "20261018_0096"
PARTNER_WEBHOOKS_PARITY_CONTRACT = "ac-postgres-parity-v63"
PARTNER_WEBHOOKS_PARITY_TABLES = LEAD_ALERTS_PARITY_TABLES + (
    "partner_webhook_endpoints",
    "partner_quote_facts",
    "partner_webhook_events",
    "partner_webhook_attempts",
)
CALL_DATA_PARITY_MIGRATION_HEAD = "20261019_0097"
CALL_DATA_PARITY_CONTRACT = "ac-postgres-parity-v64"
CALL_DATA_PARITY_TABLES = PARTNER_WEBHOOKS_PARITY_TABLES + (
    "call_data_settings",
    "call_data_runs",
    "call_objects",
    "call_object_decisions",
)
REPORT_SETTINGS_PARITY_MIGRATION_HEAD = "20261019_0098"
REPORT_SETTINGS_PARITY_CONTRACT = "ac-postgres-parity-v65"
REPORT_SETTINGS_PARITY_TABLES = CALL_DATA_PARITY_TABLES + (
    "conversation_report_settings_versions",
    "conversation_report_settings_events",
)
BUDGET_SETTINGS_PARITY_MIGRATION_HEAD = "20261019_0099"
BUDGET_SETTINGS_PARITY_CONTRACT = "ac-postgres-parity-v66"
BUDGET_SETTINGS_PARITY_TABLES = REPORT_SETTINGS_PARITY_TABLES + ("conversation_budget_settings",)
# 0100 widens one CHECK (capture sources); the table list is 0099's.
CAPTURE_SOURCE_PARITY_MIGRATION_HEAD = "20261019_0100"
CAPTURE_SOURCE_PARITY_CONTRACT = "ac-postgres-parity-v67"
CAPTURE_SOURCE_PARITY_TABLES = BUDGET_SETTINGS_PARITY_TABLES
# 0101 adds Review 2.0 (pipelines and verdicts).
REVIEW_PARITY_MIGRATION_HEAD = "20261019_0101"
REVIEW_PARITY_CONTRACT = "ac-postgres-parity-v68"
REVIEW_PARITY_TABLES = CAPTURE_SOURCE_PARITY_TABLES + (
    "review_pipelines",
    "review_verdicts",
)
# 0102 adds partner lead events and customer hand-overs.
PARTNER_LEAD_EVENTS_PARITY_MIGRATION_HEAD = "20261019_0102"
PARTNER_LEAD_EVENTS_PARITY_CONTRACT = "ac-postgres-parity-v69"
PARTNER_LEAD_EVENTS_PARITY_TABLES = REVIEW_PARITY_TABLES + (
    "partner_handover_recipients",
    "partner_lead_events",
    "partner_lead_attempts",
)
# 0103 adds the developer platform: API keys and sealed integration secrets.
INTEGRATIONS_PARITY_MIGRATION_HEAD = "20261019_0103"
INTEGRATIONS_PARITY_CONTRACT = "ac-postgres-parity-v70"
INTEGRATIONS_PARITY_TABLES = PARTNER_LEAD_EVENTS_PARITY_TABLES + (
    "integration_api_keys",
    "integration_secrets",
    "integration_oauth_clients",
    "integration_oauth_grants",
    "integration_oauth_codes",
    "integration_oauth_tokens",
)
# 0104 adds the CRM's lead stages sent back to Meta (Conversions API for CRM).
META_CONVERSIONS_PARITY_MIGRATION_HEAD = "20261019_0104"
META_CONVERSIONS_PARITY_CONTRACT = "ac-postgres-parity-v71"
META_CONVERSIONS_PARITY_TABLES = INTEGRATIONS_PARITY_TABLES + (
    "lead_desk_meta_conversions",
    "lead_desk_meta_conversion_attempts",
)
# 0105 adds WhatsApp in the CRM and the first-response SLA.
WHATSAPP_PARITY_MIGRATION_HEAD = "20261019_0105"
WHATSAPP_PARITY_CONTRACT = "ac-postgres-parity-v72"
WHATSAPP_PARITY_TABLES = META_CONVERSIONS_PARITY_TABLES + (
    "lead_desk_whatsapp_numbers",
    "lead_desk_whatsapp_messages",
    "lead_desk_whatsapp_templates",
    "lead_desk_sla_breaches",
)
# 0106 adds staff keys for the Admin command line and MCP.
STAFF_KEYS_PARITY_MIGRATION_HEAD = "20261019_0106"
STAFF_KEYS_PARITY_CONTRACT = "ac-postgres-parity-v73"
STAFF_KEYS_PARITY_TABLES = WHATSAPP_PARITY_TABLES + ("admin_staff_keys",)
# 0107 adds Messenger and Instagram conversations in the CRM.
SOCIAL_PARITY_MIGRATION_HEAD = "20261019_0107"
SOCIAL_PARITY_CONTRACT = "ac-postgres-parity-v74"
SOCIAL_PARITY_TABLES = STAFF_KEYS_PARITY_TABLES + (
    "lead_desk_social_accounts",
    "lead_desk_social_messages",
)
# 0108 adds ad spend per Meta campaign.
SPEND_PARITY_MIGRATION_HEAD = "20261019_0108"
SPEND_PARITY_CONTRACT = "ac-postgres-parity-v75"
SPEND_PARITY_TABLES = SOCIAL_PARITY_TABLES + ("lead_desk_ad_spend_days",)
# 0109 adds AI replies to leads.
AI_REPLIES_PARITY_MIGRATION_HEAD = "20261019_0109"
AI_REPLIES_PARITY_CONTRACT = "ac-postgres-parity-v76"
AI_REPLIES_PARITY_TABLES = SPEND_PARITY_TABLES + ("lead_desk_ai_replies",)
# 0110 adds AI replies' Admin settings (switch, model, cap).
AI_SETTINGS_PARITY_MIGRATION_HEAD = "20261019_0110"
AI_SETTINGS_PARITY_CONTRACT = "ac-postgres-parity-v77"
AI_SETTINGS_PARITY_TABLES = AI_REPLIES_PARITY_TABLES + ("lead_desk_ai_settings",)
# 0111 adds lead stages per business and the ad-platform outbox.
JOURNEY_PARITY_MIGRATION_HEAD = "20261020_0111"
JOURNEY_PARITY_CONTRACT = "ac-postgres-parity-v78"
JOURNEY_PARITY_TABLES = AI_SETTINGS_PARITY_TABLES + (
    "lead_desk_journey_versions",
    "lead_desk_conversions",
    "lead_desk_conversion_attempts",
)
# 0112 adds AI spend caps per environment.
AI_SPEND_PARITY_MIGRATION_HEAD = "20261020_0112"
AI_SPEND_PARITY_CONTRACT = "ac-postgres-parity-v79"
AI_SPEND_PARITY_TABLES = JOURNEY_PARITY_TABLES + ("ai_spend_settings",)
# 0113 adds read marks for Sales Xray Chats.
CHAT_READS_PARITY_MIGRATION_HEAD = "20261020_0113"
CHAT_READS_PARITY_CONTRACT = "ac-postgres-parity-v80"
CHAT_READS_PARITY_TABLES = AI_SPEND_PARITY_TABLES + ("lead_desk_chat_reads",)
# 0114 lets integration_secrets hold provider keys (a check constraint, no new table).
PROVIDER_KEYS_PARITY_MIGRATION_HEAD = "20261020_0114"
PROVIDER_KEYS_PARITY_CONTRACT = "ac-postgres-parity-v81"
PROVIDER_KEYS_PARITY_TABLES = CHAT_READS_PARITY_TABLES
# 0115 adds daily reference rates and the usage pseudonym key.
FX_PEOPLE_PARITY_MIGRATION_HEAD = "20261020_0115"
FX_PEOPLE_PARITY_CONTRACT = "ac-postgres-parity-v82"
FX_PEOPLE_PARITY_TABLES = PROVIDER_KEYS_PARITY_TABLES + (
    "fx_reference_rates",
    "metrics_pseudonym_keys",
)
# 0116 adds the one-pass trial's settings and runs.
ANALYSIS_TRIAL_PARITY_MIGRATION_HEAD = "20261021_0116"
ANALYSIS_TRIAL_PARITY_CONTRACT = "ac-postgres-parity-v83"
ANALYSIS_TRIAL_PARITY_TABLES = FX_PEOPLE_PARITY_TABLES + (
    "analysis_pipeline_settings",
    "one_pass_runs",
)
# 0117 adds Brain 4.0's shadow reads of saved reports.
BRAIN4_PARITY_MIGRATION_HEAD = "20261021_0117"
BRAIN4_PARITY_CONTRACT = "ac-postgres-parity-v84"
BRAIN4_PARITY_TABLES = ANALYSIS_TRIAL_PARITY_TABLES + ("conversation_brain4_reviews",)
# 0118 adds gold review checkpoints and the blind Brain 4.0 mode (two columns, no table).
GOLD_CHECKPOINT_PARITY_MIGRATION_HEAD = "20261021_0118"
GOLD_CHECKPOINT_PARITY_CONTRACT = "ac-postgres-parity-v85"
GOLD_CHECKPOINT_PARITY_TABLES = BRAIN4_PARITY_TABLES
# 0119 adds AI on calls: each organisation's levels and what they decided per call.
CALL_AI_PARITY_MIGRATION_HEAD = "20261021_0119"
CALL_AI_PARITY_CONTRACT = "ac-postgres-parity-v86"
CALL_AI_PARITY_TABLES = GOLD_CHECKPOINT_PARITY_TABLES + (
    "call_ai_settings",
    "call_ai_decisions",
)
# 0120 adds why a call stopped (one column, no table).
CALL_AI_REASON_PARITY_MIGRATION_HEAD = "20261021_0120"
CALL_AI_REASON_PARITY_CONTRACT = "ac-postgres-parity-v87"
CALL_AI_REASON_PARITY_TABLES = CALL_AI_PARITY_TABLES
# 0121 adds lead pipelines (one table; two nullable columns).
PIPELINES_PARITY_MIGRATION_HEAD = "20261022_0121"
PIPELINES_PARITY_CONTRACT = "ac-postgres-parity-v88"
PIPELINES_PARITY_TABLES = CALL_AI_REASON_PARITY_TABLES + ("lead_desk_pipelines",)
# 0122 adds an index on lead_desk_events (no table).
CALL_SUBMISSION_PARITY_MIGRATION_HEAD = "20261022_0122"
CALL_SUBMISSION_PARITY_CONTRACT = "ac-postgres-parity-v89"
CALL_SUBMISSION_PARITY_TABLES = PIPELINES_PARITY_TABLES
# 0123 lets a gold assignment review every Report item (a check and one column, no table).
REPORT_REVIEW_PARITY_MIGRATION_HEAD = "20261023_0123"
REPORT_REVIEW_PARITY_CONTRACT = "ac-postgres-parity-v90"
REPORT_REVIEW_PARITY_TABLES = CALL_SUBMISSION_PARITY_TABLES
# 0124 adds bug reports from Sales X-Ray testers and their append-only history.
BUG_REPORTS_PARITY_MIGRATION_HEAD = "20261023_0124"
BUG_REPORTS_PARITY_CONTRACT = "ac-postgres-parity-v91"
BUG_REPORTS_PARITY_TABLES = REPORT_REVIEW_PARITY_TABLES + ("bug_reports", "bug_report_events")
# 0125 adds the Offer Studio's shared offer versions (one table).
OFFER_STUDIO_PARITY_MIGRATION_HEAD = "20261023_0125"
OFFER_STUDIO_PARITY_CONTRACT = "ac-postgres-parity-v92"
OFFER_STUDIO_PARITY_TABLES = BUG_REPORTS_PARITY_TABLES + ("admin_offer_versions",)
# 0126 adds the Economics page's settings revisions (one table).
ECONOMICS_PARITY_MIGRATION_HEAD = "20261023_0126"
ECONOMICS_PARITY_CONTRACT = "ac-postgres-parity-v93"
ECONOMICS_PARITY_TABLES = OFFER_STUDIO_PARITY_TABLES + ("economics_settings",)
# 0127 adds feedback answers and bug report voice notes.
FEEDBACK_PARITY_MIGRATION_HEAD = "20261023_0127"
FEEDBACK_PARITY_CONTRACT = "ac-postgres-parity-v94"
FEEDBACK_PARITY_TABLES = ECONOMICS_PARITY_TABLES + (
    "feedback_responses",
    "bug_report_attachments",
)
# 0128 adds Lead OS meetings (one table).
LEAD_OS_PARITY_MIGRATION_HEAD = "20261024_0128"
LEAD_OS_PARITY_CONTRACT = "ac-postgres-parity-v95"
LEAD_OS_PARITY_TABLES = FEEDBACK_PARITY_TABLES + ("lead_desk_meetings",)
# 0129 adds the work-memory engine's tasks and reminder ledger (two tables).
TASKS_PARITY_MIGRATION_HEAD = "20261024_0129"
TASKS_PARITY_CONTRACT = "ac-postgres-parity-v96"
TASKS_PARITY_TABLES = LEAD_OS_PARITY_TABLES + (
    "lead_desk_tasks",
    "lead_desk_task_reminders",
)
# 0130 adds the team engine's targets and nudge ledger (two tables).
TEAM_PARITY_MIGRATION_HEAD = "20261025_0130"
TEAM_PARITY_CONTRACT = "ac-postgres-parity-v97"
TEAM_PARITY_TABLES = TASKS_PARITY_TABLES + (
    "lead_desk_targets",
    "lead_desk_nudges",
)
# 0131 adds the AI-write ledger (one table).
AI_WRITES_PARITY_MIGRATION_HEAD = "20261025_0131"
AI_WRITES_PARITY_CONTRACT = "ac-postgres-parity-v98"
AI_WRITES_PARITY_TABLES = TEAM_PARITY_TABLES + ("integration_writes",)
# 0132 lets a task come from an AI app (a check, no table).
ASSISTANT_TASKS_PARITY_MIGRATION_HEAD = "20261025_0132"
ASSISTANT_TASKS_PARITY_CONTRACT = "ac-postgres-parity-v99"
ASSISTANT_TASKS_PARITY_TABLES = AI_WRITES_PARITY_TABLES
# 0133 lets a seller have no open-lead limit (a column, no table).
REP_LIMIT_PARITY_MIGRATION_HEAD = "20261025_0133"
REP_LIMIT_PARITY_CONTRACT = "ac-postgres-parity-v100"
REP_LIMIT_PARITY_TABLES = ASSISTANT_TASKS_PARITY_TABLES
# 0134 adds duplicate leads' pairs, decisions and merges (three tables).
DUPLICATES_PARITY_MIGRATION_HEAD = "20261025_0134"
DUPLICATES_PARITY_CONTRACT = "ac-postgres-parity-v101"
DUPLICATES_PARITY_TABLES = REP_LIMIT_PARITY_TABLES + (
    "lead_desk_duplicate_pairs",
    "lead_desk_duplicate_decisions",
    "lead_desk_merges",
)
# 0135 adds each member's details (user id, title, team) and own photo: two tables.
PROFILE_PARITY_MIGRATION_HEAD = "20261025_0135"
PROFILE_PARITY_CONTRACT = "ac-postgres-parity-v102"
PROFILE_PARITY_TABLES = DUPLICATES_PARITY_TABLES + ("person_photos", "person_profile_details")
VERSIONED_PARITY_CONTRACTS = {
    PROFILE_PARITY_MIGRATION_HEAD: (
        PROFILE_PARITY_CONTRACT,
        PROFILE_PARITY_TABLES,
    ),
    DUPLICATES_PARITY_MIGRATION_HEAD: (
        DUPLICATES_PARITY_CONTRACT,
        DUPLICATES_PARITY_TABLES,
    ),
    REP_LIMIT_PARITY_MIGRATION_HEAD: (
        REP_LIMIT_PARITY_CONTRACT,
        REP_LIMIT_PARITY_TABLES,
    ),
    ASSISTANT_TASKS_PARITY_MIGRATION_HEAD: (
        ASSISTANT_TASKS_PARITY_CONTRACT,
        ASSISTANT_TASKS_PARITY_TABLES,
    ),
    AI_WRITES_PARITY_MIGRATION_HEAD: (
        AI_WRITES_PARITY_CONTRACT,
        AI_WRITES_PARITY_TABLES,
    ),
    TEAM_PARITY_MIGRATION_HEAD: (
        TEAM_PARITY_CONTRACT,
        TEAM_PARITY_TABLES,
    ),
    TASKS_PARITY_MIGRATION_HEAD: (
        TASKS_PARITY_CONTRACT,
        TASKS_PARITY_TABLES,
    ),
    LEAD_OS_PARITY_MIGRATION_HEAD: (
        LEAD_OS_PARITY_CONTRACT,
        LEAD_OS_PARITY_TABLES,
    ),
    FEEDBACK_PARITY_MIGRATION_HEAD: (
        FEEDBACK_PARITY_CONTRACT,
        FEEDBACK_PARITY_TABLES,
    ),
    ECONOMICS_PARITY_MIGRATION_HEAD: (
        ECONOMICS_PARITY_CONTRACT,
        ECONOMICS_PARITY_TABLES,
    ),
    OFFER_STUDIO_PARITY_MIGRATION_HEAD: (
        OFFER_STUDIO_PARITY_CONTRACT,
        OFFER_STUDIO_PARITY_TABLES,
    ),
    BUG_REPORTS_PARITY_MIGRATION_HEAD: (
        BUG_REPORTS_PARITY_CONTRACT,
        BUG_REPORTS_PARITY_TABLES,
    ),
    REPORT_REVIEW_PARITY_MIGRATION_HEAD: (
        REPORT_REVIEW_PARITY_CONTRACT,
        REPORT_REVIEW_PARITY_TABLES,
    ),
    CALL_SUBMISSION_PARITY_MIGRATION_HEAD: (
        CALL_SUBMISSION_PARITY_CONTRACT,
        CALL_SUBMISSION_PARITY_TABLES,
    ),
    PIPELINES_PARITY_MIGRATION_HEAD: (
        PIPELINES_PARITY_CONTRACT,
        PIPELINES_PARITY_TABLES,
    ),
    CALL_AI_REASON_PARITY_MIGRATION_HEAD: (
        CALL_AI_REASON_PARITY_CONTRACT,
        CALL_AI_REASON_PARITY_TABLES,
    ),
    CALL_AI_PARITY_MIGRATION_HEAD: (
        CALL_AI_PARITY_CONTRACT,
        CALL_AI_PARITY_TABLES,
    ),
    GOLD_CHECKPOINT_PARITY_MIGRATION_HEAD: (
        GOLD_CHECKPOINT_PARITY_CONTRACT,
        GOLD_CHECKPOINT_PARITY_TABLES,
    ),
    BRAIN4_PARITY_MIGRATION_HEAD: (
        BRAIN4_PARITY_CONTRACT,
        BRAIN4_PARITY_TABLES,
    ),
    ANALYSIS_TRIAL_PARITY_MIGRATION_HEAD: (
        ANALYSIS_TRIAL_PARITY_CONTRACT,
        ANALYSIS_TRIAL_PARITY_TABLES,
    ),
    FX_PEOPLE_PARITY_MIGRATION_HEAD: (
        FX_PEOPLE_PARITY_CONTRACT,
        FX_PEOPLE_PARITY_TABLES,
    ),
    PROVIDER_KEYS_PARITY_MIGRATION_HEAD: (
        PROVIDER_KEYS_PARITY_CONTRACT,
        PROVIDER_KEYS_PARITY_TABLES,
    ),
    CHAT_READS_PARITY_MIGRATION_HEAD: (
        CHAT_READS_PARITY_CONTRACT,
        CHAT_READS_PARITY_TABLES,
    ),
    AI_SPEND_PARITY_MIGRATION_HEAD: (
        AI_SPEND_PARITY_CONTRACT,
        AI_SPEND_PARITY_TABLES,
    ),
    JOURNEY_PARITY_MIGRATION_HEAD: (
        JOURNEY_PARITY_CONTRACT,
        JOURNEY_PARITY_TABLES,
    ),
    AI_SETTINGS_PARITY_MIGRATION_HEAD: (
        AI_SETTINGS_PARITY_CONTRACT,
        AI_SETTINGS_PARITY_TABLES,
    ),
    AI_REPLIES_PARITY_MIGRATION_HEAD: (
        AI_REPLIES_PARITY_CONTRACT,
        AI_REPLIES_PARITY_TABLES,
    ),
    SPEND_PARITY_MIGRATION_HEAD: (
        SPEND_PARITY_CONTRACT,
        SPEND_PARITY_TABLES,
    ),
    SOCIAL_PARITY_MIGRATION_HEAD: (
        SOCIAL_PARITY_CONTRACT,
        SOCIAL_PARITY_TABLES,
    ),
    STAFF_KEYS_PARITY_MIGRATION_HEAD: (
        STAFF_KEYS_PARITY_CONTRACT,
        STAFF_KEYS_PARITY_TABLES,
    ),
    WHATSAPP_PARITY_MIGRATION_HEAD: (
        WHATSAPP_PARITY_CONTRACT,
        WHATSAPP_PARITY_TABLES,
    ),
    META_CONVERSIONS_PARITY_MIGRATION_HEAD: (
        META_CONVERSIONS_PARITY_CONTRACT,
        META_CONVERSIONS_PARITY_TABLES,
    ),
    INTEGRATIONS_PARITY_MIGRATION_HEAD: (
        INTEGRATIONS_PARITY_CONTRACT,
        INTEGRATIONS_PARITY_TABLES,
    ),
    PARTNER_LEAD_EVENTS_PARITY_MIGRATION_HEAD: (
        PARTNER_LEAD_EVENTS_PARITY_CONTRACT,
        PARTNER_LEAD_EVENTS_PARITY_TABLES,
    ),
    REVIEW_PARITY_MIGRATION_HEAD: (
        REVIEW_PARITY_CONTRACT,
        REVIEW_PARITY_TABLES,
    ),
    CAPTURE_SOURCE_PARITY_MIGRATION_HEAD: (
        CAPTURE_SOURCE_PARITY_CONTRACT,
        CAPTURE_SOURCE_PARITY_TABLES,
    ),
    BUDGET_SETTINGS_PARITY_MIGRATION_HEAD: (
        BUDGET_SETTINGS_PARITY_CONTRACT,
        BUDGET_SETTINGS_PARITY_TABLES,
    ),
    REPORT_SETTINGS_PARITY_MIGRATION_HEAD: (
        REPORT_SETTINGS_PARITY_CONTRACT,
        REPORT_SETTINGS_PARITY_TABLES,
    ),
    CALL_DATA_PARITY_MIGRATION_HEAD: (
        CALL_DATA_PARITY_CONTRACT,
        CALL_DATA_PARITY_TABLES,
    ),
    PARTNER_WEBHOOKS_PARITY_MIGRATION_HEAD: (
        PARTNER_WEBHOOKS_PARITY_CONTRACT,
        PARTNER_WEBHOOKS_PARITY_TABLES,
    ),
    LEAD_ALERTS_PARITY_MIGRATION_HEAD: (
        LEAD_ALERTS_PARITY_CONTRACT,
        LEAD_ALERTS_PARITY_TABLES,
    ),
    GOLD_REVIEWS_PARITY_MIGRATION_HEAD: (
        GOLD_REVIEWS_PARITY_CONTRACT,
        GOLD_REVIEWS_PARITY_TABLES,
    ),
    LEAD_DESK_PARITY_MIGRATION_HEAD: (
        LEAD_DESK_PARITY_CONTRACT,
        LEAD_DESK_PARITY_TABLES,
    ),
    # 0092 adds erasure columns only; its counted tables are unchanged.
    "20261016_0092": (POINTER_REVIEWS_PARITY_CONTRACT, POINTER_REVIEWS_PARITY_TABLES),
    POINTER_REVIEWS_PARITY_MIGRATION_HEAD: (
        POINTER_REVIEWS_PARITY_CONTRACT,
        POINTER_REVIEWS_PARITY_TABLES,
    ),
    # 0088–0090 change constraints only; their counted tables are unchanged.
    "20261013_0090": (CALL_OUTCOMES_PARITY_CONTRACT, CALL_OUTCOMES_PARITY_TABLES),
    "20261013_0089": (CALL_OUTCOMES_PARITY_CONTRACT, CALL_OUTCOMES_PARITY_TABLES),
    "20261012_0088": (CALL_OUTCOMES_PARITY_CONTRACT, CALL_OUTCOMES_PARITY_TABLES),
    CALL_OUTCOMES_PARITY_MIGRATION_HEAD: (
        CALL_OUTCOMES_PARITY_CONTRACT,
        CALL_OUTCOMES_PARITY_TABLES,
    ),
    COACHING_CONTEXT_PARITY_MIGRATION_HEAD: (
        COACHING_CONTEXT_PARITY_CONTRACT,
        COACHING_CONTEXT_PARITY_TABLES,
    ),
    COACHING_SHARING_PARITY_MIGRATION_HEAD: (
        COACHING_SHARING_PARITY_CONTRACT,
        COACHING_SHARING_PARITY_TABLES,
    ),
    INSIGHT_CALLS_PARITY_MIGRATION_HEAD: (
        INSIGHT_CALLS_PARITY_CONTRACT,
        INSIGHT_CALLS_PARITY_TABLES,
    ),
    REVIEW_LABELS_PARITY_MIGRATION_HEAD: (
        REVIEW_LABELS_PARITY_CONTRACT,
        REVIEW_LABELS_PARITY_TABLES,
    ),
    SYNTHETIC_SANDBOX_PARITY_MIGRATION_HEAD: (
        SYNTHETIC_SANDBOX_PARITY_CONTRACT,
        SYNTHETIC_SANDBOX_PARITY_TABLES,
    ),
    RECORDING_IMPORTS_PARITY_MIGRATION_HEAD: (
        RECORDING_IMPORTS_PARITY_CONTRACT,
        RECORDING_IMPORTS_PARITY_TABLES,
    ),
    REPORT_MINUTES_PARITY_MIGRATION_HEAD: (
        REPORT_MINUTES_PARITY_CONTRACT,
        REPORT_MINUTES_PARITY_TABLES,
    ),
    PROSPECT_FIELDS_PARITY_MIGRATION_HEAD: (
        PROSPECT_FIELDS_PARITY_CONTRACT,
        PROSPECT_FIELDS_PARITY_TABLES,
    ),
    COMPANION_DEVICES_PARITY_MIGRATION_HEAD: (
        COMPANION_DEVICES_PARITY_CONTRACT,
        COMPANION_DEVICES_PARITY_TABLES,
    ),
    PROSPECT_TAGS_PARITY_MIGRATION_HEAD: (
        PROSPECT_TAGS_PARITY_CONTRACT,
        PROSPECT_TAGS_PARITY_TABLES,
    ),
    ORGANISATION_SETTINGS_PARITY_MIGRATION_HEAD: (
        ORGANISATION_SETTINGS_PARITY_CONTRACT,
        ORGANISATION_SETTINGS_PARITY_TABLES,
    ),
    PRODUCT_UPDATES_PARITY_MIGRATION_HEAD: (
        PRODUCT_UPDATES_PARITY_CONTRACT,
        PRODUCT_UPDATES_PARITY_TABLES,
    ),
    PROSPECTS_PARITY_MIGRATION_HEAD: (PROSPECTS_PARITY_CONTRACT, PROSPECTS_PARITY_TABLES),
    BILLING_CREDITS_PARITY_MIGRATION_HEAD: (
        BILLING_CREDITS_PARITY_CONTRACT,
        BILLING_CREDITS_PARITY_TABLES,
    ),
    "20261003_0072": (CALL_METRICS_PARITY_CONTRACT, CALL_METRICS_PARITY_TABLES),
    CALL_METRICS_PARITY_MIGRATION_HEAD: (
        CALL_METRICS_PARITY_CONTRACT,
        CALL_METRICS_PARITY_TABLES,
    ),
    SPEAKER_MAPS_PARITY_MIGRATION_HEAD: (
        SPEAKER_MAPS_PARITY_CONTRACT,
        SPEAKER_MAPS_PARITY_TABLES,
    ),
    BILLING_INVOICES_PARITY_MIGRATION_HEAD: (
        BILLING_INVOICES_PARITY_CONTRACT,
        BILLING_INVOICES_PARITY_TABLES,
    ),
    INACTIVE_PLAN_VALUES_PARITY_MIGRATION_HEAD: (
        INACTIVE_PLAN_VALUES_PARITY_CONTRACT,
        INACTIVE_PLAN_VALUES_PARITY_TABLES,
    ),
    SENSITIVE_SEGMENT_MARKS_PARITY_MIGRATION_HEAD: (
        SENSITIVE_SEGMENT_MARKS_PARITY_CONTRACT,
        SENSITIVE_SEGMENT_MARKS_PARITY_TABLES,
    ),
    PLATFORM_BILLING_MANAGE_PARITY_MIGRATION_HEAD: (
        PLATFORM_BILLING_MANAGE_PARITY_CONTRACT,
        PLATFORM_BILLING_MANAGE_PARITY_TABLES,
    ),
    PLAN_CATALOGUE_PARITY_MIGRATION_HEAD: (
        PLAN_CATALOGUE_PARITY_CONTRACT,
        PLAN_CATALOGUE_PARITY_TABLES,
    ),
    BILLING_SUBSCRIPTIONS_PARITY_MIGRATION_HEAD: (
        BILLING_SUBSCRIPTIONS_PARITY_CONTRACT,
        BILLING_SUBSCRIPTIONS_PARITY_TABLES,
    ),
    BILLING_ORDERS_PARITY_MIGRATION_HEAD: (
        BILLING_ORDERS_PARITY_CONTRACT,
        BILLING_ORDERS_PARITY_TABLES,
    ),
    BILLING_LEDGER_PARITY_MIGRATION_HEAD: (
        BILLING_LEDGER_PARITY_CONTRACT,
        BILLING_LEDGER_PARITY_TABLES,
    ),
    JOB_FAILURE_DETAIL_PARITY_MIGRATION_HEAD: (
        JOB_FAILURE_DETAIL_PARITY_CONTRACT,
        JOB_FAILURE_DETAIL_PARITY_TABLES,
    ),
    PLATFORM_RELEASE_MANAGE_PARITY_MIGRATION_HEAD: (
        PLATFORM_RELEASE_MANAGE_PARITY_CONTRACT,
        PLATFORM_RELEASE_MANAGE_PARITY_TABLES,
    ),
    ORGANISATIONS_PARITY_MIGRATION_HEAD: (
        ORGANISATIONS_PARITY_CONTRACT,
        ORGANISATIONS_PARITY_TABLES,
    ),
    GOOGLE_PROFILES_PARITY_MIGRATION_HEAD: (
        GOOGLE_PROFILES_PARITY_CONTRACT,
        GOOGLE_PROFILES_PARITY_TABLES,
    ),
    CANARY_PARITY_MIGRATION_HEAD: (CANARY_PARITY_CONTRACT, CANARY_PARITY_TABLES),
    CAPABILITY_PARITY_MIGRATION_HEAD: (CAPABILITY_PARITY_CONTRACT, CAPABILITY_PARITY_TABLES),
    PRACTICE_PARITY_MIGRATION_HEAD: (PRACTICE_PARITY_CONTRACT, PRACTICE_PARITY_TABLES),
    FOCUS_PARITY_MIGRATION_HEAD: (FOCUS_PARITY_CONTRACT, FOCUS_PARITY_TABLES),
    AUTHORING_PARITY_MIGRATION_HEAD: (AUTHORING_PARITY_CONTRACT, AUTHORING_PARITY_TABLES),
    REVISION_PARITY_MIGRATION_HEAD: (REVISION_PARITY_CONTRACT, REVISION_PARITY_TABLES),
    MEDIA_LIBRARY_PARITY_MIGRATION_HEAD: (
        MEDIA_LIBRARY_PARITY_CONTRACT,
        MEDIA_LIBRARY_PARITY_TABLES,
    ),
    COURSE_CREATION_PARITY_MIGRATION_HEAD: (
        COURSE_CREATION_PARITY_CONTRACT,
        COURSE_CREATION_PARITY_TABLES,
    ),
    STUDIO_VIDEO_PARITY_MIGRATION_HEAD: (
        STUDIO_VIDEO_PARITY_CONTRACT,
        STUDIO_VIDEO_PARITY_TABLES,
    ),
    COMMUNITY_PARITY_MIGRATION_HEAD: (
        COMMUNITY_PARITY_CONTRACT,
        COMMUNITY_PARITY_TABLES,
    ),
    GLOBAL_COMMUNITY_PARITY_MIGRATION_HEAD: (
        GLOBAL_COMMUNITY_PARITY_CONTRACT,
        GLOBAL_COMMUNITY_PARITY_TABLES,
    ),
    APP_UPDATES_PARITY_MIGRATION_HEAD: (
        APP_UPDATES_PARITY_CONTRACT,
        APP_UPDATES_PARITY_TABLES,
    ),
    SALES_XRAY_PARITY_MIGRATION_HEAD: (
        SALES_XRAY_PARITY_CONTRACT,
        SALES_XRAY_PARITY_TABLES,
    ),
    INFERENCE_PARITY_MIGRATION_HEAD: (
        INFERENCE_PARITY_CONTRACT,
        INFERENCE_PARITY_TABLES,
    ),
    PLANS_PARITY_MIGRATION_HEAD: (PLANS_PARITY_CONTRACT, PLANS_PARITY_TABLES),
    COMMUNITY_CONNECTIONS_PARITY_MIGRATION_HEAD: (
        COMMUNITY_CONNECTIONS_PARITY_CONTRACT,
        COMMUNITY_CONNECTIONS_PARITY_TABLES,
    ),
    REVIEWS_PARITY_MIGRATION_HEAD: (REVIEWS_PARITY_CONTRACT, REVIEWS_PARITY_TABLES),
    REVIEW_INVITATIONS_PARITY_MIGRATION_HEAD: (
        REVIEW_INVITATIONS_PARITY_CONTRACT,
        REVIEW_INVITATIONS_PARITY_TABLES,
    ),
    ACQUISITION_PARITY_MIGRATION_HEAD: (
        ACQUISITION_PARITY_CONTRACT,
        ACQUISITION_PARITY_TABLES,
    ),
    PROCESSING_OWNERSHIP_PARITY_MIGRATION_HEAD: (
        PROCESSING_OWNERSHIP_PARITY_CONTRACT,
        PROCESSING_OWNERSHIP_PARITY_TABLES,
    ),
    REVIEWER_IDENTITY_PARITY_MIGRATION_HEAD: (
        REVIEWER_IDENTITY_PARITY_CONTRACT,
        REVIEWER_IDENTITY_PARITY_TABLES,
    ),
    PROVIDER_ACTIVATION_PARITY_MIGRATION_HEAD: (
        PROVIDER_ACTIVATION_PARITY_CONTRACT,
        PROVIDER_ACTIVATION_PARITY_TABLES,
    ),
    PROCESSING_CONTINUATION_PARITY_MIGRATION_HEAD: (
        PROCESSING_CONTINUATION_PARITY_CONTRACT,
        PROCESSING_CONTINUATION_PARITY_TABLES,
    ),
    EXECUTION_CONTROL_PARITY_MIGRATION_HEAD: (
        EXECUTION_CONTROL_PARITY_CONTRACT,
        EXECUTION_CONTROL_PARITY_TABLES,
    ),
    ANALYSIS_SETTINGS_PARITY_MIGRATION_HEAD: (
        ANALYSIS_SETTINGS_PARITY_CONTRACT,
        ANALYSIS_SETTINGS_PARITY_TABLES,
    ),
    RETAINED_C5_RECOVERY_PARITY_MIGRATION_HEAD: (
        RETAINED_C5_RECOVERY_PARITY_CONTRACT,
        RETAINED_C5_RECOVERY_PARITY_TABLES,
    ),
    ANALYSIS_LANGUAGE_PARITY_MIGRATION_HEAD: (
        ANALYSIS_LANGUAGE_PARITY_CONTRACT,
        ANALYSIS_LANGUAGE_PARITY_TABLES,
    ),
    EMAIL_LOGIN_CODES_PARITY_MIGRATION_HEAD: (
        EMAIL_LOGIN_CODES_PARITY_CONTRACT,
        EMAIL_LOGIN_CODES_PARITY_TABLES,
    ),
    SALES_XRAY_PROFILES_PARITY_MIGRATION_HEAD: (
        SALES_XRAY_PROFILES_PARITY_CONTRACT,
        SALES_XRAY_PROFILES_PARITY_TABLES,
    ),
    COACHING_DEPTH_PARITY_MIGRATION_HEAD: (
        COACHING_DEPTH_PARITY_CONTRACT,
        COACHING_DEPTH_PARITY_TABLES,
    ),
    EMAIL_ACKNOWLEDGEMENT_PARITY_MIGRATION_HEAD: (
        EMAIL_ACKNOWLEDGEMENT_PARITY_CONTRACT,
        EMAIL_ACKNOWLEDGEMENT_PARITY_TABLES,
    ),
    COACHING_V6_SELECTION_PARITY_MIGRATION_HEAD: (
        COACHING_V6_SELECTION_PARITY_CONTRACT,
        COACHING_V6_SELECTION_PARITY_TABLES,
    ),
    SUBMISSION_LABELS_PARITY_MIGRATION_HEAD: (
        SUBMISSION_LABELS_PARITY_CONTRACT,
        SUBMISSION_LABELS_PARITY_TABLES,
    ),
    SOURCE_OBJECTS_PARITY_MIGRATION_HEAD: (
        SOURCE_OBJECTS_PARITY_CONTRACT,
        SOURCE_OBJECTS_PARITY_TABLES,
    ),
}


def parity_tables_for_head(migration_head: str) -> tuple[str, ...]:
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return PARITY_TABLES
    if migration_head in VERSIONED_PARITY_CONTRACTS:
        return VERSIONED_PARITY_CONTRACTS[migration_head][1]
    raise BackupError("migration head has no reviewed row-count parity contract")


def parity_contract_for_head(migration_head: str) -> str | None:
    parity_tables_for_head(migration_head)
    if migration_head in LEGACY_PARITY_MIGRATION_HEADS:
        return None
    return VERSIONED_PARITY_CONTRACTS[migration_head][0]


def parity_metadata_fields(migration_head: str) -> dict[str, str]:
    contract = parity_contract_for_head(migration_head)
    if contract is not None:
        return {"parity_contract": contract, "migration_head": migration_head}
    return {}


HEALTH_CHECK_COMMAND_TIMEOUT_SECONDS = 30
HEALTH_CHECKS_PER_ENVIRONMENT = 2
BACKUP_SAFETY_MARGIN_SECONDS = 5 * 60
BACKUP_SERVICE_TIMEOUT_SECONDS = 60 * 60


def worst_case_two_environment_backup_seconds() -> int:
    """Return the conservative bound used by the backup systemd unit."""

    per_environment = (
        HEALTH_CHECK_COMMAND_TIMEOUT_SECONDS * HEALTH_CHECKS_PER_ENVIRONMENT
        + SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS
        + PG_RESTORE_LIST_TIMEOUT_SECONDS
        + PG_RESTORE_LIST_TIMEOUT_SECONDS
        + RESTIC_UPLOAD_TIMEOUT_SECONDS
        + RESTIC_REPOSITORY_LOCK_WAIT_SECONDS
        + OPERATION_KILL_AFTER_SECONDS
        + 30
        + R2_GUARD_CLIENT_TIMEOUT_SECONDS
    )
    return (
        len(ENVIRONMENTS) * per_environment
        + R2_GUARD_CLIENT_TIMEOUT_SECONDS
        + BACKUP_SAFETY_MARGIN_SECONDS
    )


class BackupError(RuntimeError):
    """A safe, operator-facing failure without command or secret output."""


@dataclass(frozen=True)
class ApplicationTarget:
    environment: str
    current_link: Path
    release_dir: Path
    profile_file: Path
    images_file: Path
    state_root: Path
    compose_project: str
    secret_environment: str
    migration_head: str


class CaptureIO(Protocol):
    """Optional bounded I/O for a separate Drive capture, never an R2 limit change."""

    def holder(self, target: ApplicationTarget) -> ExportedSnapshotHolder: ...
    def dump(self, target: ApplicationTarget, snapshot_id: str, path: Path) -> int: ...
    def verify(self, target: ApplicationTarget, path: Path) -> None: ...
    def read(
        self, command: list[str], *, target: ApplicationTarget, timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]: ...
    def remaining(self) -> float: ...


@dataclass
class ExportedSnapshotHolder:
    """A bounded read-only PostgreSQL transaction exporting one snapshot."""

    process: subprocess.Popen[bytes]
    snapshot_id: str
    started_at: float
    closed: bool = False
    remaining: Callable[[], float] | None = None
    cleanup: Callable[[subprocess.Popen[bytes]], None] | None = None

    def assert_alive(self) -> None:
        if self.remaining is not None:
            self.remaining()
        if self.closed or self.process.poll() is not None:
            raise BackupError("The PostgreSQL exported-snapshot holder exited early.")
        if time.monotonic() - self.started_at > SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS:
            self.close()
            raise BackupError("The PostgreSQL exported-snapshot holder exceeded its lifetime.")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._rollback()
        finally:
            if self.cleanup is not None:
                self.cleanup(self.process)

    def _rollback(self) -> None:
        if self.remaining is not None:
            self.remaining()
        rollback_error: OSError | None = None
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write(b"ROLLBACK;\n\\q\n")
                self.process.stdin.flush()
                self.process.stdin.close()
            except OSError as error:
                rollback_error = error
            if rollback_error is None:
                try:
                    timeout = SNAPSHOT_HOLDER_ROLLBACK_TIMEOUT_SECONDS
                    if self.remaining is not None:
                        timeout = min(timeout, self.remaining())
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    if self.cleanup is None:
                        terminate_process(self.process)
                    raise BackupError(
                        "The PostgreSQL exported-snapshot holder rollback timed out."
                    ) from error
            else:
                if self.cleanup is None:
                    terminate_process(self.process)
                raise BackupError(
                    "The PostgreSQL exported-snapshot holder rollback failed."
                ) from rollback_error
        if self.process.returncode not in (0, None):
            raise BackupError("The PostgreSQL exported-snapshot holder failed during cleanup.")


def validate_exported_snapshot_id(value: str) -> str:
    if not isinstance(value, str) or EXPORTED_SNAPSHOT_RE.fullmatch(value) is None:
        raise BackupError("The PostgreSQL exported snapshot identity is invalid.")
    return value


def snapshot_holder_command(target: ApplicationTarget) -> list[str]:
    return [
        "timeout",
        "--foreground",
        f"--kill-after={PG_DUMP_KILL_AFTER_SECONDS}s",
        f"{SNAPSHOT_HOLDER_MAX_LIFETIME_SECONDS}s",
        *compose_command(
            target,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-euc",
            'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
            "exec psql --no-password -h 127.0.0.1 -U ac_backup "
            '-d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1',
        ),
    ]


def start_exported_snapshot_holder(
    target: ApplicationTarget,
    *,
    timeout_seconds: float = SNAPSHOT_HOLDER_START_TIMEOUT_SECONDS,
    remaining: Callable[[], float] | None = None,
    cleanup: Callable[[subprocess.Popen[bytes]], None] | None = None,
) -> ExportedSnapshotHolder:
    if remaining is not None:
        remaining()
    try:
        process = subprocess.Popen(  # noqa: S603 - command uses fixed release paths
            snapshot_holder_command(target),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=compose_environment(target),
            start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        raise BackupError("The PostgreSQL exported-snapshot holder could not start.") from error
    handed_off = False
    try:
        try:
            assert process.stdin is not None
            process.stdin.write(SNAPSHOT_HOLDER_START_SQL)
            process.stdin.flush()
        except OSError as error:
            raise BackupError("The PostgreSQL exported-snapshot holder protocol failed.") from error
        assert process.stdout is not None
        output_queue: queue.Queue[object] = queue.Queue(maxsize=1)

        def read_snapshot_line() -> None:
            try:
                output_queue.put(process.stdout.readline(129))
            except OSError as error:
                output_queue.put(error)

        reader = threading.Thread(target=read_snapshot_line, daemon=True)
        reader.start()
        if remaining is not None:
            timeout_seconds = min(timeout_seconds, remaining())
        try:
            line = output_queue.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise BackupError(
                "The PostgreSQL exported-snapshot holder startup timed out."
            ) from error
        if isinstance(line, OSError):
            raise BackupError(
                "The PostgreSQL exported-snapshot holder output was unreadable."
            ) from line
        if not isinstance(line, bytes) or len(line) > 128 or not line.endswith(b"\n"):
            raise BackupError(
                "The PostgreSQL exported-snapshot holder returned an invalid identity."
            )
        try:
            snapshot_id = validate_exported_snapshot_id(line.decode("ascii").strip())
        except UnicodeDecodeError as error:
            raise BackupError(
                "The PostgreSQL exported-snapshot holder returned an invalid identity."
            ) from error
        if remaining is not None:
            remaining()
        if process.poll() is not None:
            raise BackupError("The PostgreSQL exported-snapshot holder exited before the dump.")
        holder = ExportedSnapshotHolder(
            process, snapshot_id, time.monotonic(), remaining=remaining, cleanup=cleanup
        )
        handed_off = True
        return holder
    finally:
        # Ownership transfers only on successful return. Even an exited leader
        # can leave live descendants, so every refusal must clean its session.
        if not handed_off:
            try:
                (cleanup or terminate_process)(process)
            except OSError as error:
                raise BackupError(
                    "The PostgreSQL exported-snapshot holder startup cleanup failed."
                ) from error


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def timestamp(value: dt.datetime | None = None) -> str:
    value = value or utc_now()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def host_path(host_root: Path, absolute_path: str | Path) -> Path:
    path = PurePosixPath(str(absolute_path).replace("\\", "/"))
    if not path.is_absolute():
        raise BackupError("An operational path must be absolute.")
    relative = Path(*path.parts[1:])
    return host_root / relative if host_root != Path("/") else Path("/", relative)


def foundation_policy_path(host_root: Path) -> Path:
    scope_record = host_path(host_root, FOUNDATION_SCOPES / "backup.release")
    if scope_record.exists() or scope_record.is_symlink():
        if scope_record.is_symlink() or not scope_record.is_file():
            raise BackupError("Backup foundation scope record is unsafe.")
        try:
            scope_release_id = scope_record.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BackupError("Backup foundation scope record is unreadable.") from exc
        if not re.fullmatch(r"foundation-[0-9a-f]{40}", scope_release_id):
            raise BackupError("Backup foundation scope record has an invalid release ID.")
        return host_path(
            host_root,
            f"/srv/authority-closers/releases/{scope_release_id}/config/r2/free-tier-policy.conf",
        )
    return host_path(host_root, FOUNDATION_CURRENT) / "config/r2/free-tier-policy.conf"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("Application release profile is not readable.") from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise BackupError("Application release profile is malformed.")
        if not ENV_VALUE_RE.fullmatch(value):
            raise BackupError("Application release profile contains unsafe syntax.")
        values[key] = value
    return values


def verify_release_files(release_dir: Path) -> None:
    manifest = release_dir / "RELEASE-FILES.sha256"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("Current application release lacks checksum evidence.") from exc
    for line in lines:
        digest, separator, relative = line.partition("  ")
        relative = relative.removeprefix("./")
        candidate = (release_dir / relative).resolve()
        if (
            not separator
            or not SHA256_RE.fullmatch(digest)
            or not relative
            or Path(relative).is_absolute()
            or release_dir not in candidate.parents
            or not candidate.is_file()
        ):
            raise BackupError("Current application release checksum evidence is malformed.")
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != digest:
            raise BackupError("Current application release checksum verification failed.")


def resolve_application_release(
    environment: str,
    *,
    host_root: Path = Path("/"),
    allow_missing: bool = False,
) -> ApplicationTarget | None:
    if environment not in ENVIRONMENTS:
        raise BackupError("Unsupported application environment.")
    application_root = host_path(host_root, APPLICATION_ROOT)
    current_link = application_root / f"current-{environment}"
    if not current_link.exists() and not current_link.is_symlink():
        if allow_missing:
            return None
        raise BackupError(f"The current {environment} application release is absent.")
    if not current_link.is_symlink():
        raise BackupError(f"The current {environment} application path is not a symlink.")
    try:
        release_dir = current_link.resolve(strict=True)
    except OSError as exc:
        raise BackupError(f"The current {environment} application release is broken.") from exc
    releases_root = application_root / "releases"
    if release_dir.parent != releases_root or not re.fullmatch(r"[0-9a-f]{40}", release_dir.name):
        raise BackupError(
            f"The current {environment} application release is outside its immutable root."
        )
    verify_release_files(release_dir)
    profile_file = release_dir / "environments" / f"{environment}.env"
    images_file = release_dir / "release-images.env"
    profile = parse_env_file(profile_file)
    for key, expected in EXPECTED_PROFILE_VALUES[environment].items():
        if profile.get(key) != expected:
            raise BackupError(f"The current {environment} application profile is not exact.")
    # Both immutable production phases need local capture, including the held
    # baseline before activation. Never admit a mixed hold/provider pair.
    provider_pair = (profile.get("AC_EXTERNAL_SIDE_EFFECTS_HOLD"), profile.get("AC_EMAIL_PROVIDER"))
    if environment == "production" and provider_pair not in {("true", "fake"), ("false", "resend")}:
        raise BackupError("The current production application profile is not exact.")
    state_root = host_path(host_root, profile["AC_STATE_ROOT"])
    if not state_root.is_dir() or state_root.is_symlink():
        raise BackupError(f"The current {environment} application state root is absent or unsafe.")
    if not images_file.is_file() or not (release_dir / "compose.yaml").is_file():
        raise BackupError(f"The current {environment} application compose release is incomplete.")
    images = parse_env_file(images_file)
    migration_head = images.get("AC_MIGRATION_HEAD", "")
    parity_tables_for_head(migration_head)
    if images.get("AC_RELEASE_ID") != release_dir.name:
        raise BackupError("The current application release identity is inconsistent.")
    return ApplicationTarget(
        environment=environment,
        current_link=current_link,
        release_dir=release_dir,
        profile_file=profile_file,
        images_file=images_file,
        state_root=state_root,
        compose_project=profile["AC_COMPOSE_PROJECT"],
        secret_environment="prod" if environment == "production" else environment,
        migration_head=migration_head,
    )


def resolve_targets(
    *, host_root: Path = Path("/"), requested_environment: str | None = None
) -> list[ApplicationTarget]:
    if requested_environment:
        target = resolve_application_release(
            requested_environment, host_root=host_root, allow_missing=False
        )
        return [target] if target else []
    staging = resolve_application_release("staging", host_root=host_root, allow_missing=False)
    production = resolve_application_release("production", host_root=host_root, allow_missing=True)
    return [target for target in (staging, production) if target is not None]


def compose_command(target: ApplicationTarget, *arguments: str) -> list[str]:
    command = [
        INFISICAL_RUN,
        "--",
        "env",
    ]
    for key in PROFILE_KEYS:
        command.extend(("-u", key))
    command.extend(
        (
            "docker",
            "compose",
            "--project-directory",
            str(target.release_dir),
            "--project-name",
            target.compose_project,
            "--env-file",
            str(target.profile_file),
            "--env-file",
            str(target.images_file),
            "--file",
            str(target.release_dir / "compose.yaml"),
            *arguments,
        )
    )
    return command


def compose_environment(target: ApplicationTarget) -> dict[str, str]:
    environment = os.environ.copy()
    environment["AC_INFISICAL_ENVIRONMENT"] = target.secret_environment
    environment["AC_INFISICAL_PATH"] = "/application"
    for key in (*PROFILE_KEYS, *SECRET_KEYS):
        environment.pop(key, None)
    for key in ("AC_POSTGRES_DRIVE_PRODUCTION_PASSPHRASE", "AC_POSTGRES_DRIVE_STAGING_PASSPHRASE"):
        environment.pop(key, None)
    return environment


def run_checked(
    command: list[str],
    *,
    target: ApplicationTarget | None = None,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - command is assembled from fixed release paths and allow-listed values
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=compose_environment(target) if target else None,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError("The bounded backup command failed.") from exc


def assert_healthy(target: ApplicationTarget, *, reader: Callable | None = None) -> None:
    result = (reader or run_checked)(compose_command(target, "ps", "-q", "postgres"), target=target)
    container_id = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise BackupError(f"The {target.environment} postgres container is not present.")
    if reader is not None:
        health = reader(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
            target=target,
        ).stdout.strip()
        if health != "healthy":
            raise BackupError(f"The {target.environment} postgres container is not healthy.")
        return
    try:
        health = subprocess.run(  # noqa: S603 - container ID is validated before use
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],  # noqa: S607
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"The {target.environment} postgres health check failed.") from exc
    if health != "healthy":
        raise BackupError(f"The {target.environment} postgres container is not healthy.")


def read_policy(path: Path) -> dict[str, int | str]:
    values: dict[str, int | str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BackupError("R2 policy is not readable.") from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in POLICY_KEYS or key in values:
            raise BackupError("R2 policy contains an unknown or duplicate assignment.")
        if key.endswith("BUCKET"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", value):
                raise BackupError("R2 policy contains an unsafe bucket name.")
            values[key] = value
        else:
            if not value.isdigit():
                raise BackupError("R2 policy numeric values must be non-negative integers.")
            values[key] = int(value)
    required = {
        "R2_MAX_STANDARD_BYTES",
        "R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES",
        "R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT",
        "R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS",
    }
    if not required.issubset(values):
        raise BackupError("R2 policy lacks the logical PostgreSQL storage model.")
    return values


def projected_logical_bytes(policy: dict[str, int | str]) -> int:
    result = (
        int(policy["R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES"])
        * int(policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"])
        * int(policy["R2_POSTGRES_LOGICAL_MAX_ENVIRONMENTS"])
    )
    if result <= 0 or result > int(policy["R2_MAX_STANDARD_BYTES"]):
        raise BackupError("The logical PostgreSQL storage projection is outside the R2 envelope.")
    return result


def run_r2_guard(projected_bytes: int) -> None:
    environment = os.environ.copy()
    environment["R2_PROJECTED_ADDITIONAL_BYTES"] = str(projected_bytes)
    try:
        subprocess.run(  # noqa: S603 - fixed installed usage-guard path
            [R2_USAGE_GUARD],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=R2_GUARD_CLIENT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BackupError("R2 usage or projected logical-dump storage is not safe.") from exc


def dump_command(target: ApplicationTarget, snapshot_id: str) -> list[str]:
    snapshot_id = validate_exported_snapshot_id(snapshot_id)
    return [
        "timeout",
        "--foreground",
        f"--kill-after={PG_DUMP_KILL_AFTER_SECONDS}s",
        f"{PG_DUMP_TIMEOUT_SECONDS}s",
        *compose_command(
            target,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-euc",
            'umask 077; export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
            "exec pg_dump --no-password -h 127.0.0.1 "
            f'-U ac_backup -d "$POSTGRES_DB" --format=custom --create --snapshot={snapshot_id}',
        ),
    ]


def parity_command(target: ApplicationTarget, snapshot_id: str) -> list[str]:
    snapshot_id = validate_exported_snapshot_id(snapshot_id)
    tables = parity_tables_for_head(target.migration_head)
    query = " UNION ALL ".join(
        f"SELECT '{table}', count(*)::text FROM \"{table}\""  # noqa: S608 - fixed table allowlist
        for table in tables
    )
    query = (
        "SELECT '__migration_head__', version_num FROM alembic_version UNION ALL " + query  # noqa: S608 - fixed allowlist
    )
    snapshot_query = (
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY; "
        f"SET TRANSACTION SNAPSHOT '{snapshot_id}'; "
        f"{query}; COMMIT;"
    )
    return compose_command(
        target,
        "exec",
        "-T",
        "postgres",
        "sh",
        "-euc",
        'export PGPASSWORD="$AC_DB_BACKUP_PASSWORD"; '
        "exec psql --no-password --no-psqlrc --set=ON_ERROR_STOP=1 "
        '-h 127.0.0.1 -U ac_backup -d "$POSTGRES_DB" -qAt '
        '-c "$1"',
        "--",
        snapshot_query,
    )


def source_row_counts(
    target: ApplicationTarget, snapshot_id: str, *, reader: Callable | None = None
) -> dict[str, int]:
    tables = parity_tables_for_head(target.migration_head)
    result = (reader or run_checked)(
        parity_command(target, snapshot_id),
        target=target,
        timeout_seconds=PG_RESTORE_LIST_TIMEOUT_SECONDS,
    ).stdout.splitlines()
    counts: dict[str, int] = {}
    migration_versions: list[str] = []
    for line in result:
        table, separator, count = line.partition("|")
        if separator and table == "__migration_head__":
            migration_versions.append(count)
            continue
        if not separator or table not in tables or table in counts or not count.isdigit():
            raise BackupError("The source PostgreSQL parity query returned an unsafe result.")
        counts[table] = int(count)
    if migration_versions != [target.migration_head]:
        raise BackupError("The source snapshot migration head differs from the exact release.")
    if set(counts) != set(tables):
        raise BackupError("The source PostgreSQL parity query was incomplete.")
    return counts


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=PG_DUMP_KILL_AFTER_SECONDS)
        # A leader can exit while a descendant retains its pipes. These are
        # owned sessions; always finish group cleanup, never a shared group.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait(timeout=PG_DUMP_KILL_AFTER_SECONDS)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_directory(path: Path) -> None:
    if path.is_symlink():
        raise BackupError("The logical backup directory must not be a symlink.")
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    path.chmod(0o750)
    if grp is None:
        raise BackupError("The Linux ownership implementation is unavailable.")
    try:
        os.chown(path, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
    except (KeyError, OSError) as exc:
        raise BackupError(
            "The logical backup directory must be root-owned and acops-readable."
        ) from exc


def is_root_owned(path: Path) -> bool:
    """Return whether *path* is owned by root without following symlinks."""
    return getattr(path.lstat(), "st_uid", None) == 0


def remove_capture_directory(path: Path, *, temporary: bool) -> None:
    if path.is_symlink() or not path.is_dir() or not is_root_owned(path):
        raise BackupError("A logical-backup capture directory is unsafe.")
    allowed_names = {"backup.dump", "metadata.json"}
    for candidate in path.iterdir():
        if (
            candidate.name not in allowed_names
            or candidate.is_symlink()
            or not candidate.is_file()
            or not is_root_owned(candidate)
        ):
            raise BackupError("A logical-backup capture directory contains an unsafe entry.")
        candidate.unlink()
    if not temporary and any(path.iterdir()):
        raise BackupError("A logical-backup capture directory could not be emptied safely.")
    path.rmdir()


def remove_stale_temporaries(path: Path, environment: str) -> None:
    for candidate in path.iterdir():
        if candidate.name.startswith(f".{environment}-") and candidate.name.endswith(
            ".capture.tmp"
        ):
            remove_capture_directory(candidate, temporary=True)
        elif candidate.name.startswith(".prune-"):
            capture_name = candidate.name.removeprefix(".prune-")
            match = CAPTURE_DIR_RE.fullmatch(capture_name)
            if match is None or match.group(1) != environment:
                raise BackupError("A stale logical-backup prune path is unsafe.")
            remove_capture_directory(candidate, temporary=True)


def fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture_dump(
    target: ApplicationTarget,
    logical_dir: Path,
    max_bytes: int,
    *,
    capture_io: CaptureIO | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    prepare_directory(logical_dir)
    remove_stale_temporaries(logical_dir, target.environment)
    started_at = timestamp()
    temporary_name = tempfile.mkdtemp(
        prefix=f".{target.environment}-", suffix=".capture.tmp", dir=logical_dir
    )
    temporary_dir = Path(temporary_name)
    temporary_dir.chmod(0o750)
    if grp is None:
        temporary_dir.rmdir()
        raise BackupError("The Linux ownership implementation is unavailable.")
    try:
        os.chown(temporary_dir, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
    except (KeyError, OSError) as exc:
        temporary_dir.rmdir()
        raise BackupError("The logical capture must be root-owned and acops-readable.") from exc
    temporary_path = temporary_dir / "backup.dump"
    metadata_path_tmp = temporary_dir / "metadata.json"
    snapshot_holder: ExportedSnapshotHolder | None = None
    process: subprocess.Popen[bytes] | None = None
    bytes_written = 0
    try:
        snapshot_holder = (
            capture_io.holder(target) if capture_io else start_exported_snapshot_holder(target)
        )
        snapshot_holder.assert_alive()
        if capture_io:
            bytes_written = capture_io.dump(target, snapshot_holder.snapshot_id, temporary_path)
            if not 0 < bytes_written <= max_bytes:
                raise BackupError("The bounded capture exceeded its fixed size bound.")
        else:
            process = subprocess.Popen(  # noqa: S603 - fixed exact compose release and timeout
                dump_command(target, snapshot_holder.snapshot_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=compose_environment(target),
                start_new_session=(os.name == "posix"),
            )
            assert process.stdout is not None
            with temporary_path.open("wb") as destination:
                while True:
                    chunk = process.stdout.read(min(1024 * 1024, max_bytes - bytes_written + 1))
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        terminate_process(process)
                        raise BackupError(
                            f"The {target.environment} logical dump exceeded its fixed size bound."
                        )
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if process.wait() != 0:
                raise BackupError(f"The {target.environment} logical dump command failed.")
        if bytes_written == 0:
            raise BackupError(f"The {target.environment} logical dump was empty.")
        if capture_io:
            capture_io.verify(target, temporary_path)
        else:
            with temporary_path.open("rb") as verified_dump:
                restore_result = subprocess.run(  # noqa: S603 - fixed exact compose release
                    compose_command(target, "exec", "-T", "postgres", "pg_restore", "--list"),
                    stdin=verified_dump,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=compose_environment(target),
                    timeout=PG_RESTORE_LIST_TIMEOUT_SECONDS,
                )
            if restore_result.returncode != 0:
                raise BackupError(
                    f"The {target.environment} logical dump failed pg_restore --list verification."
                )
        snapshot_holder.assert_alive()
        row_counts = (
            source_row_counts(target, snapshot_holder.snapshot_id, reader=capture_io.read)
            if capture_io
            else source_row_counts(target, snapshot_holder.snapshot_id)
        )
        snapshot_holder.close()
        snapshot_holder = None
        completed_time = utc_now()
        completed_at = timestamp(completed_time)
        captured_at_epoch_ns = time.time_ns()
        capture_id = f"{completed_time.strftime('%Y%m%dT%H%M%S.%fZ')}-{os.getpid()}"
        digest = sha256_file(temporary_path)
        if capture_io:
            capture_io.remaining()
        metadata: dict[str, object] = {
            "artifact_type": "authority-closers-postgresql-logical",
            "restic_tag": RESTIC_TAG,
            "environment": target.environment,
            "release_id": target.release_dir.name,
            "compose_project": target.compose_project,
            "database_role": "ac_backup",
            "format": "custom",
            "verification": "pg_restore --list",
            "capture_started_at": started_at,
            "capture_completed_at": completed_at,
            "captured_at": completed_at,
            "captured_at_epoch_ns": captured_at_epoch_ns,
            "capture_clock": "CLOCK_REALTIME",
            "dump_bytes": bytes_written,
            "dump_sha256": digest,
            "row_counts": row_counts,
        }
        # Old immutable application controllers accept only the legacy keys.
        # Every reviewed post-0018 schema requires its own exact version identity.
        metadata.update(parity_metadata_fields(target.migration_head))
        metadata_fd = os.open(
            metadata_path_tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o640,
        )
        with os.fdopen(metadata_fd, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, sort_keys=True, separators=(",", ":"))
            metadata_file.write("\n")
            metadata_file.flush()
            os.fsync(metadata_file.fileno())
        metadata_path_tmp.chmod(0o640)
        if grp is None:
            raise BackupError("The Linux ownership implementation is unavailable.")
        try:
            os.chown(metadata_path_tmp, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
            temporary_path.chmod(0o640)
            os.chown(temporary_path, 0, grp.getgrnam("acops").gr_gid, follow_symlinks=False)
        except (KeyError, OSError) as exc:
            raise BackupError(
                "Logical capture files must be root-owned and acops-readable."
            ) from exc
        capture_dir = logical_dir / f"{capture_id}-{target.environment}"
        dump_path = capture_dir / "backup.dump"
        metadata_path = capture_dir / "metadata.json"
        if capture_dir.exists() or capture_dir.is_symlink():
            raise BackupError("The logical capture identity already exists.")
        fsync_directory(temporary_dir)
        temporary_dir.rename(capture_dir)
        fsync_directory(logical_dir)
        return dump_path, metadata_path, metadata
    except Exception:
        cleanup_error: Exception | None = None
        if process is not None and process.poll() is None:
            try:
                terminate_process(process)
            except Exception as error:
                cleanup_error = error
        if snapshot_holder is not None:
            try:
                snapshot_holder.close()
            except Exception as error:
                cleanup_error = error
        if temporary_dir.exists() and not temporary_dir.is_symlink():
            try:
                remove_capture_directory(temporary_dir, temporary=True)
            except Exception as error:
                cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise BackupError(
                "Logical backup snapshot or temporary cleanup failed."
            ) from cleanup_error
        raise


def prune_local_ring(
    logical_dir: Path,
    keep_points: int,
    retained_capture: Path | None = None,
    *,
    validate_only: bool = False,
) -> None:
    environment = logical_dir.parent.name
    if environment not in ENVIRONMENTS or keep_points <= 0:
        raise BackupError("The local logical-backup ring identity is invalid.")
    remove_stale_temporaries(logical_dir, environment)
    captures: list[Path] = []
    for candidate in sorted(logical_dir.iterdir()):
        match = CAPTURE_DIR_RE.fullmatch(candidate.name)
        if match is None or match.group(1) != environment:
            raise BackupError("The local logical-backup ring contains an unknown entry.")
        if candidate.is_symlink() or not candidate.is_dir() or not is_root_owned(candidate):
            raise BackupError("The local logical-backup ring contains an incomplete pair.")
        entries = {entry.name: entry for entry in candidate.iterdir()}
        if set(entries) != {"backup.dump", "metadata.json"} or any(
            entry.is_symlink() or not entry.is_file() or not is_root_owned(entry)
            for entry in entries.values()
        ):
            raise BackupError("The local logical-backup ring contains an incomplete pair.")
        captures.append(candidate)
    if validate_only:
        # A previous failed retention may have left the actually newest pair
        # with an older CLOCK_REALTIME filename. Never guess which valid pair
        # to delete before its replacement has been captured successfully.
        if len(captures) > keep_points:
            raise BackupError(
                "The local logical-backup ring exceeds its retention bound; "
                "existing pairs were preserved and no new capture was started."
            )
        return
    if retained_capture is None:
        recent_captures = set(captures[-keep_points:])
    else:
        if retained_capture not in captures:
            raise BackupError("The retained logical capture is not a verified ring member.")
        other_captures = [capture for capture in captures if capture != retained_capture]
        recent_captures = {retained_capture}
        if keep_points > 1:
            recent_captures.update(other_captures[-(keep_points - 1) :])
    for capture_dir in captures:
        if capture_dir in recent_captures:
            continue
        prune_path = logical_dir / f".prune-{capture_dir.name}"
        if prune_path.exists() or prune_path.is_symlink():
            raise BackupError("The local logical-backup prune identity already exists.")
        capture_dir.rename(prune_path)
        fsync_directory(logical_dir)
        remove_capture_directory(prune_path, temporary=False)
        fsync_directory(logical_dir)


@contextlib.contextmanager
def secure_lock_file(host_root: Path, filename: str) -> Iterator[int]:
    if fcntl is None:
        raise BackupError("The Linux file-lock implementation is unavailable.")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise BackupError("The Linux no-follow lock boundary is unavailable.")
    lock_parent = host_path(host_root, LOCK_ROOT)
    lock_parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if host_root == Path("/"):
        parent_stat = os.stat(lock_parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != 0
            or not parent_stat.st_mode & stat.S_ISVTX
        ):
            raise BackupError("The system lock parent is not a root-owned sticky directory.")
    lock_directory = host_path(host_root, PRIVATE_LOCK_ROOT)
    with contextlib.suppress(FileExistsError):
        lock_directory.mkdir(mode=0o750)
    try:
        directory_fd = os.open(
            lock_directory,
            os.O_RDONLY | os.O_CLOEXEC | directory_flag | no_follow,
        )
    except OSError as exc:
        raise BackupError("The private lock directory could not be opened safely.") from exc
    expected_uid = 0 if host_root == Path("/") else os.geteuid()
    expected_gid = os.getegid()
    if host_root == Path("/"):
        if grp is None:
            os.close(directory_fd)
            raise BackupError("The system group database is unavailable.")
        try:
            expected_gid = grp.getgrnam("acops").gr_gid
        except KeyError as exc:
            os.close(directory_fd)
            raise BackupError("The acops group is unavailable.") from exc
    lock_fd: int | None = None
    try:
        try:
            directory_stat = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != expected_uid:
                raise BackupError("The private lock directory has an unsafe identity.")
            os.fchmod(directory_fd, 0o750)
            os.fchown(directory_fd, expected_uid, expected_gid)
            lock_fd = os.open(
                filename,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | no_follow,
                0o640,
                dir_fd=directory_fd,
            )
            lock_stat = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or lock_stat.st_uid != expected_uid
                or lock_stat.st_nlink != 1
            ):
                raise BackupError("The lock file has an unsafe identity.")
            os.fchmod(lock_fd, 0o640)
            os.fchown(lock_fd, expected_uid, expected_gid)
        except OSError as exc:
            raise BackupError("The private lock boundary could not be opened safely.") from exc
        yield lock_fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


@contextlib.contextmanager
def repository_lock(
    host_root: Path, *, timeout_seconds: float = RESTIC_REPOSITORY_LOCK_WAIT_SECONDS
) -> Iterator[int]:
    with secure_lock_file(host_root, "ac-restic-repository.lock") as lock_fd:
        wait_for_repository_lock(lock_fd, timeout_seconds=timeout_seconds)
        yield lock_fd


def wait_for_repository_lock(
    lock_fd: int, *, timeout_seconds: float = RESTIC_REPOSITORY_LOCK_WAIT_SECONDS
) -> None:
    if not 0 < timeout_seconds <= RESTIC_REPOSITORY_LOCK_WAIT_SECONDS:
        raise BackupError("The Restic repository lock wait bound is invalid.")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise BackupError(
                    "The Restic repository lock could not be acquired safely."
                ) from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackupError(
                    "The Restic repository lock wait timed out; "
                    "another backup, prune, or restore proof remains active."
                ) from exc
            time.sleep(min(RESTIC_REPOSITORY_LOCK_POLL_SECONDS, remaining))


@contextlib.contextmanager
def environment_lock(environment: str, host_root: Path) -> Iterator[None]:
    with secure_lock_file(host_root, f"ac-postgres-backup-{environment}.lock") as lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BackupError(f"Another {environment} logical backup is already active.") from exc
        yield


def upload_command(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
) -> list[str]:
    return [
        "timeout",
        "--foreground",
        f"--kill-after={OPERATION_KILL_AFTER_SECONDS}s",
        f"{RESTIC_UPLOAD_TIMEOUT_SECONDS}s",
        RESTIC_LOGICAL_BACKUP,
        "--",
        RESTIC_LOGICAL_INNER,
        str(dump_path),
        str(metadata_path),
        environment,
    ]


def upload_dump(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
    projected_bytes: int,
    *,
    repository_lock_fd: int | None = None,
) -> None:
    environment_vars = os.environ.copy()
    environment_vars["R2_PROJECTED_ADDITIONAL_BYTES"] = str(projected_bytes)
    command = upload_command(dump_path, metadata_path, environment)
    if repository_lock_fd is not None:
        environment_vars["AC_RESTIC_LOCK_FD"] = str(repository_lock_fd)
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed installed Infisical/Restic wrappers
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=environment_vars,
            pass_fds=(repository_lock_fd,)
            if os.name == "posix" and repository_lock_fd is not None
            else (),
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise BackupError(
            "The encrypted off-host logical snapshot failed "
            "(stage=off_host_upload, reason=launch_failed); the local dump was retained."
        ) from exc
    assert process.stderr is not None
    diagnostic_tail = bytearray()
    diagnostic_read_failed = threading.Event()

    def drain_diagnostics() -> None:
        # Drain continuously to avoid pipe deadlock, retaining only a bounded
        # in-memory tail. Raw child output is never persisted or emitted.
        assert process.stderr is not None
        try:
            while chunk := process.stderr.read(1024):
                diagnostic_tail.extend(chunk)
                del diagnostic_tail[:-UPLOAD_DIAGNOSTIC_MAX_BYTES]
        except OSError:
            diagnostic_read_failed.set()
        finally:
            process.stderr.close()

    reader = threading.Thread(
        target=drain_diagnostics, name=f"ac-upload-diagnostics-{process.pid}", daemon=True
    )
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=RESTIC_UPLOAD_TIMEOUT_SECONDS + OPERATION_KILL_AFTER_SECONDS + 30)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process(process)
    finally:
        reader.join(timeout=1)
    if reader.is_alive():
        # A child retaining stderr must not leave an unbounded background reader
        # or be counted as a successful off-host write.
        terminate_process(process)
        reader.join(timeout=1)
        if reader.is_alive() and os.name == "posix":
            # The leader may have exited before TERM while a descendant kept
            # stderr open. Escalate only this upload's start_new_session group.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            reader.join(timeout=1)
        diagnostic_read_failed.set()
    if diagnostic_read_failed.is_set():
        raise BackupError(
            "The encrypted off-host logical snapshot failed "
            "(stage=off_host_upload, reason=diagnostics_unavailable); "
            "the local dump was retained."
        )
    if timed_out or process.returncode != 0:
        if timed_out or process.returncode == 124:
            reason = "timeout"
        elif process.returncode == 137 or (
            process.returncode is not None and process.returncode < 0
        ):
            reason = "terminated"
        else:
            reason = upload_failure_reason(bytes(diagnostic_tail))
        raise BackupError(
            "The encrypted off-host logical snapshot failed "
            f"(stage=off_host_upload, reason={reason}, exit_status={process.returncode}); "
            "the local dump was retained."
        )


def upload_failure_reason(stderr_tail: bytes) -> str:
    """Return only a fixed diagnostic label, never child text or credentials."""
    diagnostic = stderr_tail.lower()
    signatures = (
        (
            b"ac_backup_failure=repository_lock_descriptor_invalid",
            "repository_lock_descriptor_invalid",
        ),
        (b"ac_backup_failure=repository_lock_timeout", "repository_lock_timeout"),
        (b"ac_backup_failure=repository_lock_unavailable", "repository_lock_unavailable"),
        (b"ac_backup_failure=r2_usage_guard", "r2_usage_guard_failed"),
        (b"unable to create lock in backend", "remote_repository_lock_contention"),
        (b"repository is already locked", "remote_repository_lock_contention"),
        (b"accessdenied", "remote_authorization_failed"),
        (b"invalidaccesskeyid", "remote_authorization_failed"),
        (b"signaturedoesnotmatch", "remote_authorization_failed"),
        (b"unauthorized", "authentication_failed"),
        (b"no such host", "remote_name_resolution_failed"),
        (b"connection refused", "remote_connection_failed"),
        (b"i/o timeout", "remote_timeout"),
    )
    return next(
        (label for signature, label in signatures if signature in diagnostic), "command_failed"
    )


def publish_snapshot(
    dump_path: Path,
    metadata_path: Path,
    environment: str,
    projected_bytes: int,
    *,
    capture_only: bool,
    uploader: Callable[[Path, Path, str, int], None] = upload_dump,
    pruner: Callable[[Path, int, Path | None], None] = prune_local_ring,
    keep_points: int,
) -> None:
    if (
        dump_path.name != "backup.dump"
        or metadata_path.name != "metadata.json"
        or dump_path.parent != metadata_path.parent
    ):
        raise BackupError("The logical snapshot pair does not use the atomic capture contract.")
    logical_dir = dump_path.parent.parent
    if not capture_only:
        try:
            uploader(dump_path, metadata_path, environment, projected_bytes)
        except Exception as upload_error:
            # Protect this exact pair even if CLOCK_REALTIME moved backward.
            try:
                pruner(logical_dir, keep_points, dump_path.parent)
            except Exception:
                raise BackupError(
                    "The off-host logical snapshot failed and local retention could not "
                    "complete; the verified local dump was retained."
                ) from upload_error
            detail = (
                str(upload_error)
                if isinstance(upload_error, BackupError)
                else "Bounded off-host operation failed."
            )
            raise BackupError(
                f"Off-host upload failed; the verified local pair was retained. {detail}"
            ) from upload_error
    # Retention is deliberately after upload. A failed off-host write leaves
    # the verified local dump and its metadata in the bounded ring.
    pruner(logical_dir, keep_points, dump_path.parent)


def run(args: argparse.Namespace) -> None:
    if os.geteuid() != 0:
        raise BackupError("The logical backup must run as root.")
    if args.environment and args.environment not in ENVIRONMENTS:
        raise BackupError("Unsupported application environment.")
    host_root = Path(os.environ.get("AC_POSTGRES_BACKUP_HOST_ROOT", "/")).resolve()
    policy_path = foundation_policy_path(host_root)
    policy = read_policy(policy_path)
    max_dump_bytes = int(policy["R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES"])
    keep_points = int(policy["R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT"])
    projected_bytes = projected_logical_bytes(policy)
    targets = resolve_targets(host_root=host_root, requested_environment=args.environment)
    for target in targets:
        assert_healthy(target)
    if args.dry_run:
        if not args.capture_only:
            run_r2_guard(projected_bytes)
        return
    failures: list[tuple[str, str]] = []
    for target in targets:
        logical_dir = host_path(host_root, BACKUP_ROOT) / target.environment / "logical"
        try:
            with environment_lock(target.environment, host_root):
                # A failed upload must not prevent the next local recovery point.
                # A failed retention pass must prevent another capture from
                # accumulating beyond the ring plus one in-flight pair.
                prepare_directory(logical_dir)
                prune_local_ring(logical_dir, keep_points, validate_only=True)
                dump_path, metadata_path, _metadata = capture_dump(
                    target, logical_dir, max_dump_bytes
                )

                def locked_upload(
                    dump: Path,
                    metadata: Path,
                    environment: str,
                    projected: int,
                ) -> None:
                    with repository_lock(host_root) as repository_lock_fd:
                        run_r2_guard(projected)
                        upload_dump(
                            dump,
                            metadata,
                            environment,
                            projected,
                            repository_lock_fd=repository_lock_fd,
                        )

                publish_snapshot(
                    dump_path,
                    metadata_path,
                    target.environment,
                    projected_bytes,
                    capture_only=args.capture_only,
                    uploader=locked_upload,
                    keep_points=keep_points,
                )
        except (BackupError, OSError, subprocess.SubprocessError) as error:
            # BackupError messages are curated; never print raw filesystem or
            # subprocess diagnostics. Continue the other exact environment's
            # local capture, but do not turn partial/off-host failure into success.
            detail = (
                str(error)
                if isinstance(error, BackupError)
                else "Bounded local operation failed before completion."
            )
            failures.append((target.environment, detail))
    if failures:
        environments = ", ".join(environment for environment, _detail in failures)
        raise BackupError(
            f"Logical backup failed for {environments}. First failure: {failures[0][1]}"
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="validate release and health; also validate R2 unless --capture-only",
    )
    result.add_argument(
        "--capture-only",
        action="store_true",
        help="capture and verify locally without an off-host write",
    )
    result.add_argument(
        "--environment", choices=ENVIRONMENTS, help="limit a run to one exact application release"
    )
    return result


if __name__ == "__main__":
    try:
        run(parser().parse_args())
    except BackupError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        sys.exit(1)
