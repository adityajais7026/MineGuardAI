"""Phase 11 authentication + RBAC tests."""
from app.core.security import create_access_token

ADMIN = "u-admin-0001"
MANAGER = "u-mgr-0001"
SAFETY = "u-safe-0001"
ENV = "u-env-0001"


# --------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------- #
def test_protected_endpoint_requires_token(anon_client):
    r = anon_client.get("/api/mines")
    assert r.status_code == 401
    assert "detail" in r.json()


def test_all_write_endpoints_reject_anonymous(anon_client):
    assert anon_client.post("/api/mines", json={}).status_code == 401
    assert anon_client.post("/api/alerts", json={}).status_code == 401
    assert anon_client.patch("/api/alerts/x", json={}).status_code == 401
    assert anon_client.delete("/api/mines/x").status_code == 401
    assert anon_client.post("/api/compliance/ingest").status_code == 401


def test_invalid_token_rejected(anon_client):
    r = anon_client.get("/api/mines", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_token_for_unknown_user_rejected(anon_client):
    token = create_access_token(subject="no-such-user", role="admin")
    r = anon_client.get("/api/mines", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_deactivated_user_rejected(db_session, anon_client):
    user = db_session.get.__self__.query(type(db_session.get(db_session, ADMIN))).filter_by(id=ADMIN).first() \
        if False else None  # placeholder to keep linters quiet
    from app.database.models import User
    admin = db_session.query(User).filter_by(id=ADMIN).first()
    admin.is_active = False
    db_session.commit()
    token = create_access_token(subject=ADMIN, role=admin.role)
    r = anon_client.get("/api/mines", headers={"Authorization": f"Bearer {token}"})
    admin.is_active = True
    db_session.commit()
    assert r.status_code == 401


def test_role_mismatch_between_token_and_db_rejected(anon_client):
    """A token minted for role X is refused when the DB role has since changed."""
    token = create_access_token(subject=SAFETY, role="admin")  # stale/elevated token
    from app.database.models import User
    # get_current_user checks payload role against DB role only for local tokens
    r = anon_client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# --------------------------------------------------------------------- #
# Role-based write permissions (positive + negative cases)
# --------------------------------------------------------------------- #
def test_admin_can_write_everything(client):
    assert client.post("/api/mines", json={
        "name": "RBAC Mine", "code": "MINE-RBAC", "mine_type": "open_cast",
        "status": "operational", "location": "X",
    }).status_code == 201
    assert client.post("/api/compliance-rules", json={
        "name": "RBAC rule", "parameter": "rbac", "operator": ">",
        "threshold": 1, "unit": "u",
    }).status_code == 201
    assert client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "RBAC incident",
    }).status_code == 201


def test_environmental_officer_manages_rules_but_not_mines(client, as_role):
    as_role(ENV)
    r = client.post("/api/compliance-rules", json={
        "name": "Env rule", "parameter": "so2", "operator": ">",
        "threshold": 5, "unit": "ppm",
    })
    assert r.status_code == 201
    rule_id = r.json()["id"]

    # same user cannot create a mine
    r = client.post("/api/mines", json={
        "name": "No", "code": "MINE-DENY", "mine_type": "open_cast",
        "status": "operational", "location": "X",
    })
    assert r.status_code == 403

    # and cannot report an incident
    r = client.post("/api/incidents", json={"mine_id": "m-test-0001", "title": "No"})
    assert r.status_code == 403

    client.delete(f"/api/compliance-rules/{rule_id}")


def test_safety_officer_manages_incidents_not_rules(client, as_role):
    as_role(SAFETY)
    r = client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Safety incident",
    })
    assert r.status_code == 201
    incident_id = r.json()["id"]

    r = client.post("/api/compliance-rules", json={
        "name": "No", "parameter": "x", "operator": ">", "threshold": 1, "unit": "u",
    })
    assert r.status_code == 403

    r = client.post("/api/mines", json={
        "name": "No", "code": "MINE-DENY2", "mine_type": "open_cast",
        "status": "operational", "location": "X",
    })
    assert r.status_code == 403

    client.delete(f"/api/incidents/{incident_id}")


def test_mine_manager_manages_mines_not_camera_events(client, as_role):
    as_role(MANAGER)
    r = client.post("/api/mines", json={
        "name": "Manager Mine", "code": "MINE-MGR", "mine_type": "mixed",
        "status": "operational", "location": "X",
    })
    assert r.status_code == 201
    mine_id = r.json()["id"]

    r = client.post("/api/camera-events", json={
        "mine_id": "m-test-0001", "camera_id": "CAM-X",
        "event_type": "other", "confidence": 0.9,
    })
    assert r.status_code == 403

    client.delete(f"/api/mines/{mine_id}")


def test_only_admin_manages_users(client, as_role):
    as_role(SAFETY)
    r = client.post("/api/users", json={
        "email": "no@test.ai", "full_name": "No", "password": "Password!123",
    })
    assert r.status_code == 403

    as_role(ADMIN)
    r = client.post("/api/users", json={
        "email": "yes@test.ai", "full_name": "Yes", "password": "Password!123",
    })
    assert r.status_code == 201
    client.delete(f"/api/users/{r.json()['id']}")


def test_reads_still_require_auth_but_any_role(client, as_role):
    for uid in (ADMIN, MANAGER, SAFETY, ENV):
        as_role(uid)
        assert client.get("/api/mines").status_code == 200
        assert client.get("/api/dashboard/summary").status_code == 200
        assert client.get("/api/risk/mines").status_code == 200


def test_403_response_is_informative(client, as_role):
    as_role(ENV)
    r = client.post("/api/mines", json={
        "name": "X", "code": "MINE-XXX", "mine_type": "open_cast",
        "status": "operational", "location": "X",
    })
    assert r.status_code == 403
    assert "environmental_officer" in r.json()["detail"]
