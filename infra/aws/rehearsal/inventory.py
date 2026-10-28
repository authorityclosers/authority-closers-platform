#!/usr/bin/env python3
"""Only fictional upload IDs, lengths and checksum verdicts; secrets remain local."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.pulse.models import AppCallUpload


async def main():
    root = Path("/fixture")
    if not (root / "FICTIONAL-ONLY").is_file():
        raise SystemExit("Fictional marker required")
    if "@pgbouncer:6432/ac_platform" not in os.environ["AC_DATABASE_URL"]:
        raise SystemExit("Isolated pooler required")
    engine = create_async_engine(os.environ["AC_DATABASE_URL"], hide_parameters=True)
    async with AsyncSession(engine) as db:
        rows = list(await db.scalars(select(AppCallUpload).order_by(AppCallUpload.id)))
        result = []
        for row in rows:
            path = (
                Path(os.environ["AC_SALES_XRAY_STORAGE_ROOT"])
                / "app-inbox"
                / str(row.tenant_id)
                / f"{row.id}.bin"
            )
            exists = path.is_file()
            result.append(
                {
                    "id": str(row.id),
                    "external_id": row.external_id,
                    "bytes": row.byte_size,
                    "state": row.state,
                    "exists": exists,
                    "checksum_ok": exists
                    and hashlib.sha256(path.read_bytes()).hexdigest() == row.source_sha256,
                }
            )
    await engine.dispose()
    print(
        json.dumps(
            {
                "count": len(rows),
                "all_files_match": all(row["checksum_ok"] for row in result),
                "uploads": result,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
