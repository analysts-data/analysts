"""Окружение сценария защиты: свой uvicorn на каждый тест, набор загружен и оценён (design, решение 10).

Фикстуры не `autouse`: тесты экранов в `tests/e2e/web/` их не задевают. Пока продукта нет,
сценарий пропускается (`pytest.skip`), а не падает: нет кассет, сервер не поднялся, нет маршрута.
"""

import io
import os
import socket
import subprocess
import sys
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import ConsoleMessage, Error, Page, Route

from .steps import FIXTURES, Defence, wait_run

ROOT = Path(__file__).resolve().parents[3]
CASSETTES = ROOT / "tests" / "cassettes" / "llm"
# лимит сценария защиты; под нагрузкой (много параллельных агентов) слияние задаёт CQA_E2E_SESSION_LIMIT_S=300
SESSION_LIMIT_S = int(os.environ.get("CQA_E2E_SESSION_LIMIT_S", "120"))
START_TIMEOUT_S = 20


@pytest.fixture(scope="session")
def defence_clock() -> Iterator[None]:
    start = time.monotonic()
    yield
    took = time.monotonic() - start
    if took > SESSION_LIMIT_S:
        pytest.fail(f"сценарий защиты шёл {took:.0f} с, лимит {SESSION_LIMIT_S} с")


@pytest.fixture
def defence_api(defence_clock: None, tmp_path: Path) -> Iterator[httpx.Client]:
    """Свежий сервер с оценённым набором: `httpx.Client` с `base_url` сервера."""
    mode = os.environ.get("CQA_LLM_MODE", "replay")
    if mode == "replay" and not any(CASSETTES.glob("*.json")):
        pytest.skip("нет кассет tests/cassettes/llm: ждёт make record (5.2)")
    port = _free_port()
    log_path = tmp_path / "server.log"
    env = {**os.environ, "CQA_LLM_MODE": mode, "CQA_DB_PATH": str(tmp_path / "cqa.db")}
    cmd = [sys.executable, "-m", "uvicorn", "cqa.http.app:create_app", "--factory"]
    cmd += ["--app-dir", str(ROOT / "src"), "--host", "127.0.0.1", "--port", str(port)]
    with log_path.open("w") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as api:
            _wait_health(api, proc, log_path)
            _load_and_evaluate(api)
            yield api
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.fixture
def defence(defence_api: httpx.Client, page: Page) -> Defence:
    """Страница на сервере сценария; запись звонка подменена тишиной, ошибки консоли собираются."""
    d = Defence(page, defence_api)
    page.set_default_timeout(5_000)  # localhost: a broken step fails fast and fits the 120 s limit

    def console(m: ConsoleMessage) -> None:
        if m.type == "error":
            d.console_errors.append(m.text)

    def page_error(e: Error) -> None:
        d.console_errors.append(str(e))

    page.on("console", console)
    page.on("pageerror", page_error)
    longest = max((x["dur"] or 0 for x in d.state()["dialogs"] if x["ch"] == "call"), default=0)
    page.route("**/api/dialogs/*/audio", _serve(silence_wav(longest + 5)))
    # интонация: синтетическая запись не скачивается, сервер ответил бы 502 с ошибкой в консоли
    page.route(
        "**/api/dialogs/*/prosody",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"lines": [], "summary": []}'),
    )
    d.go("#/queue")
    return d


def silence_wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * int(seconds * 8000))  # 8-bit PCM: 0x80 is zero amplitude
    return buf.getvalue()


def _serve(wav: bytes) -> Callable[[Route], None]:
    """Ответ 206 на `Range`: без него Chromium не перематывает `<audio>`."""

    def handle(route: Route) -> None:
        first, _, last = route.request.headers.get("range", "").removeprefix("bytes=").partition("-")
        start, end = int(first or 0), int(last) if last else len(wav) - 1
        route.fulfill(
            status=206,
            headers={
                "Content-Type": "audio/wav",
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{len(wav)}",
            },
            body=wav[start : end + 1],
        )

    return handle


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(api: httpx.Client, proc: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"сервер не поднялся (код {proc.returncode}): {log.read_text()[-500:]}")
        try:
            if api.get("/api/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.skip(f"сервер не ответил на /api/health за {START_TIMEOUT_S} с: {log.read_text()[-500:]}")


def _load_and_evaluate(api: httpx.Client) -> None:
    raw = (FIXTURES / "defence_set.json").read_bytes()
    r = api.post("/api/datasets/upload", content=raw, headers={"Content-Type": "application/json"})
    if r.status_code in (404, 405):
        pytest.skip("ждёт review-workflow: нет POST /api/datasets/upload")
    if r.status_code == 503:
        pytest.skip(f"ждёт dialog-ingest: {r.text}")
    assert r.json() == {"added": 8, "skipped": 0}, r.text
    r = api.post("/api/runs", json={"dialogs": None, "criteria": None})
    if r.status_code == 503:
        pytest.skip(f"ждёт llm-evaluation: {r.text}")
    run = wait_run(api, r.raise_for_status().json()["run_id"])
    if run["status"] != "done" or run["errors"] or run["done"] != run["total"]:
        pytest.fail(f"оценка набора: {len(run['errors'])} ошибок запуска, {run}")
