"""Fictional path/evidence fixtures for the M1a/M1b merge rule."""

import builtins
import os
import socket
import sys
from pathlib import Path

import pytest

# Support both pytest's console entry point and python -m pytest in importlib mode.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci.merge_class import classify_changed_files  # noqa: E402

PROTECTED = [
    ("apps/nested/AGENTS.md", "protected:instructions"),
    ("docs/CLAUDE.md", "protected:instructions"),
    (".github/workflows/check.yml", "protected:automation"),
    ("infra/config.py", "protected:automation"),
    ("scripts/ci/check.py", "protected:automation"),
    ("scripts/ops/check.py", "protected:automation"),
    ("scripts/data-changes/production-membership.py", "protected:automation"),
    ("scripts/ac_task.py", "protected:automation"),
    ("apps/Dockerfile", "protected:deployment"),
    ("apps/Dockerfile.dev", "protected:deployment"),
    ("apps/Dockerfile-dev", "protected:deployment"),
    ("apps/Dockerfile_dev", "protected:deployment"),
    ("apps/api.Dockerfile", "protected:deployment"),
    ("apps/compose.yml", "protected:deployment"),
    ("apps/docker-compose.dev.yaml", "protected:deployment"),
    ("apps/.env", "protected:secrets"),
    ("apps/dev.env.example", "protected:secrets"),
    ("packages/secrets/config.json", "protected:secrets"),
    ("tools/.infisical.json", "protected:secrets"),
    ("db/migrations/0001_add.py", "protected:migration"),
    ("scripts/ci/merge_class.py", "protected:classifier"),
] + [
    (f"apps/{term}/config.py", f"protected:name:{term}")
    for term in (
        "payment",
        "billing",
        "price",
        "checkout",
        "subscription",
        "top-up",
        "credit",
        "entitlement",
        "consent",
        "retention",
        "deletion",
        "score",
        "purchase",
    )
]
# Identity, authentication, sessions, permissions/roles and organisation membership (AUT-932).
PROTECTED += [
    (path, "protected:identity")
    for path in (
        "packages/python/ac_platform/http/auth.py",
        "packages/python/ac_platform/http/organisation.py",
        "packages/python/ac_platform/identity/models.py",
        "packages/python/ac_platform/authorization/policy.py",
        "packages/python/ac_platform/tenancy/services.py",
        "packages/python/ac_platform/organisations/service.py",
        "packages/python/ac_platform/bootstrap/cli.py",
        "packages/python/ac_platform/kernel/authz.py",
        "packages/python/ac_platform/media/delivery_authorizer.py",
        "packages/x/authorised.py",
        "packages/x/authenticator.py",
        "packages/x/oauth_callback.py",
        "packages/x/csrf.py",
        "packages/x/jwt.py",
        "packages/x/credentials.py",
        "packages/x/capability_grants.py",
        "packages/x/organization.ts",
        "packages/x/membership.py",
        "packages/x/review_invitations.py",
        "packages/x/ownership_transfer.py",
        "apps/web/app/login/page.tsx",
        "apps/web/app/sign-up.tsx",
        "apps/web/app/sign-out-control.tsx",
        "apps/web/app/forgot-password/page.tsx",
        "apps/web/app/session-expired/page.tsx",
        "apps/web/app/lib/server-auth.ts",
        "apps/web/app/workspace-access.tsx",
        "apps/web/app/people/grants/page.tsx",
        "apps/web/app/role-picker.tsx",
        "apps/web/app/permissions.ts",
        "apps/web/app/members/list.tsx",
        "apps/web/app/tenant-switcher.tsx",
        "apps/web/app/cookie.ts",
        "tests/security/test_http_boundary.py",
    )
]


def classify(path, status="modified", previous=None):
    record = {"filename": path, "status": status}
    if previous is not None:
        record["previous_filename"] = previous
    return classify_changed_files([record], {path: "fictional head"}, changed_files=1)


@pytest.mark.parametrize("path,reason", PROTECTED)
@pytest.mark.parametrize("case", [str, str.upper])
@pytest.mark.parametrize("direction", ["added", "modified", "removed", "rename-in", "rename-out"])
def test_protected_paths_both_rename_names_and_deletes(path, reason, case, direction):
    path = case(path)
    result = (
        classify(path, "renamed", "apps/ordinary.py")
        if direction == "rename-in"
        else classify("apps/ordinary.py", "renamed", path)
        if direction == "rename-out"
        else classify(path, direction)
    )
    assert result["class"] == "escalation"
    assert reason in result["reasons"]
    assert result["reasons"] == sorted(set(result["reasons"]))


