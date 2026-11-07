"""Dataset loading: new dialogs with their audio links, duplicates and broken records in `skipped`."""

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Dialog
from cqa.services.datasets import load_group, load_upload
from cqa.services.errors import Invalid, Upstream
from fakes import FakeSource, prototype_dialogs

DIALOGS = {d.id: d for d in prototype_dialogs()}


@pytest.fixture
def dialogs() -> list[Dialog]:
    """Only call-024 is already loaded."""
    return [DIALOGS["call-024"]]


def _source() -> FakeSource:
    return FakeSource(
        [DIALOGS["call-024"], DIALOGS["p1-ru-003"], DIALOGS["p1-ru-025"]],
        audio={"call-024": "https://org.test/player/1?token=x"},
        errors=["syn-1: нет транскрипта", "syn-2: нет транскрипта"],
    )


async def test_load_group_counts_duplicates_and_broken_records_as_skipped(store: Store) -> None:
    assert await load_group(store, _source(), "DEV") == {"added": 2, "skipped": 3}
    assert [d.id for d in store.list_dialogs()] == ["call-024", "p1-ru-003", "p1-ru-025"]


def test_load_upload_counts_duplicates_and_broken_records_as_skipped(store: Store) -> None:
    assert load_upload(store, _source(), b"{}") == {"added": 2, "skipped": 3}


async def test_audio_links_of_new_dialogs_go_to_the_store() -> None:
    store = Store(connect(":memory:"))
    await load_group(store, _source(), "DEV")
    assert store.audio_url("call-024") == "https://org.test/player/1?token=x"
    assert store.audio_url("p1-ru-003") is None


@pytest.mark.parametrize("exc", [Invalid("Недопустимый group_id"), Upstream("API организаторов не ответил")])
async def test_source_errors_of_fetch_pass_through_unchanged(store: Store, exc: Exception) -> None:
    with pytest.raises(type(exc), match=f"^{exc}$"):
        await load_group(store, FakeSource(raises={"fetch": exc}), "DEV")


def test_source_errors_of_upload_pass_through_unchanged(store: Store) -> None:
    exc = Invalid("В файле нет поля data.records")
    with pytest.raises(Invalid, match=f"^{exc}$"):
        load_upload(store, FakeSource(raises={"upload": exc}), b"{}")


async def test_blank_group_id_is_rejected(store: Store) -> None:
    with pytest.raises(Invalid, match="^Укажите group_id$"):
        await load_group(store, _source(), "  ")


def test_empty_upload_is_rejected(store: Store) -> None:
    with pytest.raises(Invalid, match="^Пустой файл$"):
        load_upload(store, _source(), b"")


async def test_load_group_uses_the_saved_org_link(store: Store) -> None:
    store.set_org_source("https://org.test/api?token=t", "DEV")
    source = _source()
    await load_group(store, source, "CTRL1")
    assert source.fetched == [("CTRL1", "https://org.test/api?token=t")]
