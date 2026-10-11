from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.database import conversation_harness as harness

ROOT = Path(__file__).resolve().parents[3]
pytest_plugins = ["pytester"]


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("test_data.py", "import sqlalchemy\n", False),
        ("test_data.py", "from alembic.migration import MigrationContext\n", True),
        ("test_data.py", 'COMMAND = ["alembic", "upgrade", "head"]\n', True),
        ("test_data.py", "def broken(\n", True),
        ("test_backup_parity.py", "", True),
        ("test_migration.py", "", True),
        ("test_upgrade.py", "", True),
        ("test_restore.py", "", True),
    ],
)
def test_migration_and_backup_subjects_keep_original_rehearsal(
    tmp_path: Path, name: str, source: str, expected: bool
) -> None:
    module = tmp_path / name
    module.write_text(source)
    assert harness.migration_subject(module) is expected


def test_regular_session_clones_full_migration_seed_and_cleans_owned_databases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert os.environ.get("AC_TEST_DATABASE_URL"), "The disposable lane URL is required"
    module = tmp_path / "test_data.py"
    module.write_text("def test_data():\n    assert True\n")
    token = harness.CURRENT_MODULE.set(module)
    original = harness.migrated_database
    calls = []

    @contextmanager
    def counted(*args, **kwargs):
        calls.append(kwargs.get("drop_schema", True))
        with original(*args, **kwargs) as engine:
            yield engine

    monkeypatch.setattr(harness, "migrated_database", counted)
    names = []
    try:
        with harness.template_session(ROOT) as state:
            first = harness.conversation_harness(ROOT)
            engine = next(first)
            names.append(engine.url.database)
            try:
                with engine.begin() as connection:
                    identifier = connection.scalar(
                        text(
                            "SELECT id FROM tenants WHERE name = 'Disposable pre-Sales-Xray tenant'"
                        )
                    )
                    assert identifier is not None
                    connection.execute(
                        text("UPDATE tenants SET name = :name WHERE id = :id"),
                        {"id": identifier, "name": "first clone mutation"},
                    )
            finally:
                first.close()
            second = harness.conversation_harness(ROOT)
            engine = next(second)
            names.append(engine.url.database)
            try:
                with engine.connect() as connection:
                    assert (
                        connection.scalar(
                            text("SELECT name FROM tenants WHERE id = :id"), {"id": identifier}
                        )
                        == "Disposable pre-Sales-Xray tenant"
                    )
                    assert connection.scalar(text("SELECT version_num FROM alembic_version"))
            finally:
                second.close()
            assert calls == [False]
            assert len(set(names)) == 2
            pools = list(state.pools.values())
            assert len(pools) == 1 and len(pools[0].owned) == 1
        assert not pools[0].owned and pools[0].closed
    finally:
        harness.CURRENT_MODULE.reset(token)


def test_migration_routing_uses_original_initializer_each_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "test_migration.py"
    module.write_text("")
    calls = []

    @contextmanager
    def migration(*args, **kwargs):
        calls.append("alembic rehearsal")
        yield "original engine"

    monkeypatch.setattr(harness, "migrated_database", migration)
    token = harness.CURRENT_MODULE.set(module)
    try:
        with harness.template_session(ROOT) as state:
            for _ in range(2):
                generator = harness.conversation_harness(ROOT)
                assert next(generator) == "original engine"
                generator.close()
            assert state.pools == {}
        assert calls == ["alembic rehearsal", "alembic rehearsal"]
    finally:
        harness.CURRENT_MODULE.reset(token)


def test_regular_pytest_hooks_preserve_wrapper_api_and_migration_rehearsal(pytester) -> None:
    pytester.makeconftest(
        f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import pytest
from tests.database import conversation_harness as h

@pytest.fixture(scope='session', autouse=True)
def templates():
    with h.template_session(Path({str(ROOT)!r})) as state:
        yield
        assert len(state.pools) == 1
        assert calls == [False, True]

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    h.CURRENT_MODULE.set(Path(item.path))

from contextlib import contextmanager
calls = []
original = h.migrated_database
@contextmanager
def counted(*args, **kwargs):
    calls.append(kwargs.get('drop_schema', True))
    with original(*args, **kwargs) as engine:
        yield engine
h.migrated_database = counted
"""
    )
    pytester.makepyfile(
        shared=f"""
from pathlib import Path
import pytest
from tests.database import conversation_harness as h

@pytest.fixture(scope='module')
def postgres_harness():
    yield from h.conversation_harness(Path({str(ROOT)!r}))
""",
        test_data="""
import pytest
from sqlalchemy import text
from shared import postgres_harness as original

@pytest.fixture
def postgres_harness():
    yield from original.__wrapped__()

@pytest.mark.parametrize('value', ['one', 'two'])
def test_isolation(postgres_harness, value):
    with postgres_harness.begin() as connection:
        assert connection.scalar(
            text("SELECT name FROM tenants")
        ) == 'Disposable pre-Sales-Xray tenant'
        connection.execute(text("UPDATE tenants SET name = :name"), {'name': value})
""",
        test_migration="""
from shared import postgres_harness
from sqlalchemy import text

def test_prior_revision_preservation(postgres_harness):
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert connection.scalar(
            text("SELECT name FROM tenants")
        ) == 'Disposable pre-Sales-Xray tenant'
""",
    )
    result = pytester.runpytest_subprocess("-q", "--tb=short")
    result.assert_outcomes(passed=3)
