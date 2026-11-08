"""GET /api/scores/export: оценки для Excel из текущего состояния, строка на диалог или на пару."""

import csv
import io

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from cqa.domain.review import fingerprint
from fakes import prototype_checklist


def evaluate(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c, dialog.ch), dialog.res[c.id])


def table(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.removeprefix("﻿")), delimiter=";"))


def test_wide_export_is_a_csv_attachment_named_by_checklist_version(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])  # call-024; p1-ru-003 не оценён

    response = client.get("/api/scores/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="cqa-scores-v3.csv"'
    assert response.text.startswith("﻿ID;Название;")
    head, *rows = table(response.text)
    names = [c.name for c in prototype_checklist().criteria]
    assert head[-len(names) :] == names
    row = {r[0]: dict(zip(head, r, strict=True)) for r in rows}
    assert (row["call-024"]["Итог"], row["call-024"]["Канал"]) == ("82,94", "Звонок")
    assert (row["p1-ru-003"]["Итог"], row["p1-ru-003"][names[0]]) == ("", "ждёт оценки")


def test_long_export_has_a_row_per_evaluated_pair_and_filters(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])

    head, *rows = table(client.get("/api/scores/export?format=csv&shape=long").text)
    chats = table(client.get("/api/scores/export?shape=long&ch=chat").text)

    assert head[:4] == ["ID диалога", "ID критерия", "Критерий", "Ответ"]
    assert [r[1] for r in rows] == [c.id for c in prototype_checklist().criteria]
    assert {r[0] for r in rows} == {"call-024"}
    assert chats[1:] == []


def test_unknown_format_shape_or_channel_is_422(client: TestClient) -> None:
    assert client.get("/api/scores/export?format=xlsx").status_code == 422
    assert client.get("/api/scores/export?shape=tall").status_code == 422
    assert client.get("/api/scores/export?ch=fax").status_code == 422
