import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# system event phrases of the organisers' platform ("Идентификация пройдена"), not criterion data
EXEMPT = {Path("src/cqa/domain/events.py")}


def test_source_strings_have_no_criterion_names_labels_or_keys() -> None:
    checklist = json.loads((ROOT / "tests/fixtures/checklist_v3.json").read_text(encoding="utf-8"))
    criteria = checklist["criteria"]
    literals = {c["name"] for c in criteria} | {
        q[field] for c in criteria for q in c.get("questions") or [] for field in ("label", "k")
    }
    # темы обращений и маркеры риска — тоже данные
    literals |= {p["name"] for p in json.loads((ROOT / "tests/fixtures/products.json").read_text("utf-8"))}
    literals |= {r["label"] for r in json.loads((ROOT / "tests/fixtures/risks.json").read_text("utf-8"))}
    pattern = re.compile("|".join(rf"(?<!\w){re.escape(s)}(?!\w)" for s in literals))
    hits = [
        f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}"
        for path in sorted((ROOT / "src/cqa").rglob("*.py"))
        if path.relative_to(ROOT) not in EXEMPT
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.search(node.value)
    ]
    assert hits == []
