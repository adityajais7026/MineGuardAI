"""Health endpoint tests."""


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "MineGuardAI API"


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_health_db(client):
    body = client.get("/api/health/db").json()
    assert body["connected"] is True
    assert body["status"] == "ok"