@pytest.mark.parametrize("root", ["apps", "packages", "tests", "docs", "tools"])
@pytest.mark.parametrize("status", ["added", "modified", "removed", "renamed"])
def test_ordinary_roots(root, status):
    assert classify(
        f"{root}/ordinary.py", status, "apps/old.py" if status == "renamed" else None
    ) == {
        "class": "routine",
        "reasons": [],
    }


# PR #221 (AUT-786: organisation roles and ownership transfer) merged on one review (AUT-932).
PR_221 = [
    "packages/python/ac_platform/http/organisation.py",
    "packages/python/ac_platform/organisations/service.py",
    "tests/integration/test_organisation_owner_transfer_postgresql.py",
    "tests/unit/http/test_organisation_member_writes.py",
]


@pytest.mark.parametrize("files", [PR_221, *[[path] for path in PR_221]])
def test_identity_and_membership_changes_escalate(files):
    records = [{"filename": path, "status": "modified"} for path in files]
    contents = {path: "fictional head" for path in files}
    result = classify_changed_files(records, contents, changed_files=len(files))
    assert result == {"class": "escalation", "reasons": ["protected:identity"]}


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/app/signIn.tsx",
        "apps/web/app/SignOutButton.tsx",
        "apps/web/app/adminRoles.ts",
        "apps/web/app/userAuthPanel.tsx",
        "apps/web/app/OAuthCallback.tsx",
        "apps/web/app/teamMembers.tsx",
    ],
)
def test_camel_case_identity_words_escalate(path):
    assert classify(path) == {"class": "escalation", "reasons": ["protected:identity"]}


@pytest.mark.parametrize(
    "path",
    [
        "packages/python/ac_platform/conversation_intelligence/author_notes.py",
        "apps/web/app/authority-closers-logo.svg",
        "docs/authoring-guide.md",
        "packages/python/ac_platform/media/signing.py",
        "apps/web/app/maintenance.tsx",
        "apps/web/app/accessibility.css",
        "apps/web/app/roleplay/page.tsx",
        "apps/web/app/remember-choice.ts",
        "tools/authors.txt",
    ],
)
@pytest.mark.parametrize("case", [str, str.upper])
def test_identity_terms_avoid_lookalike_words(path, case):
    result = classify(case(path))
    assert "protected:identity" not in result["reasons"]
    if case is str:
        assert result == {"class": "routine", "reasons": []}


@pytest.mark.parametrize(
    "path", ["README.md", "new-root/file.py", "scripts/other.py", "db/model.py", "APPS/ordinary.py"]
)
def test_unknown_roots(path):
    assert classify(path) == {"class": "escalation", "reasons": ["path:unknown-root"]}


@pytest.mark.parametrize(
    "record,reason",
    [
        (None, "evidence:record"),
        ({}, "evidence:path"),
        ({"filename": "apps/file.py"}, "evidence:status"),
        ({"filename": "apps/file.py", "status": []}, "evidence:status"),
        ({"filename": "apps/file.py", "status": "copied"}, "evidence:status"),
        ({"filename": "apps/file.py", "status": "renamed"}, "evidence:rename"),
        (
            {"filename": "apps/file.py", "status": "renamed", "previous_filename": "apps/file.py"},
            "evidence:rename",
        ),
        (
            {"filename": "apps/file.py", "status": "modified", "previous_filename": "apps/old.py"},
            "evidence:rename",
        ),
    ],
)
def test_missing_malformed_or_ambiguous_records(record, reason):
    result = classify_changed_files([record], {"apps/file.py": ""}, changed_files=1)
    assert result["class"] == "escalation" and reason in result["reasons"]


@pytest.mark.parametrize(
    "path",
    [
        None,
        3,
        "",
        "/apps/x.py",
        "apps//x.py",
        "apps/../x.py",
        "apps/./x.py",
        "apps\\x.py",
        "apps/x\x00.py",
        "apps/x\n.py",
        " apps/x.py",
    ],
)
def test_invalid_paths(path):
    assert "evidence:path" in classify(path)["reasons"]
    assert "evidence:rename" in classify("apps/x.py", "renamed", path)["reasons"]


