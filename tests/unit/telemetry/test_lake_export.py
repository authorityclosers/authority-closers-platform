"""Fictional lake data only; no provider, database credential or customer record."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from sqlalchemy.dialects import postgresql

from ac_platform.telemetry import lake, lake_cli

DAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 29, 1, tzinfo=UTC)
KEY = b"fictional-test-only-key-32-bytes!!"
TENANT = UUID(int=1)
PERSON = UUID(int=2)


def analytics() -> dict:
    return {
        "tenant_id": TENANT,
        "actor_person_id": PERSON,
        "subject_person_id": PERSON,
        "session_id": "fictional-session",
        "event_id": "fictional-event",
        "event_name": "sx.api_timing",
        "event_version": "1.0",
        "route": "/leads",
        "occurred_at": NOW - timedelta(hours=2),
        "retention_expires_at": NOW + timedelta(days=180),
        "payload": {
            "screen": "leads",
            "band": "lt100",
            "status": "2xx",
            "background": "no",
            "endpoint": "fictional-person",
            "message": "Fictional Person +910000000000",
        },
        "trace_id": "not-exported",
        "consent_policy_version": "not-exported",
    }


def lead() -> dict:
    return {
        "tenant_id": TENANT,
        "actor_person_id": PERSON,
        "id": UUID(int=3),
        "lead_id": UUID(int=4),
        "kind": "note",
        "created_at": NOW - timedelta(hours=2),
        "data": {"text": "Fictional Person", "phone": "+910000000000"},
        "command_id": UUID(int=5),
    }


def test_hmac_is_stable_scoped_and_secret_dependent() -> None:
    value = lake.pseudonym(KEY, "dev", TENANT, "person", PERSON)
    assert value == lake.pseudonym(KEY, "dev", TENANT, "person", PERSON)
    assert (
        len(
            {
                value,
                lake.pseudonym(KEY, "production", TENANT, "person", PERSON),
                lake.pseudonym(KEY, "dev", UUID(int=9), "person", PERSON),
                lake.pseudonym(b"x" * 32, "dev", TENANT, "person", PERSON),
                lake.pseudonym(KEY, "dev", TENANT, "lead", PERSON),
            }
        )
        == 5
    )
    with pytest.raises(lake.ContractError):
        lake.pseudonym(b"short", "dev", TENANT, "person", PERSON)


@pytest.mark.parametrize(
    "table,source", [("analytics_events", analytics), ("lead_desk_events", lead)]
)
def test_real_parquet_allowlist_checksum_counts_and_deterministic_retry(
    tmp_path, table, source
) -> None:
    paths = []
    for run in ("first", "retry"):
        manifest_path = lake.write_table(
            table, [source()] * 5, key=KEY, env="dev", day=DAY, output=tmp_path / run, chunk_rows=2
        )
        manifest = json.loads(manifest_path.read_text())
        assert manifest["rows"] == 5
        assert [p["rows"] for p in manifest["parts"]] == [2, 2, 1]
        assert (
            manifest["contract_sha256"]
            == hashlib.sha256((lake.CONTRACTS / f"{table}.json").read_bytes()).hexdigest()
        )
        tables = []
        for part in manifest["parts"]:
            local = manifest_path.parent / Path(part["key"]).name
            assert local.stat().st_size == part["bytes"]
            assert hashlib.sha256(local.read_bytes()).hexdigest() == part["sha256"]
            assert part["key"].startswith(f"lake/dev/{table}/dt=2026-10-28/part-")
            table_data = pq.ParquetFile(local).read()
            tables.extend(table_data.to_pylist())
        assert len(tables) == 5
        assert set(tables[0]) == set(lake.contract(table)["columns"])
        serialized = str(tables)
        for private in (
            "Fictional",
            "+910000000000",
            "fictional-session",
            "fictional-event",
            str(PERSON),
        ):
            assert private not in serialized
        assert "data" not in tables[0] and "payload" not in tables[0]
        paths.append([p["key"] for p in manifest["parts"]])
    assert paths[0] == paths[1]


def test_empty_day_has_a_typed_empty_part(tmp_path) -> None:
    path = lake.write_table("analytics_events", [], key=KEY, env="dev", day=DAY, output=tmp_path)
    manifest = json.loads(path.read_text())
    assert manifest["rows"] == 0 and len(manifest["parts"]) == 1
    actual = pq.ParquetFile(path.parent / Path(manifest["parts"][0]["key"]).name)
    assert actual.metadata.num_rows == 0
    assert actual.schema_arrow.equals(lake.arrow_schema(lake.contract("analytics_events")))


@pytest.mark.parametrize(
    "field,value",
    [
        ("screen", "Fictional Person"),
        ("band", "fastish"),
        ("ms", -1),
        ("ms", True),
        ("ms", float("nan")),
    ],
)
def test_refuses_bad_types_and_unbounded_values_before_manifest(tmp_path, field, value) -> None:
    source = analytics()
    source["payload"][field] = value
    with pytest.raises(lake.ContractError):
        lake.write_table("analytics_events", [source], key=KEY, env="dev", day=DAY, output=tmp_path)
    assert not list(tmp_path.rglob("manifest.json"))


def test_refuses_unknown_columns_null_rates_naive_timestamps_and_bad_routes() -> None:
    spec = lake.contract("analytics_events")
    row = lake.project("analytics_events", analytics(), KEY, "dev")
    for change in (
        {"unknown": "personal"},
        {"subject_ref": None},
        {"occurred_at": datetime(2026, 10, 28)},
        {"route": "/leads/fictional-person"},
    ):
        with pytest.raises(lake.ContractError):
            lake.validate([{**row, **change}], spec)


def test_source_queries_have_half_open_utc_window_consent_retention_and_no_lead_content() -> None:
    query = lake.source_query("analytics_events", DAY, NOW)
    compiled = query.compile(dialect=postgresql.dialect())
    assert "occurred_at >=" in str(compiled) and "occurred_at <" in str(compiled)
    assert "consent_status =" in str(compiled) and "consent_purpose =" in str(compiled)
    assert "retention_expires_at >" in str(compiled)
    assert datetime(2026, 10, 28, tzinfo=UTC) in compiled.params.values()
    assert datetime(2026, 10, 29, tzinfo=UTC) in compiled.params.values()
    lead_query = str(lake.source_query("lead_desk_events", DAY, NOW))
    assert "lead_desk_events.data" not in lead_query
    assert "lead_desk_events.command_id" not in lead_query


def test_stream_respects_current_optout_and_sandbox(monkeypatch) -> None:
    connection = MagicMock()
    refused = {**analytics(), "tenant_id": UUID(int=7)}
    connection.execute.return_value.__enter__.return_value.mappings.return_value = [
        analytics(),
        refused,
    ]

    def standing(_connection, *, tenant_id, person_id):
        result = MagicMock()
        result.collecting = tenant_id != UUID(int=7)
        return result

    monkeypatch.setattr(lake, "read_standing", standing)
    assert list(lake.source_rows(connection, "analytics_events", DAY, NOW)) == [analytics()]


def test_cli_disabled_never_reads_secrets_or_database(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("AC_LAKE_EXPORT_ENABLED", raising=False)
    assert (
        lake_cli.main(
            [
                "--environment",
                "production",
                "--database-url-file",
                "/no/database",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disabled"]
    monkeypatch.setenv("AC_LAKE_EXPORT_ENABLED", "1")
    monkeypatch.setenv("AC_LAKE_HMAC_KEY_V1", "secret-invalid-key-never-print")
    assert (
        lake_cli.main(
            [
                "--environment",
                "dev",
                "--database-url-file",
                "/no/database",
                "--output",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "secret-invalid" not in capsys.readouterr().err


def test_stream_also_respects_subject_optout(monkeypatch) -> None:
    connection = MagicMock()
    source = {**analytics(), "subject_person_id": UUID(int=8)}
    connection.execute.return_value.__enter__.return_value.mappings.return_value = [source]

    def standing(_connection, *, tenant_id, person_id):
        result = MagicMock()
        result.collecting = person_id != UUID(int=8)
        return result

    monkeypatch.setattr(lake, "read_standing", standing)
    assert list(lake.source_rows(connection, "analytics_events", DAY, NOW)) == []


def test_cli_uses_read_only_snapshot_and_writes_both_validated_tables(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("AC_LAKE_EXPORT_ENABLED", "1")
    monkeypatch.setenv("AC_TELEMETRY_SPOOL_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("AC_LAKE_HMAC_KEY_V1", (b"x" * 32).hex())
    database_file = tmp_path / "database-url"
    database_file.write_text("postgresql+psycopg://fictional:fictional@localhost/fictional")
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.scalar.return_value = 0
    monkeypatch.setattr(lake_cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(lake_cli, "source_rows", lambda *a: iter([]))
    assert (
        lake_cli.main(
            [
                "--environment",
                "dev",
                "--database-url-file",
                str(database_file),
                "--output",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    commands = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    assert commands[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert "SET LOCAL TIME ZONE 'UTC'" in commands
    assert all(command.startswith("SET ") for command in commands)
    assert len(list((tmp_path / "output").rglob("manifest.json"))) == 2
    engine.dispose.assert_called_once()
    assert "fictional:" not in capsys.readouterr().out


def test_raw_postgres_lake_reconciliation_is_visible(tmp_path):
    import json
    from datetime import date

    from ac_platform.telemetry.lake import write_table

    manifest_path = write_table(
        "analytics_events",
        [],
        key=b"x" * 32,
        env="dev",
        day=date(2026, 10, 28),
        output=tmp_path,
        reconciliation={"postgres_rows": 0, "raw_rows": 7},
    )
    reconciliation = json.loads(manifest_path.read_text())["reconciliation"]
    assert reconciliation == {"postgres_rows": 0, "raw_rows": 7, "lake_rows": 0, "mismatch": True}
