"""Отчёты по замерам: качество оценки (make eval) и запуск оценки. Данные синтетические."""

from dataclasses import asdict
from typing import Any

from cqa.domain.agreement import Thresholds
from cqa.domain.models import CriterionResult
from cqa.domain.reports import quality_checks, quality_doc, run_doc, run_report
from cqa.domain.tables import to_csv, to_html, to_markdown
from fakes import MODEL_REASON as REASON
from fakes import eval_report_body as eval_body

THRESHOLDS = Thresholds(
    gross_recall_min=1.0,
    kz_gap_max_pts=5,
    na_precision_min=0.9,
    na_recall_min=0.9,
    stability_min=0.95,
    evidence_ok_min=0.92,
    holdout_agreement_min=0.85,
    baseline_drop_max_pts=3,
)


def test_thresholds_are_checked_against_the_measured_values() -> None:
    checks = {c["name"]: c for c in quality_checks(eval_body(), THRESHOLDS)}

    assert (checks["gross_recall_min"]["value"], checks["gross_recall_min"]["ok"]) == (0.5, False)
    assert (checks["kz_gap_max_pts"]["value"], checks["kz_gap_max_pts"]["ok"]) == (7.0, False)
    assert checks["stability_min"]["ok"] is True
    assert checks["na_precision_min"]["ok"] is True
    assert (checks["na_recall_min"]["value"], checks["na_recall_min"]["ok"]) == (None, None)
    assert checks["baseline_drop_max_pts"]["ok"] is None  # без лучшего прогона значения нет
    assert len(checks) == len(asdict(THRESHOLDS))


def test_quality_document_lists_disagreements_without_model_reasons() -> None:
    d = quality_doc(eval_body(), THRESHOLDS, names={"c2": "Синтетический критерий"}, meta="Прогон 1")
    titles = [t.title for t in d.tables]
    rows = {t.title: t.rows for t in d.tables}

    assert "Расхождения с эталоном" in titles and "Пороги" in titles
    assert ["dlg-1", "c2 Синтетический критерий", "да", "нет"] in rows["Расхождения с эталоном"]
    assert ["dlg-2", "c3", "k2", "нет ответа"] in rows["Расхождения с эталоном"]
    assert ["RU", "0,92"] in rows["Совпадение по языкам"]
    for text in (to_html(d), to_markdown(d), to_csv(d)):
        assert REASON not in text and "синтетическая цитата" not in text


def test_quality_document_shows_threshold_verdicts_and_run_problems() -> None:
    rows = {t.title: t.rows for t in quality_doc(eval_body(), THRESHOLDS, names={}, meta="").tables}

    verdicts = {r[0]: r[3] for r in rows["Пороги"]}
    assert "не пройден" in verdicts.values() and "пройден" in verdicts.values()
    assert "нет данных" in verdicts.values()
    assert ["замечание"] in rows["Замечания прогона"]


def result(a: Any, model: str = "model-x") -> CriterionResult:
    return CriterionResult(a=a, model=model)


RUN = {
    "id": 7,
    "total": 6,
    "done": 3,
    "cost": 0.004,
    "calls": 3,
    "errors": ["dlg-9: timeout"],
    "status": "running",
    "started": 1_762_560_000.0,
    "finished": None,
}


def test_run_report_counts_answers_per_criterion() -> None:
    results = [
        ("c1", 3, result("yes")),
        ("c1", 3, result("no")),
        ("c1", 3, result("yes", "model-y")),
        ("c2", 3, result({"k1": True, "k2": False})),
    ]

    rep = run_report(RUN, results, names={"c1": "Первый"})

    assert (rep["progress"], rep["models"], rep["checklist_versions"]) == (0.5, ["model-x", "model-y"], [3])
    assert rep["criteria"] == [
        {"cid": "c1", "name": "Первый", "n": 3, "answers": {"yes": 2, "no": 1}},
        {"cid": "c2", "name": None, "n": 1, "answers": {"k1": 1}},
    ]


def test_run_document_shows_progress_errors_and_distribution() -> None:
    rep = run_report(RUN, [("c1", 3, result("na"))], names={})
    rows = {t.title: t.rows for t in run_doc(rep).tables}

    assert ["Оценено пар", "3 из 6 (50 %)"] in rows["Сводка"]
    assert ["dlg-9: timeout"] in rows["Ошибки"]
    assert ["c1", "1", "N/A 1"] in rows["Ответы по критериям"]
