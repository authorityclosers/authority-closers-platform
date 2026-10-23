"""The Pulse organisation move carries exactly the organisation's rows, renumbers only what the
target numbers itself, keeps a dry run a dry run, and refuses to apply without the owner's words
or to skip production's snapshot."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "pulse_org_move", ROOT / "scripts/data-changes/pulse-org-move.py"
)
assert spec is not None and spec.loader is not None
move = importlib.util.module_from_spec(spec)
sys.modules["pulse_org_move"] = move
spec.loader.exec_module(move)

ORG = "350ce338-d796-4de2-b17b-07cbc337f27a"


def col(name: str, *, fresh: bool = False, generated: bool = False) -> dict:
    return {"name": name, "type": "text", "fresh": fresh, "generated": generated}


def table(
    name: str,
    rows: int,
    columns: list[dict],
    *,
    forced: bool = True,
    referenced: list[str] | None = None,
) -> dict:
    return {
        "t": name,
        "rows": rows,
        "forced": forced,
        "columns": columns,
        "referenced": referenced or [],
    }


INFO = {
    "tables": [
        table(
            "pulse.task", 3, [col("id"), col("org_id"), col("title"), col("search", generated=True)]
        ),
        table("pulse.event", 2, [col("seq", fresh=True), col("tx_id"), col("org_id"), col("id")]),
        table(
            "pulse.projection_cursor",
            1,
            [col("org_id"), col("name"), col("last_tx"), col("last_seq"), col("status")],
        ),
        table("pulse.login_credential", 5, [col("org_id"), col("person_id"), col("password_hash")]),
        table("pulse.login_session", 7, [col("org_id"), col("token_hash")]),
        table("pulse_priv.pulse_licence", 1, [col("id"), col("org_id")], forced=False),
        table("pulse.empty", 0, [col("org_id")], forced=False),
    ]
}


def test_moves_organisation_tables_and_leaves_sign_in_state_and_the_register() -> None:
    moving, staying = move.plan_tables(INFO, carry_passwords=False)
    assert [e["table"] for e in moving] == ["pulse.task", "pulse.event", "pulse.projection_cursor"]
    assert {s["table"] for s in staying} == {
        "pulse.login_credential",
        "pulse.login_session",
        "pulse_priv.pulse_licence",
    }
    task = moving[0]
    assert task["columns"] == ["id", "org_id", "title"]  # a generated column is never copied
    event = moving[1]
    assert event["fresh"] == ["seq", "tx_id"] and event["columns"] == ["org_id", "id"]


def test_passwords_move_only_when_asked() -> None:
    moving, staying = move.plan_tables(INFO, carry_passwords=True)
    assert "pulse.login_credential" in [e["table"] for e in moving]
    assert "pulse.login_session" in [s["table"] for s in staying]  # sessions never move


def test_refuses_unforced_tables_and_renumbered_keys_that_something_points_at() -> None:
    unforced = {"tables": [table("pulse.odd", 1, [col("org_id")], forced=False)]}
    with pytest.raises(SystemExit, match="forced row-level security"):
        move.plan_tables(unforced, carry_passwords=False)
    pointed = {
        "tables": [
            table(
                "pulse.chat_event", 1, [col("seq", fresh=True), col("org_id")], referenced=["seq"]
            )
        ]
    }
    with pytest.raises(SystemExit, match="renumbers"):
        move.plan_tables(pointed, carry_passwords=False)


def test_rows_are_read_in_order_and_cursors_restart() -> None:
    moving, _ = move.plan_tables(INFO, carry_passwords=False)
    event_sql = move.select_for(moving[1], ORG)
    assert (
        event_sql.endswith(f"where org_id = '{ORG}' order by \"seq\"")
        and '"tx_id"' not in event_sql
    )
    cursor_sql = move.select_for(moving[2], ORG)
    assert (
        "'0'::xid8 as \"last_tx\"" in cursor_sql
        and '0 as "last_seq"' in cursor_sql
        and "'building' as \"status\"" in cursor_sql
    )


def manifest(tables: list[dict]) -> dict:
    return {
        "org": {
            "id": ORG,
            "name": "Authority Closers",
            "code": "AC",
            "slug": "authority-closers",
            "handle": "authorityclosers",
        },
        "migrations": ["0949", "0950"],
        "rows": sum(t["rows"] for t in tables),
        "tables": tables,
        "staying": [],
        "carry_passwords": False,
        "bundle_sha256": "x",
        "source": {"exec": "docker exec -i pulse-postgres-1", "database": "pulse"},
    }


def test_one_transaction_triggers_paused_for_the_rows_then_checked_before_commit() -> None:
    moving, _ = move.plan_tables(INFO, carry_passwords=False)
    m = manifest(moving)
    args = {
        "actor": "Data change x",
        "host": "pulse.authorityclosers.com",
        "link": ("suyash", ORG),
        "licence_central": True,
        "licence_note": "moved",
    }
    dry = move.import_script(m, "BUNDLE\n", {"licence": {"id": "l"}}, apply=False, **args)
    real = move.import_script(m, "BUNDLE\n", {"licence": {"id": "l"}}, apply=True, **args)
    assert dry.rstrip().endswith("rollback;") and "\ncommit;" not in dry
    assert real.rstrip().endswith("commit;") and "\nrollback;" not in real
    order = [
        dry.index(s)
        for s in (
            "begin;",
            "session_replication_role = replica",
            "BUNDLE",
            "$counts$",
            "session_replication_role = origin",
            "insert into pulse.org_domain",
            "$verify$",
        )
    ]
    assert order == sorted(order)
    assert dry.count("begin;") == 1
    assert "update pulse_priv.pulse_licence set hosting = 'central'" in dry
    assert "where a.handle = 'suyash'" in dry
    plain = move.import_script(
        m,
        "BUNDLE\n",
        {"licence": {"id": "l"}},
        apply=False,
        actor="a",
        host="",
        link=None,
        licence_central=False,
        licence_note="",
    )
    assert (
        "org_domain(" not in plain
        and "account_member(" not in plain
        and "update pulse_priv.pulse_licence" not in plain
    )


def test_actor_text_is_quoted() -> None:
    assert move.lit("it's") == "'it''s'"


class FakePg:
    def __init__(self, target: dict) -> None:
        self.target = target

    def one_json(self, sql: str) -> dict:
        return self.target


def test_target_checks_name_every_clash() -> None:
    moving, _ = move.plan_tables(INFO, carry_passwords=False)
    m = manifest(moving)
    target = {
        "migrations": ["0949"],
        "org_taken": [{"id": ORG}],
        "handle_taken": True,
        "host_taken": "6f1a",
        "account": None,
        "licence": None,
        "orgs": [],
        "columns": {"pulse.task": ["id", "org_id"]},
    }
    _, problems = move.check_target(FakePg(target), m, "pulse.authorityclosers.com", "suyash")
    text = " ".join(problems)
    for phrase in (
        "migrations differ",
        "already has an organisation",
        "handle",
        "already claimed",
        "no Pulse account",
        "columns differ",
        "does not exist in the target",
    ):
        assert phrase in text, phrase


def bundle_dir(tmp_path: Path) -> Path:
    body = b"COPY x FROM stdin;\n\\.\n"
    m = manifest([])
    m["bundle_sha256"] = hashlib.sha256(body).hexdigest()
    (tmp_path / "bundle.sql").write_bytes(body)
    (tmp_path / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return tmp_path


def test_apply_needs_the_owners_words(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--approver"):
        move.main(["import", "--bundle", str(bundle_dir(tmp_path)), "--apply"])


def test_a_changed_bundle_is_refused(tmp_path: Path) -> None:
    d = bundle_dir(tmp_path)
    (d / "bundle.sql").write_bytes(b"something else")
    with pytest.raises(SystemExit, match="sha256"):
        move.main(["import", "--bundle", str(d)])


def test_production_always_gets_a_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clean = {
        "migrations": ["0949", "0950"],
        "org_taken": None,
        "handle_taken": False,
        "host_taken": None,
        "account": None,
        "licence": None,
        "orgs": [],
        "columns": {},
    }
    monkeypatch.setattr(move, "check_target", lambda *a, **k: (clean, []))
    with pytest.raises(SystemExit, match="scratch copies only"):
        move.main(
            [
                "import",
                "--bundle",
                str(bundle_dir(tmp_path)),
                "--apply",
                "--no-snapshot",
                "--database",
                "pulse",
                "--approver",
                "a",
                "--words",
                "w",
                "--issue",
                "i",
            ]
        )
