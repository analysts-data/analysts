"""Сервис версий чек-листа (группа 4, задачи 4.1–4.5)."""

import json
from pathlib import Path
from typing import Any

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Appeal, Checklist, CriterionResult, Dialog, Mode
from cqa.domain.review import fingerprint
from cqa.services.checklists import save_checklist
from cqa.services.errors import Conflict, Invalid
from cqa.services.state import build_state, current_results

FIXTURES = Path(__file__).parent.parent / "fixtures"
SEED_NOTE = "начальная версия"


def cl_fixture() -> Checklist:
    return Checklist.model_validate(json.loads((FIXTURES / "checklist_v3.json").read_text()))


def draft(
    edits: dict[str, dict[str, Any]] | None = None,
    remove: tuple[str, ...] = (),
    add: tuple[dict[str, Any], ...] = (),
    **top: Any,
) -> Checklist:
    """Черновик v3 из фикстуры: правки критериев по id, удаление, добавление, правки полей."""
    data = {**cl_fixture().model_dump(mode="json"), **top}
    kept = [{**c, **(edits or {}).get(c["id"], {})} for c in data["criteria"] if c["id"] not in remove]
    data["criteria"] = kept + list(add)
    return Checklist.model_validate(data)


def make_store() -> Store:
    conn = connect(":memory:")
    store = Store(conn)
    store.add_checklist(cl_fixture(), SEED_NOTE)
    return store


def fps(cl: Checklist, ch: str = "chat") -> dict[str, str]:
    return {c.id: fingerprint(cl, c, ch) for c in cl.criteria}


def add_results(store: Store, dialog_ids: list[str]) -> None:
    """Диалоги из прототипа с результатами всех восьми критериев по отпечаткам v3."""
    raw = {d["id"]: d for d in json.loads((FIXTURES / "dialogs_prototype.json").read_text())}
    for did in dialog_ids:
        data = raw[did]
        store.add_dialogs([Dialog.model_validate(data)], {})
        fp = fps(cl_fixture(), data["ch"])
        for cid, body in data["res"].items():
            store.add_result(did, cid, 3, fp[cid], CriterionResult.model_validate(body))


def rows(store: Store) -> int:
    conn = store._conn  # noqa: SLF001 — подсчёт строк в тесте
    return int(conn.execute("SELECT COUNT(*) FROM results").fetchone()[0])


def res_of(store: Store, dialog_id: str) -> dict[str, CriterionResult]:
    """Текущие результаты пары — тот же отбор по отпечатку, что в build_state (решение 9)."""
    checklist = store.current_checklist()
    assert checklist is not None
    return current_results(store, checklist, store.list_dialogs()).get(dialog_id, {})


def state_res(store: Store, dialog_id: str) -> dict[str, Any]:
    state = build_state(store, Mode(where="kz", anonymized=True, model="qwen3-6", verifier=None))
    return next(d["res"] for d in state["dialogs"] if d["id"] == dialog_id)


def appeal(dlg: str, cid: str, frm: Any = 15) -> Appeal:
    return Appeal.model_validate(
        {"id": "a0", "kind": "appeal", "dlg": dlg, "cid": cid, "from": frm, "ask": 20,
         "ev": [9], "by": "Оператор", "at": "07.11 15:10", "status": "pending",
         "comment": "Срок ответа назван в реплике 9."}
    )  # fmt: skip


def test_weight_change_creates_version_without_pending() -> None:
    store = make_store()

    out = save_checklist(store, draft({"06": {"w": 10}}))

    assert out == {"version": 4, "pending": []}
    assert store.list_versions()[-1] == {"v": 4, "note": "веса или названия 06"}


NEW_09 = {"id": "09", "sec": 1, "name": "Новый критерий", "type": "bool", "w": 5,
          "na": True, "text": "Да — новое."}  # fmt: skip


def test_meaning_change_lists_only_changed_criteria() -> None:
    out = save_checklist(
        make_store(), draft({"04": {"text": "Новый текст"}, "06": {"w": 10}}, remove=("07",))
    )

    assert out == {"version": 4, "pending": ["04"]}


def test_new_criterion_is_pending() -> None:
    assert save_checklist(make_store(), draft(add=(NEW_09,))) == {"version": 4, "pending": ["09"]}


