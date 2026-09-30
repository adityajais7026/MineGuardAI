"""Invitation-based user management (link invitations + permanent deletion).

Covers the "Invite User" flow (admin mints Full Name/Email/Role only, no
password, no mobile), the public accept flow (own password, role fixed
server-side, single-use, expiry, replay), the Administrator-only permanent
delete (guards: non-admin, self, last-admin; email/mobile freed; pending
invitations revoked; demo rows untouched) and the impact scan.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import create_access_token, hash_password, verify_password
from app.database import models

BASE = "/api/auth"
UM = "/api/users"
INV = "/api/invitations"


_email_seq = iter(range(300, 399))


def _unique_email(prefix: str = "invited") -> str:
    return f"{prefix}-{next(_email_seq)}@test.ai"


def _invite(client, **overrides):
    payload = {
        "role": "mine_manager",
        "full_name": "Invited Person",
        "email": _unique_email(),
        **overrides,
    }
    return payload, client.post(f"{UM}/invite", json=payload)


def _accept(client, token: str, password: str = "Sup3rSecret!x", **overrides):
    body = {"password": password, "confirm_password": overrides.pop("confirm_password", password)}
    body.update(overrides)
    return client.post(f"{INV}/accept/{token}", json=body)


@pytest.fixture(autouse=True)
def _clean_session_state(db_session):
    """Roll back before/after every test in this module.

    The suite shares one session-scoped DB and session; a failed flush
    anywhere (this module deliberately triggers IntegrityError-adjacent
    guards) must never poison later tests.
    """
    db_session.rollback()
    yield
    db_session.rollback()


# ------------------------------------------------------------------ #
# 1. Invite User (replaces Add User)
# ------------------------------------------------------------------ #
def test_admin_can_create_invitation_and_get_link(client):
    payload, r = _invite(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == payload["role"]
    assert body["invited_email"] == payload["email"]
    assert body["invited_name"] == payload["full_name"]
    assert body["invitation_url"].startswith("/accept-invitation/")
    assert len(body["token"]) >= 20


def test_invitation_form_carries_no_password_and_no_mobile(client):
    payload, r = _invite(client)
    assert r.status_code == 201
    body = r.json()
    assert "password" not in body and "mobile" not in body
    # The stored invitation must not carry a mobile either.
    inv = client.get(f"{UM}/invitations").json()["items"]
    mine_inv = [i for i in inv if i["email"] == payload["email"]][0]
    assert "mobile" not in mine_inv


def test_invite_rejects_duplicate_email(client, db_session):
    payload, r = _invite(client, email="admin@test.ai")
    assert r.status_code == 409


def test_invite_rejects_invalid_email(client):
    _, r = _invite(client, email="not-an-email")
    assert r.status_code == 422


def test_non_admin_cannot_create_invitations(client, as_role):
    as_role("u-safe-0001")
    _, r = _invite(client)
    assert r.status_code == 403


def test_anonymous_cannot_create_invitations(anon_client):
    r = anon_client.post(f"{UM}/invite", json={
        "role": "safety_officer", "full_name": "X", "email": "x@test.ai",
    })
    assert r.status_code == 401


def test_invitation_token_is_never_stored_in_plaintext(client, db_session):
    payload, r = _invite(client)
    token = r.json()["token"]
    stored = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
    assert stored is not None
    assert token not in (stored.token_hash or "") and token not in (stored.code_hash or "")
    assert verify_password(token, stored.token_hash)


# ------------------------------------------------------------------ #
# 2. Accept flow
# ------------------------------------------------------------------ #
def test_valid_invitation_opens_and_shows_details(client):
    payload, r = _invite(client)
    token = r.json()["token"]
    v = client.get(f"{INV}/accept/{token}")
    assert v.status_code == 200
    body = v.json()
    assert body["email"] == payload["email"]
    assert body["full_name"] == payload["full_name"]
    assert body["role"] == payload["role"]


def test_unknown_token_is_rejected(client):
    r = client.get(f"{INV}/accept/not-a-real-token-value")
    assert r.status_code == 404
    assert "expired" in r.json()["detail"].lower()


def test_used_invitation_is_rejected_for_view_and_accept(client):
    _, r = _invite(client)
    token = r.json()["token"]
    assert _accept(client, token).status_code == 200
    # Replay: view and accept must both fail now.
    assert client.get(f"{INV}/accept/{token}").status_code == 404
    assert _accept(client, token).status_code == 404


def test_expired_invitation_is_rejected(client, db_session):
    payload, r = _invite(client)
    token = r.json()["token"]
    inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
    inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    assert client.get(f"{INV}/accept/{token}").status_code == 404
    assert _accept(client, token).status_code == 404


def test_accept_creates_account_with_own_password_and_correct_role(client, db_session):
    payload, r = _invite(client, role="environmental_officer", full_name="Gov Officer")
    token = r.json()["token"]
    resp = _accept(client, token, password="MyOwnPassword1!")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["role"] == "environmental_officer"
    assert body["user"]["email"] == payload["email"]
    assert body["access_token"]

    user = db_session.query(models.User).filter_by(email=payload["email"]).first()
    assert user is not None
    assert user.role == "environmental_officer"
    assert user.is_active is True
    assert user.mobile is None  # link invitations never touch MSG91
    assert verify_password("MyOwnPassword1!", user.hashed_password)


def test_accept_login_works_with_new_password(client):
    _, r = _invite(client)
    token = r.json()["token"]
    body = _accept(client, token, password="LoginWorks99!").json()
    email = body["user"]["email"]
    login = client.post(f"{BASE}/login", data={"username": email, "password": "LoginWorks99!"})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_invited_user_cannot_change_role_via_payload(client, db_session):
    _, r = _invite(client, role="safety_officer")
    token = r.json()["token"]
    # Attempt to self-elevate by injecting fields into the accept payload.
    resp = _accept(client, token, role="admin", full_name="Hacker", email="admin@test.ai")
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "safety_officer"  # server-side authority
    assert resp.json()["user"]["email"] != "admin@test.ai"


def test_accept_password_mismatch_rejected(client):
    _, r = _invite(client)
    token = r.json()["token"]
    resp = _accept(client, token, password="Password1!", confirm_password="Password2!")
    assert resp.status_code == 422
    # Invitation must remain usable after the failed attempt.
    assert client.get(f"{INV}/accept/{token}").status_code == 200


def test_accept_rejects_short_password(client):
    _, r = _invite(client)
    token = r.json()["token"]
    resp = _accept(client, token, password="short")
    assert resp.status_code == 422


def test_accept_fails_cleanly_when_email_taken(client, db_session):
    payload, r = _invite(client)
    token = r.json()["token"]
    # Someone registers the email between invite and accept.
    db_session.add(models.User(
        id="u-email-snatch", email=payload["email"], full_name="Snatch",
        role="safety_officer", hashed_password="x",
    ))
    db_session.commit()
    try:
        resp = _accept(client, token)
        assert resp.status_code == 409
        inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
        assert inv.is_used is False  # consumption rolled back with the failure
    finally:
        db_session.rollback()


def test_expired_invitation_message(client):
    _, r = _invite(client)
    token = r.json()["token"]
    # Burn it, then check the generic message required by the spec.
    assert _accept(client, token).status_code == 200
    resp = _accept(client, token)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "This invitation is expired or has already been used."


# ------------------------------------------------------------------ #
# 3. Invitation listing (Pending / Accepted / Expired)
# ------------------------------------------------------------------ #
def test_invitation_listing_statuses(client, db_session):
    _, r1 = _invite(client, email="listing-pending@test.ai")
    _, r2 = _invite(client, email="listing-accept@test.ai")
    assert _accept(client, r2.json()["token"]).status_code == 200
    _, r3 = _invite(client, email="listing-expired@test.ai")
    inv = db_session.query(models.RoleInvitation).filter_by(bound_email="listing-expired@test.ai").first()
    inv.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    items = {i["email"]: i["status"] for i in client.get(f"{UM}/invitations").json()["items"]}
    assert items["listing-pending@test.ai"] == "Pending"
    assert items["listing-accept@test.ai"] == "Accepted"
    assert items["listing-expired@test.ai"] == "Expired"


def test_invitation_listing_is_admin_only(client, as_role):
    as_role("u-safe-0001")
    assert client.get(f"{UM}/invitations").status_code == 403


# ------------------------------------------------------------------ #
# 4. Permanent deletion
# ------------------------------------------------------------------ #
def _make_deleteable_user(db_session, **kwargs) -> models.User:
    user = models.User(
        id=kwargs.pop("id", None),
        email=kwargs.pop("email", _unique_email("victim")),
        full_name=kwargs.pop("full_name", "Victim"),
        role=kwargs.pop("role", "safety_officer"),
        hashed_password=kwargs.pop("hashed_password", hash_password("Password!123")),
        **kwargs,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_admin_can_permanently_delete_eligible_user(client, db_session):
    victim = _make_deleteable_user(db_session)
    r = client.delete(f"{UM}/{victim.id}/permanent")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detail"] == "User permanently deleted."
    assert body["deleted"]["user"] == 1
    assert db_session.get(models.User, victim.id) is None


def test_deleted_user_email_becomes_reusable(client, db_session):
    victim = _make_deleteable_user(db_session, email="reuse-me@test.ai", mobile="918000000001")
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 200
    # Email can be registered again (uniqueness is gone).
    reborn = models.User(
        email="reuse-me@test.ai", full_name="Reborn", role="safety_officer",
        mobile="918000000001", hashed_password="x",
    )
    db_session.add(reborn)
    db_session.commit()
    db_session.refresh(reborn)
    assert reborn.id


def test_non_admin_cannot_permanently_delete(client, as_role, db_session):
    victim = _make_deleteable_user(db_session)
    as_role("u-safe-0001")
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 403
    as_role("u-mgr-0001")
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 403
    as_role("u-env-0001")
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 403
    as_role("u-admin-0001")
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 200


def test_admin_cannot_delete_themselves(client, db_session):
    r = client.delete(f"{UM}/u-admin-0001/permanent")
    assert r.status_code == 400
    assert "your own" in r.json()["detail"].lower()
    assert db_session.get(models.User, "u-admin-0001") is not None


def test_last_admin_cannot_be_deleted(client, db_session):
    """A non-self admin target who is the last ACTIVE admin is protected.

    Hermetic against other tests' leftover admin accounts: every OTHER active
    admin is deactivated first (and restored afterwards).
    """
    target = _make_deleteable_user(
        db_session, id="u-admin-target", email=_unique_email("last-admin"), role="admin"
    )
    others = db_session.query(models.User).filter(
        models.User.role == "admin", models.User.is_active.is_(True), models.User.id != target.id
    ).all()
    assert others, "scenario requires at least one other active admin"
    original_states = [(u.id, u.is_active) for u in others]
    try:
        for u in others:
            u.is_active = False
        db_session.commit()

        r = client.delete(f"{UM}/{target.id}/permanent")
        assert r.status_code == 400
        assert "last active administrator" in r.json()["detail"].lower()
        assert db_session.get(models.User, target.id) is not None
    finally:
        for uid, state in original_states:
            restored = db_session.get(models.User, uid)
            restored.is_active = state
        db_session.commit()
    # With the other admins active again, the target is deletable.
    assert client.delete(f"{UM}/{target.id}/permanent").status_code == 200


def test_demo_accounts_survive_admin_deletion_of_other_users(client, db_session):
    victim = _make_deleteable_user(db_session)
    client.delete(f"{UM}/{victim.id}/permanent")
    for uid in ("u-admin-0001", "u-mgr-0001", "u-safe-0001", "u-env-0001"):
        assert db_session.get(models.User, uid) is not None


def test_delete_revokes_pending_invitations_but_keeps_used_ones(client, db_session):
    admin = db_session.get(models.User, "u-admin-0001")
    victim = _make_deleteable_user(db_session, id="u-inviter-0001", email="inviter@test.ai", role="admin")
    # The victim (an admin) minted two link invitations: one pending, one used.
    p_inv = models.RoleInvitation(
        role="safety_officer", code_hash="hash", token_hash="hash",
        full_name="P", bound_email="p@test.ai", invited_by_id=victim.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    u_inv = models.RoleInvitation(
        role="safety_officer", code_hash="hash", token_hash="hash",
        full_name="U", bound_email="u@test.ai", invited_by_id=victim.id,
        is_used=True, used_by_id="u-safe-0001", used_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db_session.add_all([p_inv, u_inv])
    db_session.commit()
    pending_id, used_id = p_inv.id, u_inv.id

    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 200
    assert db_session.get(models.RoleInvitation, pending_id) is None   # revoked
    assert db_session.get(models.RoleInvitation, used_id) is not None  # audit kept


def test_delete_detaches_shared_records_instead_of_destroying(client, db_session):
    victim = _make_deleteable_user(db_session, id="u-reporter-0001", email="reporter@test.ai")
    incident = models.Incident(
        mine_id="m-test-0001", reported_by_id=victim.id, title="Survives",
        category="other", severity="low", status="open",
    )
    alert = models.Alert(
        mine_id="m-test-0001", alert_type="safety", title="Assigned alert",
        severity="low", source="manual", status="new", assigned_to_id=victim.id,
    )
    db_session.add_all([incident, alert])
    db_session.commit()
    incident_id, alert_id = incident.id, alert.id

    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 200
    db_session.expire_all()  # bulk DELETE/SET NULL bypasses the identity map
    assert db_session.get(models.Incident, incident_id) is not None
    assert db_session.get(models.Alert, alert_id) is not None
    assert db_session.get(models.Incident, incident_id).reported_by_id is None
    assert db_session.get(models.Alert, alert_id).assigned_to_id is None


def test_delete_reports_impact(client, db_session):
    victim = _make_deleteable_user(db_session)
    r = client.get(f"{UM}/{victim.id}/impact")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == victim.id
    assert body["email"] == victim.email
    assert body["role"] == victim.role
    assert "affected" in body
    r = client.delete(f"{UM}/{victim.id}/permanent")
    assert r.status_code == 200
    assert "detached" in r.json()


def test_impact_and_delete_unknown_user_404(client):
    assert client.get(f"{UM}/no-such-user/impact").status_code == 404
    assert client.delete(f"{UM}/no-such-user/permanent").status_code == 404


def test_impact_is_admin_only(client, as_role, db_session):
    victim = _make_deleteable_user(db_session)
    as_role("u-safe-0001")
    assert client.get(f"{UM}/{victim.id}/impact").status_code == 403


def test_deleted_user_cannot_authenticate(client, db_session):
    """A deleted user's JWT stops working (auth resolves the DB row)."""
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token as _cat, get_current_user
    from app.main import app

    victim = _make_deleteable_user(db_session, email="gone@test.ai")
    victim_headers = {"Authorization": f"Bearer {_cat(subject=victim.id, role=victim.role)}"}
    admin_headers = {"Authorization": f"Bearer {_cat(subject='u-admin-0001', role='admin')}"}

    # Drop the fixture's auth override so these requests perform REAL token
    # auth against the shared test DB (get_db override stays active).
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app) as fresh:
            assert fresh.get("/api/auth/me", headers=victim_headers).status_code == 200  # alive
            assert fresh.delete(f"{UM}/{victim.id}/permanent", headers=admin_headers).status_code == 200
            db_session.expire_all()
            assert fresh.get("/api/auth/me", headers=victim_headers).status_code == 401  # deleted
    finally:
        admin = db_session.get(models.User, "u-admin-0001")
        app.dependency_overrides[get_current_user] = lambda: admin


def test_soft_delete_deactivate_still_works(client, db_session):
    victim = _make_deleteable_user(db_session)
    r = client.patch(f"/api/users/{victim.id}", json={"is_active": False})
    assert r.status_code == 200
    assert db_session.get(models.User, victim.id).is_active is False
    # ...and the row is still there (soft-delete untouched by the new feature).
    assert client.delete(f"{UM}/{victim.id}/permanent").status_code == 200
