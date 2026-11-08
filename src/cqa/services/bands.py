"""Шкала оценок: сохранённая из интерфейса или по умолчанию (src/cqa/catalog/bands.json, с обоснованием).

Шкала — настройка, а не часть чек-листа: не входит в отпечаток смысла и переживает смену версий.
"""

from typing import Any

from cqa.adapters.store import Store
from cqa.catalog import load
from cqa.domain.tuning import Band, Bands, band_errors
from cqa.services.errors import Invalid


def bands_view(store: Store) -> dict[str, Any]:
    """GET /api/bands: `{bands, why, source: "default" | "saved", saved_at}`."""
    saved = store.bands()
    if saved is None:
        default = Bands.model_validate(load("bands.json")).model_dump(mode="json")
        return {**default, "source": "default", "saved_at": None}
    body, at = saved
    return {**body, "source": "saved", "saved_at": at}


def current_bands(store: Store) -> list[Band]:
    return [Band.model_validate(b) for b in bands_view(store)["bands"]]


def save_bands(store: Store, bands: Bands) -> dict[str, Any]:
    if errors := band_errors(bands):
        raise Invalid("; ".join(errors.values()), fields=errors)
    store.set_bands(bands.model_dump(mode="json"))
    return bands_view(store)
