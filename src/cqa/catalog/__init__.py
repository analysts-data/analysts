"""Каталог данных продукта: шкала оценок по умолчанию, шаблоны критериев, готовые чек-листы (JSON рядом)."""

import json
from pathlib import Path
from typing import Any


def load(name: str) -> Any:
    return json.loads((Path(__file__).parent / name).read_text(encoding="utf-8"))