@pytest.mark.parametrize(
    "files,contents,count,truncated,reason",
    [
        (None, {}, 0, False, "evidence:records"),
        ("apps/x.py", {}, 0, False, "evidence:records"),
        ([], {}, 1, False, "evidence:count"),
        ([], {}, True, False, "evidence:count"),
        ([], {}, -1, False, "evidence:count"),
        ([], {}, None, False, "evidence:count"),
        ([], {}, 0, True, "evidence:truncated"),
        ([], {}, 0, None, "evidence:truncation-flag"),
        ([], None, 0, False, "evidence:contents"),
        ([{"filename": "apps/x.py", "status": "modified"}], {}, 1, False, "evidence:contents"),
        (
            [{"filename": "apps/x.py", "status": "added"}],
            {"apps/x.py": b"bytes"},
            1,
            False,
            "evidence:contents",
        ),
        ([{"filename": "apps/x.py", "status": "removed"}] * 2, {}, 2, False, "evidence:duplicate"),
    ],
)
def test_incomplete_evidence(files, contents, count, truncated, reason):
    result = classify_changed_files(files, contents, changed_files=count, truncated=truncated)
    assert result["class"] == "escalation" and reason in result["reasons"]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("apps/.env", ["protected:secrets"]),
        ("apps/billing/config.json", ["protected:name:billing"]),
        ("apps/payment/config.json", ["protected:name:payment"]),
        ("apps/purchase.py", ["protected:name:purchase"]),
        (
            "scripts/data-changes/production-membership.py",
            ["path:unknown-root", "protected:automation", "protected:identity"],
        ),
        ("apps/deletion.py", ["protected:name:deletion"]),
    ],
)
@pytest.mark.parametrize(
    "direction", ["modified", "rename-in", "rename-out", "missing", "ambiguous"]
)
def test_owner_only_fixtures_fail_closed_with_exact_stable_reasons(path, expected, direction):
    record = {"filename": path, "status": "modified"}
    if direction == "rename-in":
        record.update(status="renamed", previous_filename="apps/ordinary.py")
    elif direction == "rename-out":
        record.update(filename="apps/ordinary.py", status="renamed", previous_filename=path)
    elif direction == "missing":
        record.update(status="renamed")
        expected = ["evidence:rename", *expected]
    elif direction == "ambiguous":
        record.update(previous_filename="apps/ordinary.py")
        expected = ["evidence:rename", *expected]
    result = classify_changed_files([record], {record["filename"]: ""}, changed_files=1)
    assert result == {"class": "escalation", "reasons": sorted(expected)}


def test_purity_determinism_no_semantics_or_input_mutation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("classifier attempted external IO or input execution")

    files = [
        {"filename": "apps/ordinary.py", "status": "modified"},
        {"filename": "apps/payment.py", "status": "removed"},
        {"filename": "apps/payment-billing.py", "status": "removed"},
    ]
    contents = {"apps/ordinary.py": "import os; os.system('fictional'); billing score deletion"}
    with monkeypatch.context() as patch:
        for target, name in [
            (builtins, "open"),
            (builtins, "exec"),
            (builtins, "eval"),
            (os, "system"),
            (socket, "socket"),
            (builtins, "__import__"),
        ]:
            patch.setattr(target, name, forbidden)
        results = [
            classify_changed_files(records, contents, changed_files=len(records))
            for records in (files, files[::-1], files[:1])
        ]
    expected = {
        "class": "escalation",
        "reasons": ["protected:name:billing", "protected:name:payment"],
    }
    assert results[:2] == [expected, expected]
    assert results[2] == {
        "class": "routine",
        "reasons": [],
    }
    assert files[1] == {"filename": "apps/payment.py", "status": "removed"}
    assert contents["apps/ordinary.py"].startswith("import os;")


# M1b: fictional added-migration fixtures. Contents are parsed only, never executed.
MIGRATION = "db/migrations/versions/20990101_0001_fictional.py"
HEADER = '''"""Fictional migration."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fictional_0001"
down_revision: str | None = "fictional_0000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
'''
DOWNGRADE = '\n\ndef downgrade() -> None:\n    op.drop_table("fictional_widgets")\n'
ESCALATED = ["path:unknown-root", "protected:migration"]


def migration(body, header=HEADER, downgrade=DOWNGRADE):
    return f"{header}\n\ndef upgrade() -> None:\n    {body}\n{downgrade}"


