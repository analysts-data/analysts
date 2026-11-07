"""make eval: два прогона оценщика по эталону, метрики, пороги и лучший прогон (eval-and-delivery)."""

from dataclasses import fields

import yaml

from cqa.domain.agreement import Thresholds


def load_thresholds(text: str) -> Thresholds:
    """Пороги из eval/thresholds.yaml; неизвестный или пропущенный ключ — ValueError."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("thresholds.yaml: ожидается словарь порогов")
    names = {f.name for f in fields(Thresholds)}
    if unknown := sorted(set(data) - names):
        raise ValueError(f"thresholds.yaml: неизвестные пороги {', '.join(unknown)}")
    if missing := sorted(names - set(data)):
        raise ValueError(f"thresholds.yaml: нет порогов {', '.join(missing)}")
    return Thresholds(**{k: float(v) for k, v in data.items()})
