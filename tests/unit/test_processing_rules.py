"""Правила обработки: первое включённое подходящее правило выбирает оценщик диалога."""

from cqa.adapters.store import Store, connect
from cqa.domain.routing import DEFAULT, Match, Rule
from cqa.services.routing import RoutedEvaluator, facts
from fakes import FakeEvaluator, prototype_checklist, prototype_dialogs

CHECKLIST = prototype_checklist()
DIALOGS = {d.id: d for d in prototype_dialogs()}


async def test_each_dialog_is_evaluated_by_the_first_enabled_matching_rule() -> None:
    store = Store(connect(":memory:"))
    store.add_dialogs(list(DIALOGS.values()), {"call-024": "https://storage.test/call-024.mp3"})
    off, calls, later, default = FakeEvaluator(), FakeEvaluator(), FakeEvaluator(), FakeEvaluator()
    rules = [
        Rule(id="off", name="выключено", enabled=False, match=Match(ch="call")),
        Rule(id="calls", name="Звонки → ds", match=Match(ch="call", has_audio=True)),
        Rule(id="later", name="позже", match=Match(ch="call")),  # звонок уже взяло правило выше
        Rule(id=DEFAULT, name="общий"),
    ]
    built = {"off": off, "calls": calls, "later": later}
    routed = RoutedEvaluator(rules, default, built, lambda d: facts(store, d))
    call = await routed.evaluate(DIALOGS["call-024"], CHECKLIST, CHECKLIST.criteria)
    chat = await routed.evaluate(DIALOGS["p1-ru-003"], CHECKLIST, CHECKLIST.criteria)
    assert (off.order, calls.order, later.order, default.order) == ([], ["call-024"], [], ["p1-ru-003"])
    assert {(e.result.rule_id, e.result.rule_name) for e in call.results} == {("calls", "Звонки → ds")}
    assert {e.result.rule_id for e in chat.results} == {None}  # общий режим: без пометки, как раньше