def classify_migration(content, path=MIGRATION, status="added"):
    record = {"filename": path, "status": status}
    return classify_changed_files([record], {path: content}, changed_files=1)


ALLOWED = [
    "pass",
    '"""Only a docstring."""',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid(), nullable=False),'
    ' sa.Column("label", sa.String(length=80), nullable=False),'
    ' sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),'
    ' sa.Column("data", postgresql.JSONB(), nullable=True),'
    ' sa.PrimaryKeyConstraint("id", name=op.f("pk_fictional_widgets")))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Integer, primary_key=True),'
    ' schema="fictional", if_not_exists=True)',
    'op.create_index("ix_fictional", "fictional_widgets", ["label"])',
    'op.create_index(op.f("ix_fictional"), "fictional_widgets", ("label", "id"), unique=False)',
    'op.create_index("ix_fictional", "fictional_widgets", ["label"], schema="f",'
    " if_not_exists=True)",
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text(), nullable=True))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Integer(), server_default="0"))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Integer(), server_default="0",'
    " nullable=False))",
    'op.add_column("fictional_widgets", sa.Column("on", sa.Boolean(), server_default=sa.false(),'
    " nullable=False))",
    'op.add_column("fictional_widgets", sa.Column("on", sa.Boolean(), server_default=sa.true()))',
    'op.add_column("fictional_widgets", sa.Column("state", sa.String(20),'
    " server_default=sa.text(\"'draft'\"), nullable=False))",
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text(), nullable=True,'
    ' comment="fictional"), schema="fictional")',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid(), nullable=False))\n'
    '    op.create_index("ix_fictional", "fictional_widgets", ["id"])',
    'op.create_table("fictional_widgets", sa.Column("amount", sa.Numeric(10, 2)),'
    ' sa.Column("ok", sa.Numeric(precision=12, scale=4, asdecimal=False)))',
]


def text_default(sql):
    return (
        'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), nullable=False,'
        f" server_default=sa.text({sql!r})))"
    )


# Every sa.text() form main's migrations use, plus ::jsonb literals.
TEXT_ALLOWED = [
    "0", "5", "-1", "2.50", "true", "false", "now()", "'active'", "'pending'",
    "'course-completion'", "'audit.enrollment.created.v1'", "''", "'[]'", "'{}'",
    "'{}'::jsonb", "'[]'::jsonb",
]  # fmt: skip
ALLOWED += [text_default(sql) for sql in TEXT_ALLOWED]


@pytest.mark.parametrize("body", ALLOWED)
def test_added_additive_migration_is_routine(body):
    assert classify_migration(migration(body)) == {"class": "routine", "reasons": []}


