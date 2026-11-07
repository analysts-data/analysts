"""Shared fixtures; also puts tests/ on sys.path so tests can `import fakes`."""

import os
import sqlite3
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store, connect
from cqa.domain.models import Dialog
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource, prototype_checklist, prototype_dialogs

AUDIO = {"call-024": "https://storage.test/call-024.mp3"}
AUDIT_TEST = "test_every_cassette_is_replayed"


def pytest_configure(config: pytest.Config) -> None:
    """make e2e (CQA_CASSETTE_AUDIT=1): каждая воспроизведённая запись пишется в общий журнал."""
    if os.environ.get("CQA_CASSETTE_AUDIT") == "1" and "CQA_CASSETTE_LOG" not in os.environ:
        os.environ["CQA_CASSETTE_LOG"] = tempfile.mkstemp(prefix="cqa-cassettes-", suffix=".log")[1]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    items.sort(key=lambda item: item.name == AUDIT_TEST)  # сверка журнала — после всех прогонов


@pytest.fixture
def dialogs() -> list[Dialog]:
    """call-024 and p1-ru-003 from the prototype, with their `res`."""
    return [d for d in prototype_dialogs() if d.id in ("call-024", "p1-ru-003")]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    conn = connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def store(conn: sqlite3.Connection, dialogs: list[Dialog]) -> Store:
    store = Store(conn)
    store.add_checklist(prototype_checklist(), "начальная версия")
    store.add_dialogs(dialogs, AUDIO)
    return store


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, db_path=":memory:")


@pytest.fixture
def evaluator() -> FakeEvaluator:
    return FakeEvaluator()


@pytest.fixture
def client(
    settings: Settings,
    store: Store,
    conn: sqlite3.Connection,
    dialogs: list[Dialog],
    evaluator: FakeEvaluator,
) -> TestClient:
    return TestClient(create_app(settings, source=FakeSource(dialogs), evaluator=evaluator, conn=conn))
