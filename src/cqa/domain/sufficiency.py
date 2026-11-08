"""Достаточность данных диалога: чистые детерминированные правила (docs/insufficient-data.md).

Правило — id, текст для пользователя, обоснование исхода по умолчанию и проверка: по диалогу она
возвращает основание (что именно найдено) или None. Исход правила (block, flag, info) — данные,
их меняет `PUT /api/sufficiency`. Эвристик по смыслу текста нет: только счёт реплик, масок и меток.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cqa.domain.events import classify_event
from cqa.domain.ingest import ts_seconds
from cqa.domain.models import MANUAL, CriterionResult, Dialog, Line, Outcome, Reason, Sufficiency

# Наименьший обмен, на котором применим чек-лист: приветствие оператора, запрос клиента, ответ.
MIN_LINES = 3
# Доля слов под маской, выше которой маска перевешивает текст.
MASKED_MAX = 0.5
# Языки, на которых выверены промпт, эталон и проверка оснований.
LANGS = frozenset({"RU", "KZ", "EN"})
UNSUPPORTED = "ответ без основания при неполных данных"

_MASK = re.compile(r"\[[^\[\]]*\]")  # маска организаторов: «[Имя скрыто]»
_WORD = re.compile(r"\w+")
_SPEECH = ("client", "operator")


def _lines(d: Dialog) -> list[Line]:
    return [x for x in d.lines or [] if isinstance(x, Line)]


def _speech(d: Dialog) -> list[Line]:
    return [x for x in _lines(d) if x.who in _SPEECH]


def _talk(d: Dialog) -> list[Line] | None:
    """Реплики клиента и оператора, если оператор есть; иначе None — решают bot_only и no_operator."""
    speech = _speech(d)
    return speech if any(x.who == "operator" for x in speech) else None


def _bot_only(d: Dialog, has_audio: bool) -> str | None:
    if _speech(d):
        return None
    n = len(_lines(d))
    return f"реплик клиента и оператора нет, реплик бота и системы — {n}" if n else "реплик нет"


def _no_operator(d: Dialog, has_audio: bool) -> str | None:
    speech = _speech(d)
    if not speech or _talk(d) is not None:
        return None
    return f"реплик клиента — {len(speech)}, реплик оператора нет"


def _no_client_request(d: Dialog, has_audio: bool) -> str | None:
    talk = _talk(d)
    if talk is None:
        return None
    client = [x for x in talk if x.who == "client"]
    if any(_WORD.search(_MASK.sub(" ", x.text)) for x in client):
        return None
    return f"реплик клиента — {len(client)}, в них только маски" if client else "реплик клиента нет"


def _too_short(d: Dialog, has_audio: bool) -> str | None:
    talk = _talk(d)
    if talk is None or len(talk) >= MIN_LINES:
        return None
    return f"реплик клиента и оператора — {len(talk)}, нужно не меньше {MIN_LINES}"


def _truncated(d: Dialog, has_audio: bool) -> str | None:
    talk = _talk(d)
    if talk is None or talk[-1].who != "client":
        return None
    if any(x.who in ("system", "bot") and classify_event(x.text) == "end" for x in _lines(d)):
        return None
    return (
        f"последняя реплика {talk[-1].n} — клиента, после неё нет ни ответа оператора, ни события завершения"
    )


def _masked_heavy(d: Dialog, has_audio: bool) -> str | None:
    text = " ".join(x.text for x in _speech(d))
    masks = len(_MASK.findall(text))
    total = masks + len(_WORD.findall(_MASK.sub(" ", text)))
    if not total or masks / total <= MASKED_MAX:
        return None
    return f"под маской {masks} из {total} слов ({masks / total:.0%})"


def _no_audio(d: Dialog, has_audio: bool) -> str | None:
    return "звонок без ссылки на запись" if d.ch == "call" and not has_audio else None


def _seconds(x: Line) -> float | None:
    return float(x.t) if isinstance(x.t, int | float) else ts_seconds(x.t)


def _no_timestamps(d: Dialog, has_audio: bool) -> str | None:
    speech = _speech(d)
    distinct = {s for x in speech if (s := _seconds(x)) is not None}
    if len(speech) < 2 or len(distinct) >= 2:
        return None
    return f"различных меток времени — {len(distinct)} на {len(speech)} реплик клиента и оператора"


def _unknown_language(d: Dialog, has_audio: bool) -> str | None:
    if d.lang.upper() in LANGS:
        return None
    return f"язык {d.lang or 'не указан'}, выверены {', '.join(sorted(LANGS))}"


@dataclass(frozen=True)
class Rule:
    id: str
    text: str  # что видит пользователь
    why: str  # почему исход по умолчанию такой
    default: Outcome
    check: Callable[[Dialog, bool], str | None]  # (диалог, есть запись) → основание или None


RULES: tuple[Rule, ...] = (
    Rule(
        "bot_only",
        "Только бот и система",
        "Все критерии оценивают оператора в разговоре с клиентом. Без реплик клиента и оператора "
        "оценивать нечего, любой ответ модели был бы выдуман: диалог модели не отправляется.",
        "block",
        _bot_only,
    ),
    Rule(
        "no_operator",
        "Нет реплик оператора",
        "Критерии оценивают действия оператора, а N/A разрешён не у всех: без реплик оператора модель "
        "была бы вынуждена угадывать. Диалог модели не отправляется, в файле результатов — status: error.",
        "block",
        _no_operator,
    ),
    Rule(
        "no_client_request",
        "Клиент ничего не сказал",
        "Нет ни одной реплики клиента с текстом, кроме масок. Сформулирован ли запрос, решает модель по "
        "условию N/A каждого критерия; код только помечает диалог, чтобы человек проверил ответы.",
        "flag",
        _no_client_request,
    ),
    Rule(
        "too_short",
        "Слишком короткий диалог",
        f"Наименьший обмен для чек-листа — приветствие, запрос и ответ, {MIN_LINES} реплики клиента и "
        "оператора; при меньшем числе часть критериев судится по одной-двум репликам. Не блок: короткий "
        "диалог бывает законченным (клиент ушёл), модель отвечает по условиям N/A.",
        "flag",
        _too_short,
    ),
    Rule(
        "truncated",
        "Диалог оборван",
        "Последняя реплика — клиента, после неё нет ни ответа оператора, ни события завершения: запись "
        "могла оборваться, о завершении судить трудно. Только пометка: клиент мог сам перестать отвечать.",
        "flag",
        _truncated,
    ),
    Rule(
        "masked_heavy",
        "Почти всё скрыто маской",
        f"Больше {MASKED_MAX:.0%} слов клиента и оператора под маской [...]: содержание модель не видит "
        "и может додумать. Пометка, а не блок: ход разговора (приветствие, завершение) обычно виден.",
        "flag",
        _masked_heavy,
    ),
    Rule(
        "no_audio",
        "Нет записи звонка",
        "Без записи интонация недоступна, блок звука в запрос не добавляется. Расшифровка оценивается "
        "как обычно, поэтому только сведение.",
        "info",
        _no_audio,
    ),
    Rule(
        "no_timestamps",
        "Нет меток времени",
        "Меньше двух различных меток времени у реплик клиента и оператора: паузы и время ответа не "
        "посчитать. Оценке по тексту это не мешает, поэтому только сведение.",
        "info",
        _no_timestamps,
    ),
    Rule(
        "unknown_language",
        "Неизвестный язык",
        f"Язык не из {', '.join(sorted(LANGS))}: промпт, эталон и проверка оснований выверены только на "
        "них, надёжность ответов на другом языке не подтверждена. Модель оценивает, человек проверяет.",
        "flag",
        _unknown_language,
    ),
)

_RANK = {"info": 0, "flag": 1, "block": 2}


def assess(dialog: Dialog, *, has_audio: bool, outcomes: Mapping[str, Outcome]) -> Sufficiency:
    """Сработавшие правила в порядке RULES; статус — самый строгий исход среди них (info — ok).

    `lines: null` — расшифровка ещё не загружена (моки прототипа): судить не о чем, оценщик сам откажет.
    """
    if dialog.lines is None:
        return Sufficiency(status="ok")
    reasons = [
        Reason(id=r.id, text=r.text, basis=basis, outcome=outcomes.get(r.id, r.default))
        for r in RULES
        if (basis := r.check(dialog, has_audio)) is not None
    ]
    worst = max((_RANK[x.outcome] for x in reasons), default=0)
    return Sufficiency(status=("ok", "flag", "block")[worst], reasons=reasons)


def mark_unsupported(res: Mapping[str, CriterionResult], s: Sufficiency) -> dict[str, CriterionResult]:
    """На диалоге «Мало данных» ответ модели не N/A без реплик-оснований и участка — на проверку.

    Ответ не меняется никогда; флаг («не найдено» без оснований — норма) и ручной ответ не помечаются.
    """

    def weak(r: CriterionResult) -> bool:
        return r.a != "na" and not isinstance(r.a, dict) and not r.ev and not r.seg and r.model != MANUAL

    if s.status != "flag":
        return dict(res)
    return {cid: r.model_copy(update={"reviewWhy": UNSUPPORTED}) if weak(r) else r for cid, r in res.items()}
