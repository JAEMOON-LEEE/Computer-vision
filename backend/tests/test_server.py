from sqlalchemy.exc import OperationalError


def test_dashboard_and_database_readiness(client):
    assert client.get("/").url.path == "/dashboard/"
    assert client.get("/dashboard/").status_code == 200
    assert client.get("/dashboard/config.js").status_code == 200
    assert client.get("/ready").json() == {"status": "ok", "database": "connected"}
    assert client.get("/dashboard/.env").status_code == 404


def test_readiness_failure_does_not_disclose_connection(client):
    from backend.app.main import app
    from backend.app.db import get_db

    class BrokenDB:
        def execute(self, _):
            raise OperationalError("secret-connection", {}, Exception("password"))

    app.dependency_overrides[get_db] = lambda: BrokenDB()
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
    finally:
        app.dependency_overrides.pop(get_db, None)
