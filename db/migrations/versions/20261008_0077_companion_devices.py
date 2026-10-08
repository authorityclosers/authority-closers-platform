"""Companion credential history and nullable submission capture provenance."""

from alembic import op

revision = "20261008_0077"
down_revision = "20261005_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE companion_devices (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    person_id UUID NOT NULL,
    name VARCHAR(160) NOT NULL,
    platform VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_companion_devices PRIMARY KEY (id),
    CONSTRAINT fk_companion_devices_tenant_id_memberships FOREIGN KEY(tenant_id, person_id)
      REFERENCES memberships (tenant_id, person_id),
    CONSTRAINT ck_companion_devices_name_bounded CHECK (length(name) BETWEEN 1 AND 160),
    CONSTRAINT ck_companion_devices_platform CHECK (platform IN ( 'android' , 'ios' , 'windows' ,
      'macos' , 'chrome' )),
    CONSTRAINT ck_companion_devices_revocation_time CHECK (revoked_at IS NULL OR revoked_at >=
      created_at)
    )
    """)
    op.execute(
        "CREATE INDEX ix_companion_devices_owner ON companion_devices (tenant_id, person_id)"
    )
    op.execute("""
    CREATE TABLE companion_pairings (
    id UUID NOT NULL,
    code_sha256 VARCHAR(64) NOT NULL,
    poll_secret_sha256 VARCHAR(64) NOT NULL,
    name VARCHAR(160) NOT NULL,
    platform VARCHAR(16) NOT NULL,
    state VARCHAR(16) NOT NULL,
    device_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    collected_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_companion_pairings PRIMARY KEY (id),
    CONSTRAINT ck_companion_pairings_code_hash CHECK (code_sha256 ~ '^[0-9a-f]{64}$' ),
    CONSTRAINT ck_companion_pairings_poll_hash CHECK (poll_secret_sha256 ~ '^[0-9a-f]{64}$' ),
    CONSTRAINT ck_companion_pairings_name_bounded CHECK (length(name) BETWEEN 1 AND 160),
    CONSTRAINT ck_companion_pairings_platform CHECK (platform IN ( 'android' , 'ios' , 'windows' ,
      'macos' , 'chrome' )),
    CONSTRAINT ck_companion_pairings_expiry CHECK (expires_at > created_at AND expires_at <=
      created_at + interval '10 minutes' ),
    CONSTRAINT ck_companion_pairings_state_binding CHECK (state IN ( 'pending' , 'approved' ,
      'denied' , 'collected' ) AND (state IN ( 'approved' , 'collected' )) = (device_id IS NOT
      NULL) AND (state = 'pending' ) = (decided_at IS NULL) AND (state = 'collected' ) =
      (collected_at IS NOT NULL)),
    CONSTRAINT ck_companion_pairings_decision_time CHECK (decided_at IS NULL OR decided_at BETWEEN
      created_at AND expires_at),
    CONSTRAINT ck_companion_pairings_collection_time CHECK (collected_at IS NULL OR collected_at
      BETWEEN decided_at AND expires_at),
    CONSTRAINT uq_companion_pairings_code_sha256 UNIQUE (code_sha256),
    CONSTRAINT uq_companion_pairings_poll_secret_sha256 UNIQUE (poll_secret_sha256),
    CONSTRAINT uq_companion_pairings_device_id UNIQUE (device_id),
    CONSTRAINT fk_companion_pairings_device_id_companion_devices FOREIGN KEY(device_id) REFERENCES
      companion_devices (id)
    )
    """)
    op.execute("""
    CREATE TABLE companion_refresh_families (
    id UUID NOT NULL,
    device_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    absolute_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_companion_refresh_families PRIMARY KEY (id),
    CONSTRAINT ck_companion_refresh_families_absolute_expiry CHECK (absolute_expires_at >
      created_at AND absolute_expires_at <= created_at + interval '90 days' ),
    CONSTRAINT ck_companion_refresh_families_idle_expiry CHECK (idle_expires_at > created_at AND
      idle_expires_at <= absolute_expires_at),
    CONSTRAINT ck_companion_refresh_families_revocation_time CHECK (revoked_at IS NULL OR
      revoked_at >= created_at),
    CONSTRAINT fk_companion_refresh_families_device_id_companion_devices FOREIGN KEY(device_id)
      REFERENCES companion_devices (id)
    )
    """)
    op.execute(
        "CREATE INDEX ix_companion_refresh_families_device_id "
        "ON companion_refresh_families (device_id)"
    )
    op.execute("""
    CREATE TABLE companion_credentials (
    id UUID NOT NULL,
    family_id UUID NOT NULL,
    kind VARCHAR(16) NOT NULL,
    token_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_companion_credentials PRIMARY KEY (id),
    CONSTRAINT ck_companion_credentials_token_hash CHECK (token_sha256 ~ '^[0-9a-f]{64}$' ),
    CONSTRAINT ck_companion_credentials_kind_expiry CHECK (expires_at > created_at AND ((kind =
      'access' AND expires_at <= created_at + interval '15 minutes' ) OR (kind = 'refresh' AND
      expires_at <= created_at + interval '30 days' ) OR (kind = 'web_session' AND expires_at <=
      created_at + interval '60 seconds' ))),
    CONSTRAINT ck_companion_credentials_consumption_time CHECK (consumed_at IS NULL OR consumed_at
      BETWEEN created_at AND expires_at),
    CONSTRAINT fk_companion_credentials_family_id_companion_refresh_families FOREIGN
      KEY(family_id) REFERENCES companion_refresh_families (id),
    CONSTRAINT uq_companion_credentials_token_sha256 UNIQUE (token_sha256)
    )
    """)
    op.execute(
        "CREATE INDEX ix_companion_credentials_family_id ON companion_credentials (family_id)"
    )
    op.execute("ALTER TABLE conversation_guest_submissions ADD COLUMN capture_source VARCHAR(32)")
    op.execute("""
    ALTER TABLE conversation_guest_submissions ADD CONSTRAINT
    ck_conversation_guest_submissions_capture_source CHECK (capture_source IN (
    'web_upload' , 'browser_display_capture' , 'android_dialer_pickup' , 'android_share' ,
    'ios_share' , 'ios_recorder' , 'desktop_recorder' , 'desktop_watch_folder' , 'chrome_tab' ))
    """)
    op.execute("""
    CREATE FUNCTION ac_companion_credential_history() RETURNS trigger AS $$
    BEGIN
    IF (to_jsonb(NEW) - 'consumed_at' ) IS DISTINCT FROM (to_jsonb(OLD) - 'consumed_at' )
    OR (OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at)
    THEN RAISE EXCEPTION 'companion credential history is immutable' ; END IF;
    RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER companion_credential_history BEFORE UPDATE ON companion_credentials
    FOR EACH ROW EXECUTE FUNCTION ac_companion_credential_history();
    """)


def downgrade() -> None:
    raise RuntimeError("forward-only")
