"""Ссылка API организаторов из интерфейса и автосинхронизация набора: ссылка в базе, в статус не попадает."""

import asyncio

import pytest

from cqa.adapters.store import Store, connect
from cqa.services.errors import Invalid, Upstream
from cqa.services.sync import Syncer
from fakes import FakeSource, prototype_dialogs

DIALOGS = {d.id: d for d in prototype_dialogs()}
URL = "https://org.test/api/dialogs?group_id=DEV&token=t"


@pytest.fixture
def store() -> Store:
    return Store(connect(":memory:"))


def _source(raises: dict[str, Exception] | None = None) -> FakeSource:
    return FakeSource([DIALOGS["call-024"], DIALOGS["p1-ru-003"]], raises=raises)


async def test_configure_fetches_with_the_given_link_and_saves_it(store: Store) -> None:
    source = _source()
    assert await Syncer(store, source).configure(f" {URL} ", "DEV") == {"added": 2, "skipped": 0}
    assert source.fetched == [("DEV", URL)]
    assert store.org_source() == (URL, "DEV")


@pytest.mark.parametrize("bad", ["http://org.test/api", "org.test/api", "", "javascript:alert(1)"])
async def test_configure_rejects_a_link_without_https_and_makes_no_request(store: Store, bad: str) -> None:
    source = _source()
    with pytest.raises(Invalid, match="https://"):
        await Syncer(store, source).configure(bad, "DEV")
    assert source.fetched == []
    assert store.org_source() is None


async def test_failed_configure_keeps_the_previous_link(store: Store) -> None:
    store.set_org_source(URL, "DEV")
    source = _source(raises={"fetch": Upstream("API организаторов ответил статусом 403")})
    with pytest.raises(Upstream):
        await Syncer(store, source).configure("https://org.test/new", "CTRL1")
    assert store.org_source() == (URL, "DEV")


async def test_sync_without_a_saved_link_does_nothing(store: Store) -> None:
    source = _source()
    syncer = Syncer(store, source)
    await syncer.sync()
    assert source.fetched == []
    assert syncer.status() is None


async def test_sync_fetches_the_saved_group_and_adds_only_new_dialogs(store: Store) -> None:
    store.set_org_source(URL, "DEV")
    store.add_dialogs([DIALOGS["call-024"]], {})
    source = _source()
    syncer = Syncer(store, source)
    await syncer.sync()
    assert source.fetched == [("DEV", URL)]
    assert [d.id for d in store.list_dialogs()] == ["call-024", "p1-ru-003"]
    status = syncer.status()
    assert status is not None
    assert (status["group_id"], status["added"], status["skipped"], status["error"]) == ("DEV", 1, 1, None)
    assert status["synced_at"]


async def test_sync_error_goes_to_the_status_and_is_not_raised(store: Store) -> None:
    store.set_org_source(URL, "DEV")
    syncer = Syncer(store, _source(raises={"fetch": Upstream("набор DEV: API организаторов недоступен")}))
    await syncer.sync()
    status = syncer.status()
    assert status is not None
    assert status["error"] == "набор DEV: API организаторов недоступен"


async def test_status_never_contains_the_link(store: Store) -> None:
    syncer = Syncer(store, _source())
    await syncer.configure(URL, "DEV")
    assert "org.test" not in repr(syncer.status())


async def test_run_syncs_at_once_and_then_every_interval(store: Store) -> None:
    store.set_org_source(URL, "DEV")
    source = _source()
    task = asyncio.create_task(Syncer(store, source).run(interval_s=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    assert len(source.fetched) >= 2
