"""Темы обращений: справочник, ручная тема, план классификации и классификатор за охраной `_Gate`.

Классификатор — один вызов на диалог: вопрос choice Jev, если задан ключ Jev, иначе короткий запрос JSON
к основной модели. Реальный звонок, обезличивание и ошибка конфигурации — как у оценки (`_Gate._admit`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from cqa.adapters.store import Store
from cqa.domain.models import Dialog, Line, Product, ProductBasis, ProductTag
from cqa.domain.products import MANUAL, jev_tag, model_tag, product_key, product_messages
from cqa.domain.prompt import render_dialog
from cqa.services.errors import Invalid, NotFound
from cqa.services.evaluation import ChatModel, _Gate


@dataclass(frozen=True)
class Pick:
    choice: str | None  # id темы
    probs: dict[str, float]  # вероятность каждой темы
    p: float | None  # вероятность выбранной
    cost: float


class Picker(Protocol):  # JevVerifier.pick
    async def pick(self, dialog_text: str, options: Mapping[str, str]) -> Pick: ...


def save_products(store: Store, products: Sequence[Product]) -> list[Product]:
    """`PUT /api/products`: справочник целиком; темы диалогов пересчитает следующий запуск (ключ кэша)."""
    if not products:
        raise Invalid("Справочник тем пуст")
    seen: set[str] = set()
    for p in products:
        if p.id in seen:
            raise Invalid(f"Повторяется код темы {p.id}")
        seen.add(p.id)
    store.set_products(products)
    return list(products)


def taxonomy(store: Store) -> list[Product]:
    return store.products() or []


def set_manual(store: Store, dialog_id: str, pid: str, reason: str) -> ProductTag:
    """`PUT /api/dialogs/{id}/product`: тема вручную, запуск её не перезаписывает."""
    if store.get_dialog(dialog_id) is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    names = {p.id: p.name for p in taxonomy(store)}
    if pid not in names:
        raise Invalid(f"Нет темы {pid} в справочнике")
    tag = ProductTag(
        status="done", id=pid, name=names[pid], by=MANUAL, basis=ProductBasis(why=reason or None)
    )
    store.set_product(dialog_id, tag, MANUAL)
    return tag


def classify_plan(
    store: Store, products: Sequence[Product], dialogs: Sequence[Dialog]
) -> list[tuple[Dialog, str]]:
    """Диалоги без темы для этого справочника и текста, с ключом кэша. Ручная тема из справочника остаётся."""
    keys = store.product_keys()
    ids = {p.id for p in products}
    plan = []
    for d in dialogs:
        tag = d.product
        if tag is not None and tag.by == MANUAL and tag.id in ids:
            continue
        key = product_key(products, d)
        if keys.get(d.id) != key:
            plan.append((d, key))
    return plan


class Classifier(_Gate):
    """Тема диалога: Jev, если есть `jev`, иначе `model`. Бросает ошибки `_admit` и модели."""

    def __init__(
        self,
        *,
        jev: Picker | None,
        model: ChatModel,
        model_name: str,
        anonymize: bool,
        sends_real_data: bool,
        allow_real_data: bool,
        config_error: str | None = None,
    ) -> None:
        self.jev = jev
        self.model = model
        self.model_name = model_name
        self.anonymize = anonymize
        self.sends_real_data = sends_real_data
        self.allow_real_data = allow_real_data
        self.config_error = None if jev else config_error  # Jev не нужен адрес и ключ языковой модели
        self.prosody = None

    async def classify(self, dialog: Dialog, products: Sequence[Product]) -> ProductTag:
        dialog = self._admit(dialog)
        text = render_dialog(dialog)
        if self.jev is not None:
            pick = await self.jev.pick(text, {p.id: f"{p.name}: {p.description}" for p in products})
            return jev_tag(pick.choice, pick.probs, pick.p, products, cost=pick.cost)
        reply = await self.model.complete(product_messages(text, products))
        lines = {x.n for x in dialog.lines or [] if isinstance(x, Line)}
        return model_tag(reply.text, products, lines, by=self.model_name, cost=reply.cost)
