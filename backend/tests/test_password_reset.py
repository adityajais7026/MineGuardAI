"""Administrator password reset, forced password change and session revocation.

These tests exercise the REAL auth dependency (the shared `client` fixture
overrides `get_current_user`): after switching to `real_auth`, every request
carries an actual bearer token, so JWT session generations, the
temporary-password gate, deactivated/deleted accounts and audit logging are all
verified end to end.
"""
from datetime import datetime, timezone

import pytest

from app.core.security import get_current_user
from app.database import models
from app.main import app
from app.services.governance.audit_chain import compute_hash

USERS = "/api/users"
AUTH = "/api/auth"

_email_seq = iter(range(700, 799))


def _next_email() -> str:
    return f"pwreset-{next(_email_seq)}@test.ai"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def real_auth(db_session):
    """Temporarily remove the auth override so tokens are validated for real.

    Returns (enable, restore). `client` is an administrator for admin-only
    calls; `anon_client` is used for login/token calls while enabled.
    """

    def _db_override():
        yield db_session

    def enable():
        # get_db override stays (set by the client fixtures); only the auth
        # shortcut is removed, so bearer tokens are validated for real.
        app.dependency_overrides.pop(get_current_user, None)

    def restore():
        admin = db_session.get(models.User, "u-admin-0001")
        app.dependency_overrides[get_current_user] = lambda: admin

    yield enable, restore
    admin = db_session.get(models.User, "u-admin-0001")
    app.dependency_overrides[get_current_user] = lambda: admin


