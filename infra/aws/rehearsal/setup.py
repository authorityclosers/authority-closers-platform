#!/usr/bin/env python3
"""Generate throwaway configuration ON an isolated rehearsal host; never import env."""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path.home() / "rehearsal"
PIN = "8eac71cb1c0606b2faf344b2589ebcb08343ab3b"


def main():
    os.umask(0o077)
    ROOT.mkdir(exist_ok=True)
    marker = ROOT / "FICTIONAL-ONLY"
    if (ROOT / "runtime.env").exists():
        raise SystemExit("Existing configuration: refusing credential replacement")
    marker.write_text("Isolated AWS rehearsal; no production data or credentials\n")
    for name in (
        "state",
        "media",
        "scanner",
        "storage",
        "scratch",
        "native",
        "identities",
        "spool",
        "evidence",
    ):
        (ROOT / name).mkdir(exist_ok=True)
    for name in ("storage", "scratch"):
        (ROOT / name / ".ac-recording-storage").write_bytes(
            b"ac.private-local-recording-storage/1\n"
        )
    tenant, owner = str(uuid4()), str(uuid4())
    operations = str(uuid4())
    now = int(time.time())
    approval = dict(
        schema="ac.sales-xray.hosted-approval/1",
        environment="production",
        provider_control_tenant_id=operations,
        deployment_ref="ref:rehearsal:fictional",
        issued_at_epoch=now - 60,
        expires_at_epoch=now + 604800,
        budget_scope_id=str(uuid4()),
        budget_authorization_ref="ref:rehearsal:no-spend",
        budget_owner_id=owner,
        budget_cap_paise=0,
        intake_authorization_ref="ref:rehearsal:fictional",
        intake_retention_ref="ref:rehearsal:disposable",
        retention_days=1,
        max_stored_source_bytes=1073741824,
        allowances=[],
        stages=[],
    )
    raw = json.dumps(approval).encode()
    (ROOT / "approval.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    service = dict(
        schema_version="ac.sales_xray.worker_service/1",
        environment="production",
        release_id=PIN,
        operations_tenant_id=operations,
        bootstrap_only=True,
        sales_xray_approval_path="/run/ac-sales-xray/approval.json",
        sales_xray_approval_sha256=digest,
        sales_xray_storage_root=str(ROOT / "storage"),
        sales_xray_scratch_root=str(ROOT / "scratch"),
        database_url_file="/run/ac-sales-xray/database-url",
        native_socket_path=str(ROOT / "native/native.sock"),
        native_image_ref="sha256:" + "0" * 64,
        providers=[],
        provider_consumers=1,
    )
    service_raw = json.dumps(service).encode()
    (ROOT / "service.json").write_bytes(service_raw)
    env = dict(
        AC_COMPOSE_PROJECT="ac-rehearsal",
        AC_ENVIRONMENT="production",
        AC_RELEASE_ID=PIN,
        AC_STATE_ROOT=str(ROOT / "state"),
        AC_API_IMAGE=f"ghcr.io/authorityclosers/authority-closers-api:{PIN}",
        AC_POSTGRES_IMAGE="pgvector/pgvector:pg17",
        AC_PGBOUNCER_IMAGE="edoburu/pgbouncer@sha256:4a8371e79d6627e74f553d0aaa8e4c5ace20e30034fb296e569b71c89c99e108",
        AC_OPERATIONS_TENANT_ID=operations,
        AC_PUBLIC_LEARNER_TENANT_ID=str(uuid4()),
        AC_LEARNER_CONSENT_VERSION="fictional-rehearsal-v1",
        AC_EXTERNAL_SIDE_EFFECTS_HOLD="true",
        AC_PUBLIC_APP_URL="https://learner.authorityclosers.com",
        AC_ADMIN_APP_URL="https://admin.authorityclosers.com",
        AC_COACH_APP_URL="https://coach.authorityclosers.com",
        AC_API_URL="https://api.authorityclosers.com",
        AC_SALES_XRAY_APP_URL="https://salesxray.authorityclosers.com",
        AC_API_HOST="api.authorityclosers.com",
        AC_INTERNAL_API_HOST="api.production.ac.internal.invalid",
        AC_TRUSTED_PROXY_ADDRESSES="172.30.29.10",
        AC_EDGE_API_ALIAS="rehearsal-api",
        AC_EDGE_LEARNER_ALIAS="rehearsal-learner",
        AC_EDGE_ADMIN_ALIAS="rehearsal-admin",
        AC_EDGE_COACH_ALIAS="rehearsal-coach",
        AC_HEAVY_SCANNER_TUNNEL_ROOT=str(ROOT / "scanner"),
        AC_MEDIA_SCANNER_HOST_ROOT=str(ROOT / "scanner"),
        AC_MEDIA_FILESYSTEM_HOST_ROOT=str(ROOT / "media"),
        AC_PGBOUNCER_AUTH_FILE=str(ROOT / "userlist.txt"),
        AC_XRAY_APPROVAL_FILE=str(ROOT / "approval.json"),
        AC_XRAY_APPROVAL_SHA256=digest,
        AC_XRAY_SERVICE_CONFIG=str(ROOT / "service.json"),
        AC_XRAY_SERVICE_SHA256=hashlib.sha256(service_raw).hexdigest(),
        AC_XRAY_STORAGE_ROOT=str(ROOT / "storage"),
        AC_XRAY_SCRATCH_ROOT=str(ROOT / "scratch"),
        AC_XRAY_NATIVE_SOCKET_DIR=str(ROOT / "native"),
        AC_XRAY_NATIVE_IMAGE_REF="sha256:" + "0" * 64,
        AC_XRAY_ACQUISITION_ENABLED="false",
        AC_XRAY_ACQUISITION_POLICY_REVISION="fictional-rehearsal-v1",
        AC_XRAY_CHALLENGE_SITE_KEY="fictional-rehearsal",
        AC_XRAY_INFISICAL_BINARY="/bin/false",
        AC_XRAY_CHALLENGE_SECRET_FILE=str(ROOT / "challenge-secret"),
        AC_XRAY_DATABASE_URL_FILE=str(ROOT / "database-url"),
        AC_XRAY_POOLED_DATABASE_URL_FILE=str(ROOT / "pooled-database-url"),
    )
    for provider in ("ELEVENLABS", "DEEPGRAM", "GROQ", "GEMINI", "OPENAI"):
        env[f"AC_XRAY_{provider}_IDENTITY_DIR"] = str(ROOT / "identities")
    for role in ("LEARNER", "ADMIN", "COACH"):
        env[f"AC_{role}_IMAGE"] = (
            f"ghcr.io/authorityclosers/authority-closers-{role.lower()}-web:{PIN}"
        )
    for key in (
        "AC_POSTGRES_OWNER_PASSWORD",
        "AC_DB_MIGRATOR_PASSWORD",
        "AC_DB_RUNTIME_PASSWORD",
        "AC_DB_BACKUP_PASSWORD",
        "AC_SESSION_TOKEN_PEPPER",
        "AC_OAUTH_TRANSACTION_SECRET",
        "AC_EMAIL_CHALLENGE_SECRET",
        "AC_GOOGLE_OAUTH_CLIENT_ID",
        "AC_GOOGLE_OAUTH_CLIENT_SECRET",
        "AC_LEAD_DESK_TOKEN_KEY",
    ):
        env[key] = secrets.token_hex(32)
    env["AC_GOOGLE_OAUTH_CLIENT_ID"] += ".apps.googleusercontent.com"
    runtime = (
        f"postgresql+psycopg://ac_runtime:{env['AC_DB_RUNTIME_PASSWORD']}@postgres:5432/ac_platform"
    )
    pooled = runtime.replace("@postgres:5432", "@pgbouncer:6432")
    env["AC_DATABASE_URL"] = runtime
    env["AC_LEAN_DATABASE_URL"] = pooled
    env["AC_DATABASE_MIGRATOR_URL"] = (
        f"postgresql+psycopg://ac_migrator:{env['AC_DB_MIGRATOR_PASSWORD']}@postgres:5432/ac_platform"
    )
    for name, value in [
        ("database-url", runtime),
        ("pooled-database-url", pooled),
        ("challenge-secret", secrets.token_hex(32)),
    ]:
        (ROOT / name).write_text(value + "\n")
    (ROOT / "userlist.txt").write_text("")  # filled with the database-generated SCRAM verifier
    (ROOT / "runtime.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    (ROOT / "fixture-ids.json").write_text(json.dumps(dict(tenant=tenant, owner=owner)))
    print("Fictional configuration created; credentials retained on this host only")


if __name__ == "__main__":
    main()
