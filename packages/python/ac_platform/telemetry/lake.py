"""Read-only, content-free UTC daily lake export. Manifests are the commit markers.

No source rows are changed. Pseudonyms are domain separated by environment, tenant
and entity kind. Contracts are checked before encoding and again on the Parquet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.engine import Connection

from ac_platform.lead_desk.models import LeadEvent
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.ingest import TELEMETRY_PURPOSE
from ac_platform.telemetry.sales_xray_consent import read_standing

ENVIRONMENTS = frozenset({"dev", "staging", "production"})
TABLES = ("analytics_events", "lead_desk_events")
CONTRACTS = Path(__file__).with_name("lake_contracts")
CHUNK_ROWS = 10_000
TYPES = {
    "string": pa.string(),
    "int64": pa.int64(),
    "float64": pa.float64(),
    "timestamp": pa.timestamp("us", tz="UTC"),
}


class ContractError(ValueError):
    """Fixed error text only; never put source values in diagnostics."""


def contract(table: str) -> dict[str, Any]:
    if table not in TABLES:
        raise ContractError("unknown lake table")
    result: dict[str, Any] = json.loads((CONTRACTS / f"{table}.json").read_text())
    return result


def arrow_schema(spec: Mapping[str, Any]) -> Any:
    return pa.schema(
        [
            pa.field(name, TYPES[column["type"]], nullable=column["max_null_rate"] > 0)
            for name, column in spec["columns"].items()
        ],
        metadata={b"lake_contract": spec["version"].encode()},
    )


def validate(rows: list[dict[str, Any]], spec: Mapping[str, Any]) -> None:
    columns = spec["columns"]
    nulls = dict.fromkeys(columns, 0)
    for row in rows:
        if set(row) != set(columns):
            raise ContractError("lake column allowlist mismatch")
        for name, rule in columns.items():
            value = row[name]
            if value is None:
                nulls[name] += 1
                continue
            kind = rule["type"]
            valid = (
                isinstance(value, str)
                if kind == "string"
                else isinstance(value, int) and not isinstance(value, bool)
                if kind == "int64"
                else isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value)
                if kind == "float64"
                else isinstance(value, datetime)
                and value.tzinfo is not None
                and value.utcoffset() == timedelta(0)
            )
            if not valid:
                raise ContractError("lake column type mismatch")
            if "enum" in rule and value not in rule["enum"]:
                raise ContractError("lake value outside enum")
            if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
                raise ContractError("lake value outside pattern")
            if "min" in rule and value < rule["min"] or "max" in rule and value > rule["max"]:
                raise ContractError("lake numeric value outside range")
    for name, count in nulls.items():
        if rows and count / len(rows) > columns[name]["max_null_rate"]:
            raise ContractError("lake null rate exceeds contract")


def pseudonym(key: bytes, env: str, tenant: Any, kind: str, value: Any) -> str | None:
    if len(key) < 32 or env not in ENVIRONMENTS:
        raise ContractError("lake HMAC configuration invalid")
    if value is None:
        return None
    message = json.dumps(
        ["ac-lake/1", env, str(tenant), kind, str(value)], separators=(",", ":")
    ).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def project(
    table: str,
    source: Mapping[str, Any],
    key: bytes,
    env: str,
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Allowlist projection: raw payload/data, labels, tokens and free text never cross."""
    spec = spec if spec is not None else contract(table)
    row = dict.fromkeys(spec["columns"])
    tenant = source["tenant_id"]
    row["tenant_ref"] = pseudonym(key, env, tenant, "tenant", tenant)
    row["actor_ref"] = pseudonym(key, env, tenant, "person", source["actor_person_id"])
    if table == "analytics_events":
        for dest, field, kind in (
            ("event_ref", "event_id", "analytics_event"),
            ("subject_ref", "subject_person_id", "person"),
            ("session_ref", "session_id", "session"),
        ):
            row[dest] = pseudonym(key, env, tenant, kind, source[field])
        for name in ("event_name", "event_version", "occurred_at", "route", "retention_expires_at"):
            row[name] = source[name]
        payload = source["payload"]
        if not isinstance(payload, dict):
            raise ContractError("lake payload shape invalid")
        for name in spec["payload_columns"]:
            # Each field has fixed enums or numeric bounds in the contract. No
            # generic label/token strings, URLs, messages or content survive.
            row[name] = payload.get(name)
    else:
        row["event_ref"] = pseudonym(key, env, tenant, "lead_event", source["id"])
        row["lead_ref"] = pseudonym(key, env, tenant, "lead", source["lead_id"])
        row["kind"] = source["kind"]
        row["occurred_at"] = source["created_at"]
    return row


