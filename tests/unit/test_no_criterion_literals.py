import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_source_strings_have_no_criterion_names_labels_or_keys() -> None:
    checklist = json.loads((ROOT / "tests/fixtures/checklist_v3.json").read_text(encoding="utf-8"))
    criteria = checklist["criteria"]
    literals = {c["name"] for c in criteria} | {
        q[field] for c in criteria for q in c.get("questions") or [] for field in ("label", "k")
    }
    pattern = re.compile("|".join(rf"(?<!\w){re.escape(s)}(?!\w)" for s in literals))
    hits = [
        f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}"
        for path in sorted((ROOT / "src/cqa").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.search(node.value)
    ]
    assert hits == []
