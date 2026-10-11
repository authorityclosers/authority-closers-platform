"""Session-owned PostgreSQL templates for explicitly disposable loopback tests.

Prepared for integration after the separate red-main repair PR merges.
No URL, credentials or database contents belong in diagnostics.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

IDENTIFIER = re.compile(r"ac_pytest_[a-z0-9_]{1,52}\Z")


class TemplateError(RuntimeError):
    """A bounded, credential-free test infrastructure diagnostic."""


def disposable_url(raw: str) -> URL:
    try:
        url = make_url(raw)
    except Exception:
        raise TemplateError("Invalid disposable PostgreSQL URL") from None
    if url.get_backend_name() != "postgresql" or url.host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise TemplateError("Templates require explicitly configured loopback PostgreSQL")
    if any(key.lower() in {"host", "hostaddr", "service", "servicefile"} for key in url.query):
        raise TemplateError("Alternate PostgreSQL host/service routing is forbidden")
    if not url.database:
        raise TemplateError("A disposable database identity is required")
    return url.set(drivername="postgresql+psycopg")


def migration_fingerprint(root: Path) -> str:
    """Invalidate even an edited migration with an unchanged revision ID."""
    paths = [root / "alembic.ini", *sorted((root / "db/migrations").rglob("*.py"))]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def quoted_database(name: str) -> str:
    if not IDENTIFIER.fullmatch(name):
        raise TemplateError("Only session-owned test database identities are allowed")
    return f'"{name}"'


class PostgresTemplatePool:
    """Migrate once; clone and drop only databases created by this instance."""

    def __init__(self, raw: str, initialize: Callable[[URL, str], None]) -> None:
        self.url = disposable_url(raw)
        self.initialize = initialize
        self.session = uuid4().hex
        self.schema = f"conversation_proof_{self.session}"
        self.templates: dict[str, str] = {}
        self.owned: set[str] = set()
        self.closed = False
        # The maintenance database is the lane URL supplied by the launcher,
        # not an implicit default or a production/staging environment variable.
        self.admin = create_engine(
            self.url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )

    def _create(self, name: str, template: str | None = None) -> None:
        source = quoted_database(template) if template else '"template0"'
        try:
            with self.admin.connect() as connection:
                connection.exec_driver_sql("SET lock_timeout = '10s'")
                connection.exec_driver_sql("SET statement_timeout = '30s'")
                connection.exec_driver_sql(
                    f"CREATE DATABASE {quoted_database(name)} TEMPLATE {source}"
                )
                self.owned.add(name)
        except Exception as error:
            raise TemplateError(f"Test database creation failed ({type(error).__name__})") from None

    def _drop(self, name: str) -> None:
        if name not in self.owned:
            raise TemplateError("Refusing cleanup of an unowned database")
        try:
            with self.admin.connect() as connection:
                connection.exec_driver_sql("SET lock_timeout = '10s'")
                connection.exec_driver_sql("SET statement_timeout = '30s'")
                connection.exec_driver_sql(f"DROP DATABASE {quoted_database(name)} WITH (FORCE)")
            self.owned.remove(name)
        except Exception as error:
            raise TemplateError(f"Test database cleanup failed ({type(error).__name__})") from None

    def template(self, fingerprint: str) -> str:
        if self.closed:
            raise TemplateError("The test template session is closed")
        if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise TemplateError("A migration content fingerprint is required")
        if fingerprint not in self.templates:
            name = f"ac_pytest_tpl_{self.session}_{fingerprint[:8]}"
            self._create(name)
            try:
                # The initializer must dispose its engines before returning,
                # so PostgreSQL can copy the template without active sessions.
                self.initialize(self.url.set(database=name), self.schema)
            except BaseException:
                self._drop(name)
                raise
            self.templates[fingerprint] = name
        return self.templates[fingerprint]

    @contextmanager
    def clone(self, fingerprint: str) -> Iterator[Engine]:
        template = self.template(fingerprint)
        name = f"ac_pytest_clone_{uuid4().hex}"
        self._create(name, template)
        options = f"-csearch_path={self.schema} -clock_timeout=10000 -cstatement_timeout=30000"
        url = self.url.set(database=name, query={**self.url.query, "options": options})
        engine: Engine | None = None
        try:
            engine = create_engine(url, hide_parameters=True)
            yield engine
        finally:
            if engine is not None:
                engine.dispose()
            self._drop(name)

    def close(self) -> None:
        if self.closed:
            return
        failures = 0
        # Context managers normally remove clones first. Session cleanup also
        # reclaims an interrupted test's owned clone, never any other database.
        names = sorted(self.owned, key=lambda name: (name.startswith("ac_pytest_tpl_"), name))
        for name in names:
            try:
                self._drop(name)
            except TemplateError:
                failures += 1
        self.admin.dispose()
        if failures:
            raise TemplateError(f"Test template cleanup left {failures} owned databases")
        self.closed = True
