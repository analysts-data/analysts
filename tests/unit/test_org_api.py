"""Клиент API организаторов: подстановка group_id и один GET без утечки адреса."""

import httpx
import pytest
import respx

from cqa.adapters.org_api import (
    AUDIO_TIMEOUT_S,
    FETCH_TIMEOUT_S,
    OrgApi,
    OrgApiError,
    extract_audio_src,
    group_url,
)

TEMPLATE = "https://org.test/api/dialogs?group_id=DEV&token=t"


def test_group_url_replaces_value_and_keeps_other_params() -> None:
    assert group_url(TEMPLATE, "CTRL1") == "https://org.test/api/dialogs?group_id=CTRL1&token=t"


def test_group_url_appends_missing_param() -> None:
    assert group_url("https://org.test/api/dialogs?token=t", "DEV") == (
        "https://org.test/api/dialogs?token=t&group_id=DEV"
    )


def test_group_url_accepts_boundary_group_ids() -> None:
    assert group_url("https://org.test/api", "a" * 64).endswith("group_id=" + "a" * 64)
    assert group_url("https://org.test/api", "A-b_0") == "https://org.test/api?group_id=A-b_0"


@pytest.mark.parametrize("bad", ["../etc", "", " ", "a" * 65, "группа", "DEV 1", "a/b"])
def test_group_url_rejects_bad_group_id(bad: str) -> None:
    with pytest.raises(ValueError, match="group_id"):
        group_url(TEMPLATE, bad)


def test_fetch_timeout_is_thirty_seconds() -> None:
    assert FETCH_TIMEOUT_S == 30.0


@respx.mock
async def test_fetch_group_makes_single_get_and_returns_bytes() -> None:
    route = respx.get("https://org.test/api/dialogs").mock(return_value=httpx.Response(200, content=b"body"))
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        body = await api.fetch_group("CTRL1")

    assert body == b"body"
    assert route.call_count == 1
    request = route.calls.last.request
    assert str(request.url) == "https://org.test/api/dialogs?group_id=CTRL1&token=t"
    assert request.extensions["timeout"]["read"] == FETCH_TIMEOUT_S


@pytest.mark.parametrize("status", [404, 500])
@respx.mock
async def test_fetch_group_error_status_raises_org_api_error(status: int) -> None:
    route = respx.get("https://org.test/api/dialogs").mock(return_value=httpx.Response(status, text="oops"))
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        with pytest.raises(OrgApiError) as excinfo:
            await api.fetch_group("CTRL1")

    assert "org.test" not in str(excinfo.value)
    assert "token=" not in str(excinfo.value)
    assert route.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused by org.test"), httpx.ReadTimeout("org.test timed out")],
)
@respx.mock
async def test_fetch_group_network_failure_raises_org_api_error(failure: Exception) -> None:
    respx.get("https://org.test/api/dialogs").mock(side_effect=failure)
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        with pytest.raises(OrgApiError) as excinfo:
            await api.fetch_group("CTRL1")

    assert "org.test" not in str(excinfo.value)
    assert "token=" not in str(excinfo.value)


def test_extract_audio_src_from_source_tag_unescapes_entities() -> None:
    html = '<audio controls><source src="https://storage.test/rec.mp3?sv=1&amp;token=x" type="audio/mpeg">'
    assert extract_audio_src(html, "https://org.test/player/1") == "https://storage.test/rec.mp3?sv=1&token=x"


def test_extract_audio_src_from_audio_tag() -> None:
    html = '<html><body><audio src="https://storage.test/rec.mp3"></audio></body></html>'
    assert extract_audio_src(html, "https://org.test/player/1") == "https://storage.test/rec.mp3"


def test_extract_audio_src_builds_relative_address_from_base() -> None:
    html = '<source src="/media/rec.mp3">'
    assert extract_audio_src(html, "https://org.test/player/1") == "https://org.test/media/rec.mp3"


def test_extract_audio_src_rejects_foreign_scheme() -> None:
    assert extract_audio_src('<source src="javascript:alert(1)">', "https://org.test/player/1") is None


def test_extract_audio_src_without_tags_returns_none() -> None:
    assert extract_audio_src("<p>плеер недоступен</p>", "https://org.test/player/1") is None


def test_fresh_audio_link_timeout_is_ten_seconds() -> None:
    assert AUDIO_TIMEOUT_S == 10.0


@respx.mock
async def test_fresh_audio_link_returns_first_source_address() -> None:
    player = respx.get("https://org.test/player/1").mock(
        return_value=httpx.Response(
            200, text='<audio controls><source src="https://storage.test/rec.mp3?sv=1&amp;token=x"></audio>'
        )
    )
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        link = await api.fresh_audio_link("https://org.test/player/1")

    assert link == "https://storage.test/rec.mp3?sv=1&token=x"
    request = player.calls.last.request
    assert request.extensions["timeout"]["read"] == AUDIO_TIMEOUT_S


@respx.mock
async def test_fresh_audio_link_no_cache_two_calls_two_requests() -> None:
    player = respx.get("https://org.test/player/1").mock(
        return_value=httpx.Response(200, text='<source src="https://storage.test/rec.mp3">')
    )
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        first = await api.fresh_audio_link("https://org.test/player/1")
        second = await api.fresh_audio_link("https://org.test/player/1")

    assert first == second == "https://storage.test/rec.mp3"
    assert player.call_count == 2


@pytest.mark.parametrize("status", [404, 500])
@respx.mock
async def test_fresh_audio_link_error_status_returns_none(status: int) -> None:
    player = respx.get("https://org.test/player/1").mock(return_value=httpx.Response(status, text="oops"))
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        assert await api.fresh_audio_link("https://org.test/player/1") is None
    assert player.call_count == 1


@respx.mock
async def test_fresh_audio_link_timeout_returns_none() -> None:
    respx.get("https://org.test/player/1").mock(side_effect=httpx.ReadTimeout("org.test timed out"))
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        assert await api.fresh_audio_link("https://org.test/player/1") is None


@respx.mock
async def test_fresh_audio_link_without_source_in_html_returns_none() -> None:
    respx.get("https://org.test/player/1").mock(return_value=httpx.Response(200, text="<p>нет ссылки</p>"))
    async with httpx.AsyncClient() as client:
        api = OrgApi(TEMPLATE, client)
        assert await api.fresh_audio_link("https://org.test/player/1") is None


@respx.mock
async def test_fetch_group_without_url_makes_no_requests() -> None:
    async with httpx.AsyncClient() as client:
        api = OrgApi(None, client)
        with pytest.raises(OrgApiError, match="CQA_ORG_API_URL не задан"):
            await api.fetch_group("DEV")

    assert len(respx.calls) == 0
