from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text

from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401


def test_0061_migration_adds_nullable_failure_detail_on_postgresql(postgres_harness: Any) -> None:  # noqa: F811
    with postgres_harness.engine.connect() as connection:
        # 0061 is applied under the current head (billing 0062-0064, plans 0065 and 0066 follow it).
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "20261002_0066"
        )
        column = next(
            item
            for item in inspect(connection).get_columns("jobs")
            if item["name"] == "failure_detail"
        )
        assert column["nullable"] is True
        assert type(column["type"]).__name__ == "JSON"
        assert (
            connection.execute(
                text("SELECT count(*) FROM jobs WHERE failure_detail IS NOT NULL")
            ).scalar_one()
            == 0
        )
