"""Темы обращений: хранение справочника и тем диалогов, классификатор за охраной реальных звонков, запуск."""

import asyncio
import json
from collections.abc import Mapping, Sequence

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Dialog, Line, Product, ProductTag
from cqa.domain.prompt import Message
from cqa.services.errors import Invalid, NotFound
from cqa.services.evaluation import RealDataBlocked, Reply
from cqa.services.products import Classifier, Pick, classify_plan, save_products, set_manual
from cqa.services.runs import Runner, plan_run
from fakes import FIXTURES, FakeEvaluator, prototype_checklist

PRODUCTS = [Product.model_validate(p) for p in json.loads((FIXTURES / "products.json").read_text("utf-8"))]
CHECKLIST = prototype_checklist()
REPLY = '{"reason_ru": "Клиент спрашивает о выводе (реплика 2)", "turn_ids": [2], "answer": "funding"}'


class FakeChat:
    def __init__(self, text: str = REPLY) -> None:
        self.text = text
        self.sent: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Reply:
        self.sent.append(messages)
        return Reply(text=self.text, cost=0.0003, ms=5)


class FakeJev:
    def __init__(self) -> None:
        self.asked: list[Mapping[str, str]] = []

    async def pick(self, dialog_text: str, options: Mapping[str, str]) -> Pick:
        self.asked.append(options)
        return Pick(choice="funding", probs={"funding": 0.8, "account": 0.2}, p=0.8, cost=0.00005)


class FakeClassifier:
    def __init__(self, fail: Sequence[str] = ()) -> None:
        self.fail = set(fail)
        self.seen: list[str] = []

    async def classify(self, dialog: Dialog, products: Sequence[Product]) -> ProductTag:
        self.seen.append(dialog.id)
        if dialog.id in self.fail:
            raise RuntimeError("нет записи")
        return ProductTag(status="done", id="funding", name="Пополнение", by="m", cost=0.0001)


def _classifier(chat: FakeChat | None = None, jev: FakeJev | None = None, **kw: object) -> Classifier:
    args: dict[str, object] = {"anonymize": True, "sends_real_data": False, "allow_real_data": False} | kw
    return Classifier(jev=jev, model=chat or FakeChat(), model_name="qwen3-6", **args)  # type: ignore[arg-type]


def _dialog(ch: str = "chat") -> Dialog:
    lines = [
        Line(n=1, t="00:01", who="client", text="Мой телефон +7 701 123 45 67, где деньги?"),
        Line(n=2, t="00:05", who="operator", text="Проверяю вывод."),
    ]
    return Dialog(id="d1", ch=ch, lang="RU", at="08.11", lines=lines)  # type: ignore[arg-type]


# --- хранилище и справочник ---


def test_taxonomy_is_saved_whole_and_validated(store: Store) -> None:
    assert store.products() is None
    assert save_products(store, PRODUCTS) == PRODUCTS
    assert store.products() == PRODUCTS
    with pytest.raises(Invalid, match="Повторяется код темы account"):
        save_products(store, [PRODUCTS[0], PRODUCTS[0]])
    with pytest.raises(Invalid, match="Справочник тем пуст"):
        save_products(store, [])


def test_dialog_carries_its_topic_and_pending_marks_are_cleared(store: Store) -> None:
    tag = ProductTag(status="done", id="funding", name="Пополнение", by="m")
    store.set_product("call-024", tag, "k1")
    store.set_product("p1-ru-003", ProductTag(status="pending"), "")
    assert {d.id: d.product for d in store.list_dialogs()} == {
        "call-024": tag,
        "p1-ru-003": ProductTag(status="pending"),
    }
    store.clear_pending_products()
    assert store.get_dialog("p1-ru-003").product is None  # type: ignore[union-attr]
    assert store.get_dialog("call-024").product == tag  # type: ignore[union-attr]


def test_manual_topic_overrides_and_survives_reclassification(store: Store) -> None:
    store.set_products(PRODUCTS)
    tag = set_manual(store, "call-024", "kyc", "Клиент просит обновить документы")
    assert (tag.status, tag.id, tag.by, tag.confidence, tag.basis.why) == (
        "done",
        "kyc",
        "вручную",
        None,
        "Клиент просит обновить документы",
    )
    assert [d.id for d, _ in classify_plan(store, PRODUCTS, store.list_dialogs())] == ["p1-ru-003"]
    with pytest.raises(Invalid, match="Нет темы loans"):
        set_manual(store, "call-024", "loans", "")
    with pytest.raises(NotFound):
        set_manual(store, "nope", "kyc", "")


