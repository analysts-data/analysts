"""PUT /api/checklist (группа 4, задача 4.6)."""

import copy
from typing import Any

from fastapi.testclient import TestClient

NEW_09 = {"id": "09", "sec": 1, "name": "Новый критерий", "type": "bool", "w": 5,
          "na": True, "text": "Да — новое."}  # fmt: skip


def state_checklist(client: TestClient) -> dict[str, Any]:
    return client.get("/api/state").json()["checklist"]


def draft(
    client: TestClient,
    edits: dict[str, dict[str, Any]] | None = None,
    remove: tuple[str, ...] = (),
    add: tuple[dict[str, Any], ...] = (),
    **top: Any,
) -> dict[str, Any]:
    """Черновик из текущего чек-листа состояния: правки по id, удаление, добавление."""
    data = {**copy.deepcopy(state_checklist(client)), **top}
    kept = [{**c, **(edits or {}).get(c["id"], {})} for c in data["criteria"] if c["id"] not in remove]
    data["criteria"] = kept + list(add)
    return data


def test_put_checklist_saves_new_version(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"06": {"w": 10}}))

    assert response.status_code == 200
    assert response.json() == {"version": 4, "pending": []}
    state = client.get("/api/state").json()
    assert state["checklist"]["version"] == 4
    assert state["versions"][-1] == {"v": 4, "note": "веса или названия 06"}


def test_put_checklist_semantic_change_lists_pending(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"04": {"text": "Новый текст"}}))

    assert response.status_code == 200
    assert response.json() == {"version": 4, "pending": ["04"]}


def test_put_checklist_stale_draft_is_409(client: TestClient) -> None:
    stale = draft(client, {"06": {"w": 11}})  # черновик v3, захвачен до сохранения
    client.put("/api/checklist", json=draft(client, {"06": {"w": 10}}))  # теперь v4

    response = client.put("/api/checklist", json=stale)

    assert response.status_code == 409
    assert response.json() == {"detail": "Черновик основан на v3, текущая версия v4. Обновите страницу."}


def test_put_checklist_duplicate_id_is_422(client: TestClient) -> None:
    dup = draft(client, add=(NEW_09,))
    dup["criteria"][0] = {**dup["criteria"][0], "id": "04"}

    response = client.put("/api/checklist", json=dup)

    assert response.status_code == 422
    assert response.json() == {"detail": "Повторяется id критерия 04"}


def test_put_checklist_unknown_section_is_422(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"04": {"sec": 7}}))

    assert response.status_code == 422
    assert response.json() == {"detail": "Критерий 04: секции 7 нет"}


def test_put_checklist_channel_without_na_is_422(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"05": {"channel": "chat"}}))

    assert response.status_code == 422
    assert response.json() == {"detail": "Критерий 05: для канала chat нужен na: true"}


def test_put_checklist_scale_without_steps_is_422(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"01": {"type": "scale"}}))

    assert response.status_code == 422
    assert response.json() == {"detail": "Критерий 01: у шкалы нет ступеней"}


def test_put_checklist_rejects_bad_model_without_new_version(client: TestClient) -> None:
    response = client.put("/api/checklist", json=draft(client, {"05": {"type": "stars"}}))

    assert response.status_code == 422  # 422 от Pydantic: Literal["bool", "scale", "flag"]
    versions = client.get("/api/state").json()["versions"]
    assert versions == [{"v": 3, "note": "начальная версия"}]


def test_put_checklist_scale_with_missing_step_text_is_422(client: TestClient) -> None:
    texts = {"20": "Всё", "15": "Почти", "10": "Часть", "0": "Нет"}
    response = client.put("/api/checklist", json=draft(client, {"04": {"stepText": texts}}))

    assert response.status_code == 422
    assert response.json() == {"detail": "Критерий 04: нет текста ступени 5"}
