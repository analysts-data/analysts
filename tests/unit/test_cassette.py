"""CassetteTransport: запись и воспроизведение ответов моделей без сети."""

import hashlib
import json

import httpx
import respx

from cqa.adapters.cassette import CassetteMissing, CassetteTransport

URL = "https://llm.example/v1/chat/completions"
BODY = {"model": "qwen3-6", "messages": [{"role": "user", "content": "привет"}]}
KEY = "sk-test0123456789abcdef"


def _key(body: dict) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _write(directory, body: dict, response: dict, status: int = 200) -> None:
    path = directory / f"{_key(body)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"request": body, "status": status, "response": response}, ensure_ascii=False),
        encoding="utf-8",
    )


async def test_replay_answers_from_file_without_network(tmp_path):
    _write(tmp_path, BODY, {"choices": [{"message": {"content": "ответ"}}]})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).mock(side_effect=AssertionError("сеть запрещена"))
        transport = CassetteTransport("replay", tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(URL, json=BODY, headers={"Authorization": f"Bearer {KEY}"})
    assert response.status_code == 200
    assert response.json() == {"choices": [{"message": {"content": "ответ"}}]}
    assert route.call_count == 0


async def test_replay_without_record_raises_cassette_missing(tmp_path):
    transport = CassetteTransport("replay", tmp_path)
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            await client.post(URL, json=BODY)
        except CassetteMissing as exc:
            message = str(exc)
        else:
            raise AssertionError("ожидали CassetteMissing")
    assert f"{_key(BODY)}.json" in message
    assert "make record" in message


async def test_record_saves_live_answer_without_secrets(tmp_path):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(200, json={"choices": [{"message": {"content": "живой"}}]})
        transport = CassetteTransport("record", tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(URL, json=BODY, headers={"Authorization": f"Bearer {KEY}"})
    assert response.json() == {"choices": [{"message": {"content": "живой"}}]}
    path = tmp_path / f"{_key(BODY)}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {
        "request": BODY,
        "status": 200,
        "response": {"choices": [{"message": {"content": "живой"}}]},
    }
    assert KEY not in path.read_text(encoding="utf-8")
    assert "Authorization" not in path.read_text(encoding="utf-8")


async def test_record_plays_existing_record_without_network(tmp_path):
    _write(tmp_path, BODY, {"choices": [{"message": {"content": "из записи"}}]})
    before = (tmp_path / f"{_key(BODY)}.json").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).mock(side_effect=AssertionError("сеть запрещена"))
        transport = CassetteTransport("record", tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(URL, json=BODY)
    assert response.json() == {"choices": [{"message": {"content": "из записи"}}]}
    assert route.call_count == 0
    assert (tmp_path / f"{_key(BODY)}.json").read_text(encoding="utf-8") == before


async def test_live_goes_to_network_and_writes_nothing(tmp_path):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(200, json={"ok": True})
        transport = CassetteTransport("live", tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(URL, json=BODY)
    assert response.json() == {"ok": True}
    assert list(tmp_path.iterdir()) == []


async def test_record_does_not_save_non_200(tmp_path):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(500, text="boom")
        transport = CassetteTransport("record", tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(URL, json=BODY)
    assert response.status_code == 500
    assert list(tmp_path.iterdir()) == []


async def test_replay_names_the_record_in_the_audit_log(tmp_path, monkeypatch):
    """5.2: полный прогон make e2e собирает белый список использованных записей."""
    log = tmp_path / "used.log"
    monkeypatch.setenv("CQA_CASSETTE_LOG", str(log))
    _write(tmp_path / "llm", BODY, {"choices": [{"message": {"content": "ответ"}}]})
    async with httpx.AsyncClient(transport=CassetteTransport("replay", tmp_path / "llm")) as client:
        await client.post(URL, json=BODY)
        await client.post(URL, json=BODY)
    assert log.read_text(encoding="utf-8").split() == [f"llm/{_key(BODY)}.json"] * 2