def test_plan_skips_topics_of_the_same_taxonomy_and_text_and_retries_errors(store: Store) -> None:
    plan = classify_plan(store, PRODUCTS, store.list_dialogs())
    (d, key), _ = plan
    store.set_product(d.id, ProductTag(status="done", id="funding"), key)
    store.set_product("p1-ru-003", ProductTag(status="error", error="сбой"), "")
    assert [x.id for x, _ in classify_plan(store, PRODUCTS, store.list_dialogs())] == ["p1-ru-003"]
    renamed = [PRODUCTS[0].model_copy(update={"name": "Счёт"}), *PRODUCTS[1:]]
    assert len(classify_plan(store, renamed, store.list_dialogs())) == 2


# --- классификатор ---


async def test_without_jev_one_model_call_with_anonymized_dialog() -> None:
    chat = FakeChat()
    tag = await _classifier(chat).classify(_dialog(), PRODUCTS)
    assert (tag.status, tag.id, tag.by, tag.basis.ev, tag.cost) == ("done", "funding", "qwen3-6", [2], 0.0003)
    (messages,) = chat.sent
    assert "+7 701" not in messages[1]["content"] and "[ТЕЛЕФОН]" in messages[1]["content"]


async def test_with_jev_one_choice_question_and_no_model_call() -> None:
    chat, jev = FakeChat(), FakeJev()
    tag = await _classifier(chat, jev).classify(_dialog(), PRODUCTS)
    assert (tag.by, tag.confidence, tag.basis.probs) == ("jev", 0.8, {"funding": 0.8, "account": 0.2})
    assert chat.sent == []
    assert list(jev.asked[0]) == [p.id for p in PRODUCTS]


async def test_real_call_is_not_sent_to_any_model_without_permission() -> None:
    chat, jev = FakeChat(), FakeJev()
    with pytest.raises(RealDataBlocked):
        await _classifier(chat, sends_real_data=True).classify(_dialog("call"), PRODUCTS)
    with pytest.raises(RealDataBlocked):
        await _classifier(chat, jev, sends_real_data=True).classify(_dialog("call"), PRODUCTS)
    assert (chat.sent, jev.asked) == ([], [])
    allowed = await _classifier(chat, sends_real_data=True, allow_real_data=True).classify(
        _dialog("call"), PRODUCTS
    )
    assert allowed.status == "done"


# --- запуск ---


async def _run(store: Store, classifier: FakeClassifier, evaluator: FakeEvaluator | None = None) -> Runner:
    runner = Runner(store, evaluator or FakeEvaluator(), parallel=2, classifier=classifier)
    run_id = runner.start(None, None)
    for _ in range(200):
        if runner.progress(run_id)["status"] != "running":
            break
        await asyncio.sleep(0.01)
    return runner


async def test_run_classifies_each_dialog_once_with_separate_progress(store: Store) -> None:
    store.set_products(PRODUCTS)
    evaluator, classifier = FakeEvaluator(), FakeClassifier()
    runner = await _run(store, classifier, evaluator)
    progress = runner.progress(1)
    assert progress["products"] == {"done": 2, "total": 2, "errors": 0, "cost": pytest.approx(0.0002)}
    assert (progress["done"], progress["total"], progress["errors"]) == (16, 16, [])
    assert progress["cost"] == pytest.approx(0.016)  # цена оценки без цены тем
    assert sorted(classifier.seen) == ["call-024", "p1-ru-003"]
    assert {d.id: d.product.id for d in store.list_dialogs() if d.product} == {
        "call-024": "funding",
        "p1-ru-003": "funding",
    }

    again = await _run(store, classifier, evaluator)
    assert again.progress(2)["products"]["total"] == 0  # готовые темы не спрашиваются снова
    assert sorted(classifier.seen) == ["call-024", "p1-ru-003"]


async def test_failed_topic_is_an_error_status_and_does_not_touch_scoring(store: Store) -> None:
    store.set_products(PRODUCTS)
    runner = await _run(store, FakeClassifier(fail={"p1-ru-003"}))
    progress = runner.progress(1)
    assert (progress["products"]["errors"], progress["errors"], progress["done"]) == (1, [], 16)
    tag = store.get_dialog("p1-ru-003").product  # type: ignore[union-attr]
    assert tag == ProductTag(status="error", error="нет записи")


async def test_run_with_scores_ready_still_classifies_new_dialogs(store: Store) -> None:
    store.set_products(PRODUCTS)
    await _run(store, FakeClassifier(fail={"call-024", "p1-ru-003"}))
    assert plan_run(store, CHECKLIST, None, None) == []
    classifier = FakeClassifier()
    runner = await _run(store, classifier)
    assert runner.progress(2)["products"] == {
        "done": 2,
        "total": 2,
        "errors": 0,
        "cost": pytest.approx(0.0002),
    }