def source_query(table: str, day: date, now: datetime) -> Any:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    if table == "analytics_events":
        model = AnalyticsEvent
        return (
            select(
                *(
                    getattr(model, field)
                    for field in (
                        "event_id",
                        "tenant_id",
                        "actor_person_id",
                        "subject_person_id",
                        "session_id",
                        "event_name",
                        "event_version",
                        "occurred_at",
                        "route",
                        "payload",
                        "retention_expires_at",
                    )
                )
            )
            .where(
                model.occurred_at >= start,
                model.occurred_at < end,
                model.consent_status == "granted",
                model.consent_purpose == TELEMETRY_PURPOSE,
                model.retention_expires_at > now,
            )
            .order_by(model.occurred_at, model.tenant_id, model.event_id)
        )
    if table != "lead_desk_events":
        raise ContractError("unknown lake table")
    return (
        select(
            *(
                getattr(LeadEvent, field)
                for field in (
                    "id",
                    "tenant_id",
                    "actor_person_id",
                    "lead_id",
                    "kind",
                    "created_at",
                )
            )
        )
        .where(LeadEvent.created_at >= start, LeadEvent.created_at < end)
        .order_by(
            LeadEvent.created_at,
            LeadEvent.tenant_id,
            LeadEvent.id,
        )
    )


def source_rows(connection: Connection, table: str, day: date, now: datetime) -> Iterator[Any]:
    """Stream selected metadata; check current workspace/person privacy switches too."""
    # Cache a bounded set of consent decisions within the read-only snapshot.
    standing: dict[tuple[Any, Any], bool] = {}
    with connection.execute(
        source_query(table, day, now).execution_options(
            yield_per=CHUNK_ROWS,
        )
    ) as cursor:
        for row in cursor.mappings():
            people = {row["actor_person_id"]}
            if table == "analytics_events":
                people.add(row["subject_person_id"])
            permitted = True
            for person in people:
                pair = (row["tenant_id"], person)
                if pair not in standing:
                    if len(standing) >= CHUNK_ROWS:
                        standing.clear()
                    # System Lead Desk events still observe workspace/sandbox
                    # policy. Zero UUID has no person preference.
                    standing[pair] = read_standing(
                        connection,
                        tenant_id=pair[0],
                        person_id=person or UUID(int=0),
                    ).collecting
                if not standing[pair]:
                    permitted = False
                    break
            if permitted:
                yield row


def write_table(
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    key: bytes,
    env: str,
    day: date,
    output: Path,
    chunk_rows: int = CHUNK_ROWS,
    reconciliation: dict[str, Any] | None = None,
) -> Path:
    if env not in ENVIRONMENTS or chunk_rows < 1 or len(key) < 32:
        raise ContractError("invalid lake export configuration")
    spec = contract(table)
    schema = arrow_schema(spec)
    folder = output / table
    folder.mkdir(parents=True, exist_ok=False)
    parts: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    prefix = f"lake/{env}/{table}/dt={day.isoformat()}"

    def write() -> None:
        validate(batch, spec)
        path = folder / "writing.parquet"
        pq.write_table(pa.Table.from_pylist(batch, schema=schema), path, compression="zstd")
        actual = pq.ParquetFile(path)
        if not actual.schema_arrow.equals(
            schema, check_metadata=True
        ) or actual.metadata.num_rows != len(batch):
            raise ContractError("lake Parquet verification failed")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        name = f"part-{len(parts):05d}-{digest}.parquet"
        final = path.with_name(name)
        path.rename(final)
        parts.append(
            {
                "key": f"{prefix}/{name}",
                "rows": len(batch),
                "sha256": digest,
                "bytes": final.stat().st_size,
            }
        )

    for source in rows:
        batch.append(project(table, source, key, env, spec))
        if len(batch) == chunk_rows:
            write()
            batch.clear()
    if batch or not parts:
        write()
    manifest = {
        "schema": "ac-lake-manifest/1",
        "contract": spec["version"],
        "contract_sha256": hashlib.sha256((CONTRACTS / f"{table}.json").read_bytes()).hexdigest(),
        "environment": env,
        "table": table,
        "day": day.isoformat(),
        "timezone": "UTC",
        "rows": sum(part["rows"] for part in parts),
        "parts": parts,
        "hmac_key_id": "AC_LAKE_HMAC_KEY_V1",
        "pseudonym_version": "ac-lake/1",
    }
    if table == "analytics_events" and reconciliation is not None:
        lake_rows = manifest["rows"]
        manifest["reconciliation"] = {
            **reconciliation,
            "lake_rows": lake_rows,
            "mismatch": not (
                reconciliation.get("postgres_rows") == reconciliation.get("raw_rows") == lake_rows
            ),
        }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return path
