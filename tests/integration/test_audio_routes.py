"""Роутер записи: свежая ссылка и запасной плеер; адреса не утекают в ответы и журнал."""

import httpx
import pytest
import respx

from cqa.adapters.org_api import OrgApi
from cqa.http.app import create_app
from cqa.settings import Settings

TEMPLATE = "https://org.test/api/dialogs?group_id=DEV&token=t"
PLAYER_URL = "https://org.test/player/1"


class FakeStore:
    """Подделка Store: только метод, который читает роутер."""

    def __init__(self, urls: dict[str, str | None]) -> None:
        self._urls = urls

    def audio_url(self, dialog_id: str) -> str | None:
        return self._urls.get(dialog_id)


class FakeSource:
    """Подделка источника: готовая ссылка вместо запроса к плееру."""

    def __init__(self, link: str | None = None) -> None:
        self._link = link
        self.calls: list[str] = []

    async def audio_link(self, audio_url: str) -> str | None:
        self.calls.append(audio_url)
        return self._link


class ApiSource:
    """Подделка источника через настоящий `OrgApi.fresh_audio_link`; плеер подменяет respx."""

    def __init__(self, api: OrgApi) -> None:
        self._api = api

    async def audio_link(self, audio_url: str) -> str | None:
        return await self._api.fresh_audio_link(audio_url)


def app(store: FakeStore, source: object) -> httpx.AsyncClient:
    application = create_app(Settings(_env_file=None))
    application.state.store = store
    application.state.source = source
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def get(path: str, store: FakeStore, source: object) -> httpx.Response:
    async with app(store, source) as c, c.stream("GET", path) as response:
        body = await response.aread()
        return httpx.Response(response.status_code, content=body, headers=response.headers)


@respx.mock
async def test_audio_redirects_to_fresh_mp3_without_cache() -> None:
    player = respx.get(PLAYER_URL).mock(
        return_value=httpx.Response(
            200, text='<audio controls><source src="https://storage.test/rec.mp3?sv=1&amp;token=x"></audio>'
        )
    )
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://storage.test/rec.mp3?sv=1&token=x"
    assert response.headers["cache-control"] == "no-store"
    assert player.call_count == 1


@respx.mock
async def test_audio_relative_address_built_from_player_url() -> None:
    respx.get(PLAYER_URL).mock(return_value=httpx.Response(200, text='<source src="/media/rec.mp3">'))
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://org.test/media/rec.mp3"


@respx.mock
async def test_audio_asks_player_again_on_every_request() -> None:
    player = respx.get(PLAYER_URL).mock(
        return_value=httpx.Response(200, text='<source src="https://storage.test/rec.mp3">')
    )
    source = ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient()))
    await get("/api/dialogs/syn-call-hold/audio", FakeStore({"syn-call-hold": PLAYER_URL}), source)
    await get("/api/dialogs/syn-call-hold/audio", FakeStore({"syn-call-hold": PLAYER_URL}), source)

    assert player.call_count == 2


async def test_audio_when_source_returns_no_link_is_502() -> None:
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        FakeSource(None),
    )
    assert response.status_code == 502
    assert "detail" in response.json()
    assert PLAYER_URL not in response.json()["detail"]


@respx.mock
async def test_audio_player_without_source_is_502_without_address() -> None:
    respx.get(PLAYER_URL).mock(return_value=httpx.Response(200, text="<p>нет ссылки</p>"))
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 502
    assert "detail" in response.json()
    assert PLAYER_URL not in response.json()["detail"]


@respx.mock
async def test_audio_player_error_status_is_502() -> None:
    respx.get(PLAYER_URL).mock(return_value=httpx.Response(500, text="oops"))
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 502
    assert "detail" in response.json()
    assert PLAYER_URL not in response.json()["detail"]


@respx.mock
async def test_audio_player_timeout_is_502() -> None:
    respx.get(PLAYER_URL).mock(side_effect=httpx.ReadTimeout("timed out"))
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 502
    assert "detail" in response.json()


@respx.mock
async def test_audio_foreign_scheme_is_502() -> None:
    respx.get(PLAYER_URL).mock(return_value=httpx.Response(200, text='<source src="javascript:alert(1)">'))
    response = await get(
        "/api/dialogs/syn-call-hold/audio",
        FakeStore({"syn-call-hold": PLAYER_URL}),
        ApiSource(OrgApi(TEMPLATE, httpx.AsyncClient())),
    )

    assert response.status_code == 502
    assert "detail" in response.json()


@pytest.mark.parametrize("dialog_id", ["syn-chat-ru", "nope"])
async def test_audio_for_chat_and_unknown_id_is_404(dialog_id: str) -> None:
    response = await get(
        f"/api/dialogs/{dialog_id}/audio",
        FakeStore({"syn-chat-ru": None}),
        FakeSource("https://storage.test/rec.mp3"),
    )
    assert response.status_code == 404
    assert "detail" in response.json()


@respx.mock
async def test_player_redirects_to_audio_url_without_external_requests() -> None:
    outside = respx.route(host="org.test").mock(return_value=httpx.Response(200, text="nope"))
    audio_url = "https://org.test/player/syn-call-hold"
    response = await get(
        "/api/dialogs/syn-call-hold/player", FakeStore({"syn-call-hold": audio_url}), FakeSource()
    )

    assert response.status_code == 302
    assert response.headers["location"] == audio_url
    assert outside.call_count == 0


@pytest.mark.parametrize("dialog_id", ["syn-chat-ru", "nope"])
async def test_player_for_chat_and_unknown_id_is_404(dialog_id: str) -> None:
    response = await get(f"/api/dialogs/{dialog_id}/player", FakeStore({"syn-chat-ru": None}), FakeSource())
    assert response.status_code == 404
    assert "detail" in response.json()


def test_audio_routes_are_connected_in_create_app() -> None:
    paths = set(create_app(Settings(_env_file=None)).openapi()["paths"])
    assert "/api/dialogs/{id}/audio" in paths
    assert "/api/dialogs/{id}/player" in paths
