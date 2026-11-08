"""Интонация в оценке звонка: оценщик сервера берёт разбор `/prosody` через порт, звук — подделка `Voice`."""

import httpx
from fastapi import FastAPI
from test_prosody_route import CALL, CHAT, FakeVoice, dialogs, make_app, speech_of

from cqa.domain.audio_timeline import utterance_s
from cqa.domain.models import Dialog, Line
from cqa.domain.prompt import Message, sound_block
from cqa.domain.prosody import Tracks
from cqa.services.evaluation import LlmEvaluator, Reply
from fakes import FakeSource


def raised(dialog: Dialog) -> tuple[Tracks, int]:
    """Речь звонка, у самой длинной реплики клиента тон вдвое выше: флаг `raised`."""
    tr = speech_of(dialog)
    loud = [
        ln for ln in dialog.lines or [] if isinstance(ln, Line) and ln.who == "client" and ln.s is not None
    ]
    ln = max(loud, key=lambda x: utterance_s(x.text))
    assert ln.s is not None
    m = (tr.pitch_t >= ln.s) & (tr.pitch_t < ln.s + utterance_s(ln.text))
    tr.f0[m] = 300.0
    return tr, ln.n


class Capture:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Reply:
        self.calls.append(messages)
        return Reply(text='{"reason_ru": "ok", "answer": "yes"}', cost=0.0, ms=1)


def evaluator(app: FastAPI, model: Capture) -> LlmEvaluator:
    return LlmEvaluator(
        model,
        model_name="m",
        reasoning="off",
        anonymize=True,
        verifier=None,
        sends_real_data=False,
        allow_real_data=False,
        prosody=app.state.prosody,
    )


async def test_call_evaluation_sends_the_cached_sound_summary_without_names() -> None:
    call = dialogs()[CALL]
    tracks, n = raised(call)
    app = make_app(FakeVoice(tracks))
    checklist = app.state.store.current_checklist()
    model = Capture()

    await evaluator(app, model).evaluate(call, checklist, checklist.criteria)

    users = [m[1]["content"] for m in model.calls]
    assert users and all(
        "Анализ звука записи" in u and f"- Клиент повысил тон в реплике {n}\n" in u for u in users
    )
    stored = app.state.store.prosody(CALL)  # посчитано и сохранено, как у `/prosody`
    assert f"</dialog>\n\n{sound_block(stored)}\n\n" in users[0]
    # только фразы о ролях и номерах реплик: ни слова из расшифровки, имён тоже
    assert all(s.startswith(("Клиент ", "Оператор ", "Пауза ")) for s in stored["summary"])


async def test_call_without_record_or_chat_is_sent_as_before() -> None:
    app = make_app(FakeVoice(None))  # запись не получена — 502 у `/prosody`
    checklist = app.state.store.current_checklist()
    for dialog in (dialogs()[CALL], dialogs()[CHAT]):
        model = Capture()
        await evaluator(app, model).evaluate(dialog, checklist, checklist.criteria)
        assert model.calls and not any("Анализ звука" in m[1]["content"] for m in model.calls)
    assert app.state.store.prosody(CALL) is None


async def test_server_evaluator_uses_the_app_sound_port_also_after_mode_change() -> None:
    app = make_app(FakeVoice(None), FakeSource())
    assert app.state.runner._evaluator.prosody is app.state.prosody
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        mode = (await client.get("/api/config")).json()
        r = await client.put(
            "/api/config", json=mode | {"evaluator": "jev", "llm_base_url": "https://llm.test/v1"}
        )
    assert r.status_code == 200, r.text
    assert app.state.runner._evaluator.prosody is app.state.prosody