DISALLOWED = [
    # Unique indexes and dynamic index flags.
    'op.create_index("ix_f", "fictional_widgets", ["label"], unique=True)',
    'op.create_index("ix_f", "fictional_widgets", ["label"], unique=UNIQUE)',
    'op.create_index("ix_f", "fictional_widgets", ["label"], unique=None)',
    'op.create_index("ix_f", "fictional_widgets", ["label"], unique=False, unique=False)',
    'op.create_index("ix_f", "fictional_widgets", ["label"], postgresql_where=sa.text("x"))',
    'op.create_index("ix_f", "fictional_widgets", [sa.text("lower(label)")])',
    'op.create_index("ix_f", "fictional_widgets", [])',
    'op.create_index("ix_f", "fictional_widgets", COLUMNS)',
    'op.create_index(NAME, "fictional_widgets", ["label"])',
    'op.create_index(f"ix_{NAME}", "fictional_widgets", ["label"])',
    # Implicit nullability, NOT NULL without default, None/dynamic defaults.
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text()))',
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text(), nullable=False))',
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text(), nullable=NULLABLE))',
    'op.add_column("fictional_widgets", sa.Column("note", sa.Text(), nullable=not False))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=None))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=DEFAULT))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=helper()))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=sa.text(SQL)))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=f"{X}"))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Integer(), server_default=0))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), server_default=sa.func.x()))',
    'op.add_column("fictional_widgets", sa.Column("id", sa.Uuid(), primary_key=True,'
    " nullable=True))",
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), nullable=True, **OPTIONS))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), nullable=True, unique=True))',
    'op.add_column("fictional_widgets", sa.Column("n", sa.Text(), nullable=True, index=True))',
    'op.add_column("fictional_widgets", COLUMN)',
    'op.add_column(TABLE, sa.Column("n", sa.Text(), nullable=True))',
    # Foreign key, unique and check constraints, unknown or helper-built types.
    'op.add_column("fictional_widgets", sa.Column("p", sa.Uuid(), sa.ForeignKey("p.id"),'
    " nullable=True))",
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid()),'
    ' sa.ForeignKeyConstraint(["id"], ["p.id"]))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid()), sa.UniqueConstraint("id"))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid()), sa.CheckConstraint("id"))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Uuid()), sa.Index("ix", "id"))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.Enum("a", name="fictional")))',
    'op.create_table("fictional_widgets", sa.Column("id", helper_type()))',
    'op.create_table("fictional_widgets", sa.Column("id", sa.String(length=LENGTH)))',
    'op.create_table("fictional_widgets", *COLUMNS)',
    'op.create_table("fictional_widgets")',
    'op.create_table(TABLE, sa.Column("id", sa.Uuid()))',
    # Type arguments are written into DDL raw: strings, collations and unknown keywords.
    'op.create_table("fictional_widgets", sa.Column("n", sa.Numeric("10) CHECK (false")))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.Numeric(precision="10")))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(collation="C")))',
    'op.create_table("fictional_widgets",'
    """ sa.Column("n", sa.String(collation='C" ; DROP TABLE x; --')))""",
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(64, "C")))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(length=1.5)))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(length=-1)))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(length=None)))',
    'op.create_table("fictional_widgets", sa.Column("n", sa.String(**OPTIONS)))',
    'op.create_table("fictional_widgets", sa.Column("n", postgresql.JSONB(astext_type=1)))',
    # Raw SQL, execute, destructive, alter, rename, batch and other schema ops.
    'op.execute("CREATE TABLE fictional_widgets (id int)")',
    'op.execute(sa.text("UPDATE fictional_widgets SET n = 1"))',
    'op.get_bind().exec_driver_sql("SELECT 1")',
    'op.drop_table("fictional_widgets")',
    'op.drop_column("fictional_widgets", "note")',
    'op.drop_index("ix_fictional")',
    'op.drop_constraint("ck_fictional", "fictional_widgets")',
    'op.alter_column("fictional_widgets", "note", nullable=False)',
    'op.rename_table("fictional_widgets", "fictional_gadgets")',
    'op.alter_column("fictional_widgets", "note", new_column_name="memo")',
    'with op.batch_alter_table("fictional_widgets") as batch:\n'
    '        batch.add_column(sa.Column("note", sa.Text(), nullable=True))',
    'op.create_foreign_key(None, "fictional_widgets", "p", ["p_id"], ["id"])',
    'op.create_unique_constraint("uq_fictional", "fictional_widgets", ["label"])',
    'op.create_check_constraint("ck_fictional", "fictional_widgets", "n > 0")',
    'op.bulk_insert(sa.table("fictional_widgets"), [{"n": 1}])',
    'op.create_table_comment("fictional_widgets", "fictional")',
    # Any statement other than an allowed op call is not static enough.
    'table = "fictional_widgets"\n    op.create_index("ix_f", table, ["label"])',
    'for name in ["a"]:\n        op.create_index(name, "fictional_widgets", ["label"])',
    'if True:\n        op.create_index("ix_f", "fictional_widgets", ["label"])',
    'op.create_index("ix_f", "fictional_widgets", ["label"]) or helper()',
    "helper()",
    'getattr(op, "drop_table")("fictional_widgets")',
    'sa.create_table("fictional_widgets")',
    'import os\n    os.system("fictional")',
    "return None",
]


# sa.text() defaults are written into DDL unchanged: only whole literal forms are static.
TEXT_DISALLOWED = [
    "0; DROP TABLE demo_victim; --", "gen_random_uuid()", "now() + interval '1 day'",
    "NOW()", "TRUE", "1e3", "0x10", "1.", ".5", "--", "0 --", "'a' || 'b'", "'it''s'",
    "'a;b'", "'a--b'", "'a\\b'", "'unterminated", "'a'::text", "'{}'::jsonb; SELECT 1",
    "now()\n", " 0", "", "current_timestamp", "nextval('fictional_seq')", "(0)",
]  # fmt: skip
DISALLOWED += [text_default(sql) for sql in TEXT_DISALLOWED]


