"""Own disposable test templates once per session; migration subjects stay cold."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.database.conversation_harness import CURRENT_MODULE, template_session  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def postgres_template_session() -> Iterator[None]:
    with template_session(ROOT):
        yield


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    CURRENT_MODULE.set(Path(item.path))
