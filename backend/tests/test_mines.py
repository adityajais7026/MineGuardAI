"""Mines CRUD API tests."""


def test_list_mines_seeded(client):
    r = client.get("/api/mines")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert {m["code"] for m in body["items"]} >= {"MINE-TST", "MINE-OTH"}


def test_create_get_update_delete_cycle(client):
    r = client.post("/api/mines", json={
        "name": "Cycle Mine", "code": "MINE-CYC", "mine_type": "underground",
        "status": "operational", "location": "Cycle City",
    })
    assert r.status_code == 201
    mine_id = r.json()["id"]

    r = client.get(f"/api/mines/{mine_id}")
    assert r.status_code == 200 and r.json()["code"] == "MINE-CYC"

    r = client.patch(f"/api/mines/{mine_id}", json={"status": "suspended"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"

    r = client.get(f"/api/mines/{mine_id}/details")
    assert r.status_code == 200 and "counts" in r.json()

    assert client.delete(f"/api/mines/{mine_id}").status_code == 204
    assert client.get(f"/api/mines/{mine_id}").status_code == 404


def test_duplicate_code_rejected(client):
    payload = {"name": "Dup", "code": "MINE-TST", "mine_type": "open_cast",
               "status": "operational", "location": "X"}
    r = client.post("/api/mines", json=payload)
    assert r.status_code == 400


def test_invalid_payload_422(client):
    r = client.post("/api/mines", json={"name": "", "code": "BAD CODE!", "location": ""})
    assert r.status_code == 422


def test_unknown_mine_404(client):
    assert client.get("/api/mines/nope").status_code == 404


def test_filter_by_status(client):
    r = client.get("/api/mines", params={"status": "operational"})
    assert r.status_code == 200
    assert all(m["status"] == "operational" for m in r.json()["items"])