def test_text_change_hides_result_but_keeps_rows() -> None:
    store = make_store()
    add_results(store, ["call-024", "p1-ru-003"])
    before = rows(store)

    save_checklist(store, draft({"04": {"text": "Новый текст"}}))

    assert "04" not in res_of(store, "call-024")
    assert len(res_of(store, "call-024")) == 7
    assert rows(store) == before


def test_text_change_hides_result_in_state() -> None:
    store = make_store()
    add_results(store, ["call-024", "p1-ru-003"])

    save_checklist(store, draft({"04": {"text": "Новый текст"}}))

    assert "04" not in state_res(store, "call-024")
    assert len(state_res(store, "call-024")) == 7


def test_removed_criterion_disappears_from_results() -> None:
    store = make_store()
    add_results(store, ["call-024", "p1-ru-003"])

    save_checklist(store, draft(remove=("07",)))

    assert "07" not in res_of(store, "call-024")
    assert "07" not in {c.id for c in store.current_checklist().criteria}


def test_meaning_change_closes_pending_appeal() -> None:
    store = make_store()
    add_results(store, ["p1-ru-003"])
    store.add_appeal(appeal("p1-ru-003", "04"), fps(cl_fixture())["04"])

    save_checklist(store, draft({"04": {"text": "Новый текст"}}))

    assert store.get_appeal("a1")[0].status == "closed"


def test_removal_closes_pending_appeal() -> None:
    store = make_store()
    add_results(store, ["p1-ru-003"])
    store.add_appeal(appeal("p1-ru-003", "07", frm="yes"), fps(cl_fixture())["07"])

    save_checklist(store, draft(remove=("07",)))

    assert store.get_appeal("a1")[0].status == "closed"


def test_weight_change_keeps_pending_appeal() -> None:
    store = make_store()
    add_results(store, ["p1-ru-003"])
    store.add_appeal(appeal("p1-ru-003", "04"), fps(cl_fixture())["04"])

    save_checklist(store, draft({"04": {"w": 5}}))

    assert store.get_appeal("a1")[0].status == "pending"


# --- Задача 4.5: отказы ---


def test_stale_draft_conflicts() -> None:
    store = make_store()
    save_checklist(store, draft({"06": {"w": 10}}))  # теперь v4

    with pytest.raises(Conflict, match="Черновик основан на v3, текущая версия v4. Обновите страницу."):
        save_checklist(store, draft({"06": {"w": 11}}))


def test_unchanged_draft_returns_current_version_without_new_row() -> None:
    store = make_store()

    assert save_checklist(store, draft()) == {"version": 3, "pending": []}
    assert store.list_versions() == [{"v": 3, "note": SEED_NOTE}]


def test_duplicate_id_is_invalid() -> None:
    store = make_store()
    dup = draft(add=(NEW_09,)).model_dump(mode="json")
    dup["criteria"][0] = {**dup["criteria"][0], "id": "04"}

    with pytest.raises(Invalid, match="Повторяется id критерия 04"):
        save_checklist(store, Checklist.model_validate(dup))


def test_unknown_section_is_invalid() -> None:
    with pytest.raises(Invalid, match="Критерий 04: секции 7 нет"):
        save_checklist(make_store(), draft({"04": {"sec": 7}}))


def test_scale_without_steps_is_invalid() -> None:
    with pytest.raises(Invalid, match="Критерий 06: у шкалы нет ступеней"):
        save_checklist(make_store(), draft({"06": {"steps": []}}))


def test_channel_without_na_is_invalid() -> None:
    with pytest.raises(Invalid, match="Критерий 05: для канала chat нужен na: true"):
        save_checklist(make_store(), draft({"05": {"channel": "chat"}}))


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"steps": None, "stepText": None}, "Критерий 04: у шкалы нет ступеней"),
        (
            {"stepText": {"20": "Всё", "15": "Почти", "10": "Часть", "0": "Нет"}},
            "Критерий 04: нет текста ступени 5",
        ),
    ],
)
def test_scale_needs_steps_with_text_for_each(edit: dict[str, Any], message: str) -> None:
    store = make_store()
    with pytest.raises(Invalid, match=message):
        save_checklist(store, draft({"04": edit}))
    assert len(store.list_versions()) == 1