def _create_user(client, *, email=None, password="Initial@12345", role="safety_officer") -> dict:
    email = email or _next_email()
    r = client.post(USERS, json={
        "email": email, "full_name": "Password Tester", "role": role, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _login(anon_client, email: str, password: str):
    return anon_client.post(f"{AUTH}/login", data={"username": email, "password": password})


# ---------------------------------------------------------------- #
# 1. Administrator reset -> temporary password + forced change
# ---------------------------------------------------------------- #
def test_admin_reset_issues_temporary_password_and_forces_change(client, anon_client, db_session, real_auth):
    created = _create_user(client)
    user_id, email = created["id"], created["email"]

    # New accounts created with an administrator-chosen password are temporary;
    # clear the flag to model a normal registered account with its own password.
    user = db_session.get(models.User, user_id)
    user.must_change_password = False
    db_session.commit()

    enable, restore = real_auth
    enable()
    try:
        login = _login(anon_client, email, "Initial@12345")
        assert login.status_code == 200, login.text
        old_token = login.json()["access_token"]
        assert anon_client.get("/api/mines", headers=_auth(old_token)).status_code == 200
    finally:
        restore()

    reset = client.post(f"{USERS}/{user_id}/password-reset")
    assert reset.status_code == 200, reset.text
    body = reset.json()
    temp = body["temporary_password"]
    assert len(temp) >= 16
    assert body["must_change_password"] is True
    assert body["sessions_revoked"] is True
    # The temporary password must never appear in the user representation.
    assert temp not in client.get(USERS).text

    enable, restore = real_auth
    enable()
    try:
        # 1) Every previously issued token is dead.
        assert anon_client.get("/api/mines", headers=_auth(old_token)).status_code == 401
        # 2) The old password no longer authenticates.
        assert _login(anon_client, email, "Initial@12345").status_code == 401
        # 3) The temporary password works...
        fresh = _login(anon_client, email, temp)
        assert fresh.status_code == 200, fresh.text
        payload = fresh.json()
        assert payload["user"]["must_change_password"] is True
        temp_token = payload["access_token"]

        # 4) ...but only for the change-password screen and own profile.
        assert anon_client.get("/api/auth/me", headers=_auth(temp_token)).status_code == 200
        blocked = anon_client.get("/api/mines", headers=_auth(temp_token))
        assert blocked.status_code == 403
        assert blocked.headers.get("X-Password-Change-Required") == "true"

        # 5) A wrong current password cannot clear the flag.
        bad = anon_client.post(f"{AUTH}/change-password", headers=_auth(temp_token), json={
            "current_password": "not-the-temp-one", "new_password": "BrandNew@12345",
        })
        assert bad.status_code == 400
        assert anon_client.get("/api/mines", headers=_auth(temp_token)).status_code == 403

        # 6) The owner sets their own password: flag clears, a new session starts.
        changed = anon_client.post(f"{AUTH}/change-password", headers=_auth(temp_token), json={
            "current_password": temp, "new_password": "BrandNew@12345",
        })
        assert changed.status_code == 200, changed.text
        assert changed.json()["user"]["must_change_password"] is False
        new_token = changed.json()["access_token"]
        assert anon_client.get("/api/mines", headers=_auth(new_token)).status_code == 200
        # The temporary-password session is superseded by the new generation.
        assert anon_client.get("/api/mines", headers=_auth(temp_token)).status_code == 401
        # The temporary password itself no longer authenticates.
        assert _login(anon_client, email, temp).status_code == 401
        # The chosen password does.
        assert _login(anon_client, email, "BrandNew@12345").status_code == 200
    finally:
        restore()


def test_change_password_rejects_short_and_reused_passwords(client, anon_client, db_session, real_auth):
    created = _create_user(client, password="Original@1234")
    user = db_session.get(models.User, created["id"])
    user.must_change_password = False
    db_session.commit()

    enable, restore = real_auth
    enable()
    try:
        token = _login(anon_client, created["email"], "Original@1234").json()["access_token"]
        short = anon_client.post(f"{AUTH}/change-password", headers=_auth(token), json={
            "current_password": "Original@1234", "new_password": "short",
        })
        assert short.status_code == 422 or short.status_code == 400
        same = anon_client.post(f"{AUTH}/change-password", headers=_auth(token), json={
            "current_password": "Original@1234", "new_password": "Original@1234",
        })
        assert same.status_code == 400
        # The original session is untouched by the rejected attempts.
        assert anon_client.get("/api/mines", headers=_auth(token)).status_code == 200
    finally:
        restore()


def test_non_admin_cannot_reset_passwords(client, as_role):
    created = _create_user(client)
    as_role("u-safe-0001")
    r = client.post(f"{USERS}/{created['id']}/password-reset")
    assert r.status_code == 403


def test_reset_unknown_user_404(client):
    assert client.post(f"{USERS}/no-such-user/password-reset").status_code == 404


# ---------------------------------------------------------------- #
# 2. Audit trail for credential events
# ---------------------------------------------------------------- #
def test_reset_and_change_are_written_to_the_audit_chain(client, anon_client, db_session, real_auth):
    created = _create_user(client)
    user = db_session.get(models.User, created["id"])
    user.must_change_password = False
    db_session.commit()

    reset = client.post(f"{USERS}/{created['id']}/password-reset")
    temp = reset.json()["temporary_password"]

    enable, restore = real_auth
    enable()
    try:
        token = _login(anon_client, created["email"], temp).json()["access_token"]
        assert anon_client.post(f"{AUTH}/change-password", headers=_auth(token), json={
            "current_password": temp, "new_password": "OwnerChoice@123",
        }).status_code == 200
    finally:
        restore()

    events = client.get("/api/governance/audit", params={"limit": 200}).json()
    actions = [e["action"] for e in events]
    assert "user.password_reset" in actions
    assert "user.password_change" in actions

    reset_event = next(e for e in events if e["action"] == "user.password_reset")
    assert reset_event["entity_id"] == created["id"]
    # The actor snapshot survives even if the account is later deleted.
    assert reset_event["payload_json"]["_actor"]["email"] == "admin@test.ai"
    # The temporary password is never part of the audit record.
    assert temp not in str(reset_event)

    changed_event = next(e for e in events if e["action"] == "user.password_change")
    assert changed_event["payload_json"]["from_temporary_password"] is True
    # Integrity of THESE rows, verified the way the chain verifier does it.
    # (A global verify_chain() assertion is not usable here: test_governance
    # deliberately tampers with an old row to prove detection works, so the
    # shared chain is expected to be broken by the time this runs.)
    for event in (reset_event, changed_event):
        fields = {
            "seq": event["seq"], "actor_id": event["actor_id"],
            "actor_role": event["actor_role"], "action": event["action"],
            "entity_type": event["entity_type"], "entity_id": event["entity_id"],
            "mine_id": event["mine_id"], "payload": event["payload_json"],
        }
        assert compute_hash(event["prev_hash"], fields) == event["event_hash"]


# ---------------------------------------------------------------- #
# 3. Deactivation and permanent deletion
# ---------------------------------------------------------------- #
def test_deactivation_revokes_existing_sessions(client, anon_client, db_session, real_auth):
    created = _create_user(client)
    user = db_session.get(models.User, created["id"])
    user.must_change_password = False
    db_session.commit()

    enable, restore = real_auth
    enable()
    try:
        token = _login(anon_client, created["email"], "Initial@12345").json()["access_token"]
        assert anon_client.get("/api/mines", headers=_auth(token)).status_code == 200
    finally:
        restore()

    assert client.patch(f"{USERS}/{created['id']}", json={"is_active": False}).status_code == 200

    enable, restore = real_auth
    enable()
    try:
        assert anon_client.get("/api/mines", headers=_auth(token)).status_code == 401
        assert _login(anon_client, created["email"], "Initial@12345").status_code == 403
    finally:
        restore()


def test_permanent_delete_preserves_history_and_is_audited(client, anon_client, db_session, real_auth):
    created = _create_user(client)
    user_id, email = created["id"], created["email"]

    # History attached to the account: an inspection they led and an incident
    # they reported. Both must survive the deletion, de-attributed.
    mine_id = "m-test-0001"
    db_session.add_all([
        models.Inspection(
            id="insp-delete-0001", mine_id=mine_id, inspector_id=user_id,
            inspection_type="safety", status="completed",
            scheduled_at=datetime.now(timezone.utc), compliance_result="compliant",
        ),
        models.Incident(
            id="inc-delete-0001", mine_id=mine_id, reported_by_id=user_id,
            title="Historical incident", category="other", severity="low",
            occurred_at=datetime.now(timezone.utc),
        ),
    ])
    db_session.commit()

    report = client.delete(f"{USERS}/{user_id}/permanent")
    assert report.status_code == 200, report.text
    assert report.json()["deleted"]["user"] == 1

    db_session.expire_all()
    assert db_session.get(models.User, user_id) is None
    kept_inspection = db_session.get(models.Inspection, "insp-delete-0001")
    kept_incident = db_session.get(models.Incident, "inc-delete-0001")
    assert kept_inspection is not None and kept_inspection.inspector_id is None
    assert kept_incident is not None and kept_incident.reported_by_id is None

    # The deletion is on the audit chain with the target's identity snapshot.
    events = client.get("/api/governance/audit", params={"limit": 200}).json()
    delete_event = next(e for e in events if e["action"] == "user.delete_permanent")
    assert delete_event["entity_id"] == user_id
    assert delete_event["payload_json"]["email"] == email
    # The deletion did not rewrite any hashed row it should not have: the new
    # event's own hash recomputes correctly from its stored previous hash.
    fields = {
        "seq": delete_event["seq"], "actor_id": delete_event["actor_id"],
        "actor_role": delete_event["actor_role"], "action": delete_event["action"],
        "entity_type": delete_event["entity_type"], "entity_id": delete_event["entity_id"],
        "mine_id": delete_event["mine_id"], "payload": delete_event["payload_json"],
    }
    assert compute_hash(delete_event["prev_hash"], fields) == delete_event["event_hash"]

    # A deleted account cannot authenticate, even with the old password.
    enable, restore = real_auth
    enable()
    try:
        assert _login(anon_client, email, "Initial@12345").status_code == 401
    finally:
        restore()
