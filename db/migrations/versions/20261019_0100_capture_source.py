"""Capture sources for recordings made in the Sales Xray Android app (ADR 0056 F2, 19 Oct 2026).

The phone app records two ways besides picking up the dialer's own files
(android_dialer_pickup): conversations recorded in the app
(android_in_app_recorder) and phone or internet calls recorded by its optional
call recorder (android_call_recorder). The call data engine compares transcript
quality by capture source, never by file name (ADR 0056 section 4).

Chain: after 20261019_0099 (budget settings). Only the CHECK on
conversation_guest_submissions.capture_source changes; no table, no data.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0100"
down_revision = "20261019_0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_conversation_guest_submissions_capture_source"),
        "conversation_guest_submissions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_conversation_guest_submissions_capture_source"),
        "conversation_guest_submissions",
        "capture_source IN ('web_upload', 'browser_display_capture', 'android_dialer_pickup', "
        "'android_share', 'ios_share', 'ios_recorder', 'desktop_recorder', "
        "'desktop_watch_folder', 'chrome_tab', 'android_in_app_recorder', "
        "'android_call_recorder')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(sa.text("LOCK TABLE conversation_guest_submissions IN ACCESS EXCLUSIVE MODE"))
    submissions = sa.table("conversation_guest_submissions", sa.column("capture_source"))
    if op.get_bind().scalar(
        sa.select(
            sa.exists().where(
                submissions.c.capture_source.in_(
                    ("android_in_app_recorder", "android_call_recorder")
                )
            )
        )
    ):
        raise RuntimeError("Android capture-source history requires forward recovery.")
    op.drop_constraint(
        op.f("ck_conversation_guest_submissions_capture_source"),
        "conversation_guest_submissions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_conversation_guest_submissions_capture_source"),
        "conversation_guest_submissions",
        # Same list as 0078, written the way PostgreSQL deparses it after pg_restore, so the
        # downgrade matches the restored baseline exactly (as 0095 learned).
        "(capture_source)::text = ANY (ARRAY["
        "('web_upload'::character varying)::text, "
        "('browser_display_capture'::character varying)::text, "
        "('android_dialer_pickup'::character varying)::text, "
        "('android_share'::character varying)::text, "
        "('ios_share'::character varying)::text, "
        "('ios_recorder'::character varying)::text, "
        "('desktop_recorder'::character varying)::text, "
        "('desktop_watch_folder'::character varying)::text, "
        "('chrome_tab'::character varying)::text"
        "])",
    )