@pytest.mark.parametrize("body", DISALLOWED)
def test_added_migration_with_unsafe_upgrade_escalates(body):
    result = classify_migration(migration(body))
    assert result == {"class": "escalation", "reasons": ESCALATED}


SAFE = 'op.create_index("ix_fictional", "fictional_widgets", ["label"])'


@pytest.mark.parametrize(
    "content",
    [
        "",
        "def upgrade(:\n    pass\n",
        "\x00",
        migration(SAFE).replace("def upgrade()", "def migrate()"),
        migration(SAFE) + "\n\ndef upgrade() -> None:\n    op.drop_table('fictional_widgets')\n",
        migration(SAFE) + DOWNGRADE,
        migration(SAFE).replace("def upgrade()", "async def upgrade()"),
        migration(SAFE).replace("def upgrade()", "@helper\ndef upgrade()"),
        migration(SAFE).replace("def upgrade()", "def upgrade(x=helper())"),
        migration(SAFE).replace("def upgrade() -> None", "def upgrade() -> helper()"),
        migration(SAFE, header=HEADER + "\nimport os\n"),
        migration(SAFE, header=HEADER + "\nfrom fictional.helpers import make_index\n"),
        migration(SAFE, header=HEADER + "\nfrom alembic import op as operations\n"),
        migration(SAFE, header=HEADER + "\nfrom . import helpers\n"),
        migration(SAFE, header=HEADER + "\nop = helper()\n"),
        migration(SAFE, header=HEADER + "\nrevision = helper()\n"),
        migration(SAFE, header=HEADER + "\nrevision: helper() = 'x'\n"),
        migration(SAFE, header=HEADER + "\nhelper()\n"),
        migration(SAFE, header=HEADER + "\nif True:\n    pass\n"),
        migration(SAFE, header=HEADER + "\nclass Fictional:\n    pass\n"),
        "(" * 1000 + ")" * 1000,
    ],
)
def test_parse_errors_missing_or_ambiguous_upgrade_and_module_code_escalate(content):
    assert classify_migration(content) == {"class": "escalation", "reasons": ESCALATED}


@pytest.mark.parametrize(
    "path,status,expected",
    [
        (MIGRATION, "modified", ESCALATED),
        (MIGRATION, "removed", ESCALATED),
        ("db/migrations/versions/fictional.sql", "added", ESCALATED),
        ("DB/MIGRATIONS/versions/fictional.py", "added", ESCALATED),
        ("db/model.py", "added", ["path:unknown-root"]),
        ("db/migrations/versions/0002_billing.py", "added", ["protected:name:billing"]),
        ("db/migrations/versions/0002_secret.py", "added", ["protected:secrets"]),
    ],
)
def test_merged_migration_edits_and_other_protected_rules_still_escalate(path, status, expected):
    record = {"filename": path, "status": status}
    contents = {} if status == "removed" else {path: migration(SAFE)}
    result = classify_changed_files([record], contents, changed_files=1)
    assert result == {"class": "escalation", "reasons": expected}


@pytest.mark.parametrize("direction", ["rename-in", "rename-out"])
def test_renamed_migrations_escalate(direction):
    old, new = ("apps/fictional.py", MIGRATION)
    if direction == "rename-out":
        old, new = new, old
    record = {"filename": new, "status": "renamed", "previous_filename": old}
    result = classify_changed_files([record], {new: migration(SAFE)}, changed_files=1)
    assert result == {"class": "escalation", "reasons": ESCALATED}


def test_added_migration_needs_string_contents():
    record = {"filename": MIGRATION, "status": "added"}
    result = classify_changed_files([record], {}, changed_files=1)
    assert result == {"class": "escalation", "reasons": ["evidence:contents", *ESCALATED]}


def test_migration_contents_are_never_executed(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("classifier attempted external IO or input execution")

    body = SAFE + "\n    import os\n    os.system('fictional')"
    hostile = migration(body, header=HEADER + "\nraise SystemExit('fictional')\n")
    with monkeypatch.context() as patch:
        for target, name in [
            (builtins, "open"),
            (builtins, "exec"),
            (builtins, "eval"),
            (os, "system"),
            (socket, "socket"),
            (builtins, "__import__"),
        ]:
            patch.setattr(target, name, forbidden)
        results = [classify_migration(content) for content in (hostile, migration(SAFE))]
    assert results == [
        {"class": "escalation", "reasons": ESCALATED},
        {"class": "routine", "reasons": []},
    ]
