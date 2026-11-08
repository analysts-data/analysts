"""Свежая ссылка на запись, запасной плеер, интонация и статистика разговора; подписанные адреса не попадают
в ответы и журнал."""

from typing import Any

from fastapi import APIRouter, Request, Response

from cqa.services.errors import NotFound, Upstream
from cqa.services.prosody import dialog_prosody
from cqa.services.talkstats import dialog_talkstats, team_norms

router = APIRouter()


@router.get("/api/dialogs/{id}/audio")
async def fresh_audio(id: str, request: Request) -> Response:
    """302 на свежий MP3 из плеера организаторов; 404 — чат и неизвестный id, 502 — не вышло."""
    audio_url = request.app.state.store.audio_url(id)
    if audio_url is None:
        raise NotFound(f"У диалога {id} нет записи")
    link = await request.app.state.source.audio_link(audio_url)
    if link is None:
        raise Upstream(f"Не удалось получить свежую ссылку на запись диалога {id}")
    return Response(status_code=302, headers={"Location": link, "Cache-Control": "no-store"})


@router.get("/api/dialogs/{id}/player")
async def org_player(id: str, request: Request) -> Response:
    """302 на плеер организаторов, без запросов наружу; запасной путь для реплик без `s`."""
    audio_url = request.app.state.store.audio_url(id)
    if audio_url is None:
        raise NotFound(f"У диалога {id} нет записи")
    return Response(status_code=302, headers={"Location": audio_url})


@router.get("/api/dialogs/{id}/prosody")
async def prosody(id: str, request: Request) -> dict[str, Any]:
    """Интонация звонка по звуку; 404 — чат и неизвестный id, 502 — запись не получена."""
    state = request.app.state
    return await dialog_prosody(state.store, state.source, state.voice, id)


@router.get("/api/dialogs/{id}/talkstats")
async def talkstats(id: str, request: Request) -> dict[str, Any]:
    """Статистика разговора с нормами команды; 404 — нет данных, 502 — запись звонка не получена."""
    state = request.app.state
    return await dialog_talkstats(state.store, state.source, state.voice, id)


@router.get("/api/talkstats/norms")
async def talkstats_norms(request: Request) -> dict[str, Any]:
    """Медиана, квартили и границы Тьюки по звонкам с разбором и по чатам."""
    return team_norms(request.app.state.store)
