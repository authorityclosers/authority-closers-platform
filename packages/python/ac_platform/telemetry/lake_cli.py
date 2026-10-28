"""ac-lake-export's read-only database worker. Disabled unless explicitly enabled."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from ac_platform.telemetry.lake import ENVIRONMENTS, TABLES, source_rows, write_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=sorted(ENVIRONMENTS))
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.environ.get("AC_LAKE_EXPORT_ENABLED") != "1":
        print(json.dumps({"disabled": True, "environment": args.environment}))
        return 0
    try:
        # The key is injected by the root runner directly from Infisical, never argv/disk.
        key = bytes.fromhex(os.environ.pop("AC_LAKE_HMAC_KEY_V1", ""))
        if len(key) != 32:
            raise ValueError("invalid HMAC key")
        now = datetime.now(UTC)
        day = now.date() - timedelta(days=1)
        url = make_url(args.database_url_file.read_text().strip())
        if url.get_backend_name() != "postgresql":
            raise ValueError("PostgreSQL required")
        engine = create_engine(url.set(drivername="postgresql+psycopg"), hide_parameters=True)
        try:
            with engine.connect() as connection, connection.begin():
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '10min'")
                for table in TABLES:
                    write_table(
                        table,
                        source_rows(connection, table, day, now),
                        key=key,
                        env=args.environment,
                        day=day,
                        output=args.output,
                    )
        finally:
            engine.dispose()
        print(
            json.dumps(
                {"environment": args.environment, "day": day.isoformat(), "tables": list(TABLES)}
            )
        )
        return 0
    except Exception:
        # Driver and provider exceptions may contain credentials or raw source values.
        print('{"error":"lake export refused; no manifest published"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
