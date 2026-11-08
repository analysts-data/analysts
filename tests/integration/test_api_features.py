from fastapi.testclient import TestClient

from cqa.http.api import FEATURES, _paths
from cqa.http.app import create_app
from cqa.settings import Settings


def test_config_lists_only_features_whose_routes_exist(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(Settings(db_path=str(tmp_path / "f.db")))
    body = TestClient(app).get("/api/config").json()
    paths = _paths(app.routes)
    assert body["features"] == [k for k, p in FEATURES.items() if p in paths or p.rstrip("/") in paths]
    assert "sources" in body["features"]  # путь включённого роутера, а не только app.routes
    assert "batches" not in body["features"]  # маршрута нет — раздела нет
