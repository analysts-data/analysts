"""Библиотека шаблонов критериев и готовые чек-листы: данные проходят правила сохранения."""

import pytest

from cqa.domain.models import Checklist, Criterion
from cqa.services.checklists import checklist_presets, criteria_templates, draft_errors
from fakes import prototype_checklist


def as_checklist(criteria: list[dict[str, object]]) -> Checklist:
    return Checklist(
        version=1,
        rules="",
        sections=["Раздел"],
        criteria=[Criterion.model_validate({**c, "id": f"t{i}", "sec": 0}) for i, c in enumerate(criteria)],
    )


def test_templates_are_12_to_20_criteria_with_why_tags_section_and_weight() -> None:
    templates = criteria_templates(None)["templates"]

    assert 12 <= len(templates) <= 20
    assert len({t["key"] for t in templates}) == len(templates)
    for t in templates:
        assert t["why"].strip() and t["section"].strip() and t["tags"], t["key"]
        assert t["criterion"]["w"] > 0 and t["criterion"]["type"] in ("bool", "scale"), t["key"]
        assert "id" not in t["criterion"] and "sec" not in t["criterion"], t["key"]


def test_templates_pass_the_save_rules() -> None:
    """Канал звонка или чата ⇒ N/A с условием, у шкалы тексты всех ступеней."""
    templates = criteria_templates(None)["templates"]

    assert draft_errors(as_checklist([t["criterion"] for t in templates])) == {}
    for t in templates:
        c = t["criterion"]
        assert not c.get("na") or c.get("naCond"), t["key"]


def test_templates_do_not_repeat_the_official_criteria() -> None:
    official = prototype_checklist().criteria
    templates = criteria_templates(None)["templates"]

    assert not {c.name for c in official} & {t["criterion"]["name"] for t in templates}
    assert not {c.text for c in official} & {t["criterion"]["text"] for t in templates}


@pytest.mark.parametrize("tag", ["продажи", "комплаенс", "эмпатия", "звонки"])
def test_templates_filter_by_tag(tag: str) -> None:
    every = criteria_templates(None)
    some = criteria_templates(tag)

    assert tag in every["tags"]
    assert some["templates"] and all(tag in t["tags"] for t in some["templates"])
    assert len(some["templates"]) < len(every["templates"])
    assert some["tags"] == every["tags"]


def test_call_only_templates_are_tagged_calls() -> None:
    for t in criteria_templates(None)["templates"]:
        assert (t["criterion"].get("channel") == "call") <= ("звонки" in t["tags"]), t["key"]


def test_presets_start_with_the_official_checklist() -> None:
    presets = checklist_presets()

    assert presets[0]["official"] is True
    assert Checklist.model_validate(presets[0]["checklist"]) == prototype_checklist()
    assert 3 <= len(presets) <= 4
    assert len({p["key"] for p in presets}) == len(presets)


def test_every_preset_passes_the_save_rules_with_weights_summing_to_100() -> None:
    for p in checklist_presets():
        cl = Checklist.model_validate(p["checklist"])
        assert p["name"].strip() and p["description"].strip(), p["key"]
        assert draft_errors(cl) == {}, p["key"]
        assert sum(c.w for c in cl.criteria if c.type != "flag") == 100, p["key"]
        assert p["criteria"] == len(cl.criteria)
