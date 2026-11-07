"""Свежая ссылка на запись и запасной плеер; подписанные адреса не попадают в ответы и журнал."""

from fastapi import APIRouter, Request, Response

from cqa.services.errors import NotFound, Upstream

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
