"""Dataset loading: new dialogs with their audio links, duplicates and broken records in `skipped`."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Dialog, IngestResult
from cqa.services.datasets import load_group, load_upload
from cqa.services.errors import Invalid, Upstream

FIXTURES = Path(__file__).parents[1] / "fixtures"
DIALOGS = {
    d["id"]: Dialog.model_validate(d) for d in json.loads((FIXTURES / "dialogs_prototype.json").read_text())
}


class FakeSource:  # ponytail: own copy until tests/fakes.py lands in main
    def __init__(
        self,
        dialogs: Sequence[Dialog] = (),
        *,
        audio: Mapping[str, str] | None = None,
        errors: Sequence[str] = (),
        raises: Mapping[str, Exception] | None = None,
    ) -> None:
        self.result = IngestResult(list(dialogs), dict(audio or {}), len(errors), list(errors))
        self.raises = dict(raises or {})

    async def fetch(self, group_id: str) -> IngestResult:
        if "fetch" in self.raises:
            raise self.raises["fetch"]
        return self.result

    def upload(self, raw: bytes) -> IngestResult:
        if "upload" in self.raises:
            raise self.raises["upload"]
        return self.result

    async def audio_link(self, audio_url: str) -> str | None:
        return None


@pytest.fixture
def store() -> Store:
    store = Store(connect(":memory:"))
    store.add_dialogs([DIALOGS["call-024"]], {})
    return store


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
