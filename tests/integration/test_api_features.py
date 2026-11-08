from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.settings import Settings


def test_config_lists_features_of_mounted_routers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(Settings(db_path=str(tmp_path / "f.db")))
    features = TestClient(app).get("/api/config").json()["features"]
    assert {"employees", "audit"} <= set(features)  # роутер #84 вложен, раньше не находился
    assert "docs" not in features or "/docs/" in {getattr(r, "path", "") for r in app.routes}
