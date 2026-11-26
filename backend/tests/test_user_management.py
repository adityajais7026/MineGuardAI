"""Invitation-code registration + permanent deletion tests.

Registration is INVITATION-CODE ONLY: every new account needs a valid code
(admin-minted via POST /users/invite) strictly bound to one email, verified
mobile via the EXISTING MSG91 register-purpose OTP flow, and a password. The
invitation is the source of truth for email/full_name/role (no client role
selection). Covers code visibility for the creator, exact error messages,
the public validate endpoint, regeneration (old code invalidated), soft
delete (code invalid immediately), single-use atomicity, and the
Administrator-only permanent delete suite.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.database import models
from app.services import invitations as invitation_service
from app.services import msg91

BASE = "/api/auth"
UM = "/api/users"

# The fixed code accepted when SMS delivery is disabled (tests/dev only).
TEST_CODE = msg91.TEST_OTP_CODE

_email_seq = iter(range(400, 499))
_mobile_seq = iter(range(30000, 39999))


def _unique_email(prefix: str = "invited") -> str:
    return f"{prefix}-{next(_email_seq)}@test.ai"


def _unique_mobile() -> str:
    return f"9189{next(_mobile_seq):08d}"


def _invite(client, **overrides):
    """Mint an invitation as the admin; returns (payload, response)."""
    payload = {
        "role": "mine_manager",
        "full_name": "Invited Person",
        "email": _unique_email(),
        **overrides,
    }
    return payload, client.post(f"{UM}/invite", json=payload)


def _register(client, code: str, email: str, password: str = "Sup3rSecret!x", *, mobile: str | None = None, otp: str = TEST_CODE, **complete_overrides):
    """Drive the full registration flow: OTP start -> verify -> complete.

    Returns the final /register/complete response, or the failing
    start/verify response if the OTP steps do not succeed.
    """
    mobile = mobile or _unique_mobile()
    r = client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    if r.status_code != 200:
        return r
    verify = client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": otp})
    if verify.status_code != 200:
        return verify
    body = {
        "token": verify.json()["token"],
        "email": email,
        "invitation_code": code,
        "password": password,
    }
    body.update(complete_overrides)
    return client.post(f"{BASE}/register/complete", json=body)


@pytest.fixture(autouse=True)
def _disable_sms_delivery(monkeypatch):
    """Registration verifies mobile via the real MSG91 OTP flow; in tests the
    delivery is disabled so the fixed dev/test code works (no SMS spend)."""
    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", True)


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
# 1. Minting invitation codes (admin)
# ------------------------------------------------------------------ #
def test_admin_can_create_invitation_and_get_code(client):
    payload, r = _invite(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == payload["role"]
    assert body["email"] == payload["email"]
    assert body["full_name"] == payload["full_name"]
    # Human-usable code: three XXXX groups, no ambiguous characters.
    code = body["code"]
    assert len(code) >= 11 and code.count("-") == 2
    assert "0" not in code and "O" not in code and "1" not in code and "I" not in code


def test_invitation_code_stays_visible_in_management_list(client):
    """The code must NOT become hidden after creation: the creator can keep
    copying it from the list until the invitation is used/expired/deleted."""
    payload, r = _invite(client)
    code = r.json()["code"]
    items = client.get(f"{UM}/invitations").json()["items"]
    row = [i for i in items if i["email"] == payload["email"]][0]
    assert row["code"] == code  # plaintext, not a hash
    assert row["status"] == "Active"


def test_invitation_form_carries_no_password_and_no_mobile(client):
    payload, r = _invite(client)
    assert r.status_code == 201
    body = r.json()
    assert "password" not in body and "mobile" not in body
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


def test_invitation_code_is_stored_hashed_but_kept_for_creator(client, db_session):
    """Store the code securely: bcrypt hash is the credential; the plaintext
    copy exists only so the creator can display/copy the code again."""
    payload, r = _invite(client)
    code = r.json()["code"]
    stored = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
    assert stored is not None
    assert code not in (stored.code_hash or "")
    assert verify_password(code, stored.code_hash)
    assert stored.code == code  # creator-visible plaintext copy


# ------------------------------------------------------------------ #
# 2. Registration with a code (public) — code + email -> OTP -> password
# ------------------------------------------------------------------ #
def test_validate_endpoint_returns_invitation_role(client):
    payload, r = _invite(client, role="environmental_officer", full_name="Gov Officer")
    code = r.json()["code"]
    v = client.get(f"{BASE}/invitations/validate", params={"code": code, "email": payload["email"]})
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["role"] == "environmental_officer"
    assert body["full_name"] == "Gov Officer"


def test_validate_unknown_code_rejected_with_exact_message(client):
    v = client.get(f"{BASE}/invitations/validate",
                   params={"code": "AAAA-BBBB-CCCC", "email": _unique_email()})
    assert v.status_code == 403
    assert v.json()["detail"] == invitation_service.MSG_INVALID_CODE


def test_validate_wrong_email_rejected_with_exact_message(client):
    payload, r = _invite(client)
    code = r.json()["code"]
    v = client.get(f"{BASE}/invitations/validate",
                   params={"code": code, "email": "another@example.com"})
    assert v.status_code == 403
    assert v.json()["detail"] == invitation_service.MSG_WRONG_EMAIL


def test_register_requires_invitation_code(client):
    """NO PUBLIC REGISTRATION: without a code nothing is created."""
    _, r = _invite(client)
    mob = _unique_mobile()
    assert client.post(f"{BASE}/register/otp/start", json={"mobile": mob}).status_code == 200
    verify = client.post(f"{BASE}/register/otp/verify", json={"mobile": mob, "otp": TEST_CODE})
    resp = client.post(f"{BASE}/register/complete", json={
        "token": verify.json()["token"], "email": _unique_email(), "password": "Password1!",
    })
    assert resp.status_code == 400
    assert resp.json()["detail"] == invitation_service.MSG_CODE_REQUIRED
    # No invitation existed, so no account could be created either way.


def test_register_with_invalid_code_rejected(client, db_session):
    email = _unique_email()
    resp = _register(client, "AAAA-BBBB-CCCC", email)
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_INVALID_CODE
    assert db_session.query(models.User).filter_by(email=email).first() is None


def test_register_with_wrong_email_rejected_and_not_consumed(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    other_email = _unique_email("other")
    resp = _register(client, code, other_email)
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_WRONG_EMAIL
    assert db_session.query(models.User).filter_by(email=other_email).first() is None
    inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
    assert inv.is_used is False  # mismatch never consumes the invitation


def test_register_creates_account_with_invitation_role_and_verified_mobile(client, db_session):
    payload, r = _invite(client, role="environmental_officer", full_name="Gov Officer")
    code = r.json()["code"]
    mob = _unique_mobile()
    resp = _register(client, code, payload["email"], password="MyOwnPassword1!", mobile=mob)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["role"] == "environmental_officer"  # invitation decides
    assert body["user"]["email"] == payload["email"]
    assert body["access_token"]

    user = db_session.query(models.User).filter_by(email=payload["email"]).first()
    assert user is not None
    assert user.full_name == "Gov Officer"  # from the invitation, not the client
    assert user.is_active is True
    assert user.mobile == msg91.normalize_mobile(mob)  # MSG91-verified, mandatory
    assert verify_password("MyOwnPassword1!", user.hashed_password)


def test_register_ignores_client_role_and_name_fields(client):
    """The invitation is the source of truth: role/full_name in the payload
    cannot override or select anything."""
    payload, r = _invite(client, role="safety_officer", full_name="Real Name")
    code = r.json()["code"]
    resp = _register(client, code, payload["email"], role="admin", full_name="Hacker")
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "safety_officer"
    assert resp.json()["user"]["full_name"] == "Real Name"


def test_register_email_match_is_case_insensitive(client):
    """The email is strictly tied to the invitation; address comparison is
    case-insensitive (a different address is rejected — see the wrong-email
    test — but capitalisation is not an identity change)."""
    payload, r = _invite(client, email="person@example.com")
    code = r.json()["code"]
    resp = _register(client, code, "Person@Example.COM")
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "person@example.com"


def test_register_accepts_code_with_surrounding_spaces_and_lowercase(client):
    """Codes are case-insensitive and tolerate surrounding whitespace, but the
    displayed XXXX-XXXX-XXXX format (with dashes) is required."""
    payload, r = _invite(client)
    code = r.json()["code"]
    resp = _register(client, f"  {code.lower()}  ", payload["email"])
    assert resp.status_code == 200, resp.text


def test_register_rejects_code_missing_dashes(client):
    """A mangled code (dashes removed) is simply an invalid code."""
    payload, r = _invite(client)
    code = r.json()["code"]
    resp = _register(client, code.replace("-", ""), payload["email"])
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_INVALID_CODE


def test_register_without_verified_mobile_rejected(client):
    """No OTP verification -> no pending-registration token -> no account."""
    payload, r = _invite(client)
    code = r.json()["code"]
    resp = client.post(f"{BASE}/register/complete", json={
        "token": "x" * 40, "email": payload["email"],
        "invitation_code": code, "password": "Password1!",
    })
    assert resp.status_code == 401  # reg token invalid -> start OTP again
    assert client.get(f"{BASE}/invitations/validate",
                      params={"code": code, "email": payload["email"]}).status_code == 200


def test_register_wrong_otp_never_creates_account(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    mob = _unique_mobile()
    assert client.post(f"{BASE}/register/otp/start", json={"mobile": mob}).status_code == 200
    wrong = client.post(f"{BASE}/register/otp/verify", json={"mobile": mob, "otp": "000000"})
    assert wrong.status_code == 401
    assert db_session.query(models.User).filter_by(email=payload["email"]).first() is None
    # Invitation still usable with a fresh mobile + correct OTP.
    assert _register(client, code, payload["email"]).status_code == 200


def test_register_rejects_reused_code(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    assert _register(client, code, payload["email"]).status_code == 200
    second = _unique_email("second")
    resp = _register(client, code, second)
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_ALREADY_USED
    assert db_session.query(models.User).filter_by(email=second).first() is None


def test_register_rejects_expired_code_with_exact_message(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
    inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    resp = _register(client, code, payload["email"])
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_EXPIRED


def test_register_rejects_deleted_code_with_exact_message(client):
    payload, r = _invite(client)
    code = r.json()["code"]
    inv_id = r.json()["id"]
    assert client.delete(f"{UM}/invitations/{inv_id}").status_code == 200
    resp = _register(client, code, payload["email"])
    assert resp.status_code == 403
    assert resp.json()["detail"] == invitation_service.MSG_DELETED


def test_register_fails_cleanly_when_email_taken(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    db_session.add(models.User(
        id="u-email-snatch", email=payload["email"], full_name="Snatch",
        role="safety_officer", hashed_password="x",
    ))
    db_session.commit()
    try:
        resp = _register(client, code, payload["email"])
        assert resp.status_code == 409
        inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
        assert inv.is_used is False  # consumption rolled back with the failure
    finally:
        db_session.rollback()


def test_register_rejects_already_registered_mobile(client, db_session):
    """The register-purpose mobile-uniqueness check is inherited from the
    existing OTP service: starting the OTP for a taken mobile is a 409."""
    taken = _unique_mobile()
    owner = models.User(id="u-mob-owner", email=_unique_email("mobowner"), full_name="Owner",
                        role="safety_officer", mobile=taken, hashed_password="x")
    db_session.add(owner)
    db_session.commit()
    try:
        payload, r = _invite(client)
        code = r.json()["code"]
        resp = _register(client, code, payload["email"], mobile=taken)
        assert resp.status_code == 409
        inv = db_session.query(models.RoleInvitation).filter_by(bound_email=payload["email"]).first()
        assert inv.is_used is False  # nothing consumed on the failed start
    finally:
        db_session.rollback()
        db_session.delete(owner)
        db_session.commit()


def test_register_otp_inherits_resend_cooldown(client):
    """Reusing the existing register-purpose policy: an immediate re-send hits
    the same cooldown the OTP flow always enforced."""
    _, r = _invite(client)
    mob = _unique_mobile()
    assert client.post(f"{BASE}/register/otp/start", json={"mobile": mob}).status_code == 200
    again = client.post(f"{BASE}/register/otp/start", json={"mobile": mob})
    assert again.status_code == 429
    assert "Retry-After" in again.headers


def test_registered_account_can_login_with_own_password(client):
    payload, r = _invite(client)
    code = r.json()["code"]
    body = _register(client, code, payload["email"], password="LoginWorks99!").json()
    login = client.post(f"{BASE}/login", data={"username": body["user"]["email"], "password": "LoginWorks99!"})
    assert login.status_code == 200
    assert login.json()["access_token"]


# ------------------------------------------------------------------ #
# 3. Invitation management: status, regenerate, delete
# ------------------------------------------------------------------ #
def test_invitation_listing_statuses(client, db_session):
    _, r1 = _invite(client, email="listing-active@test.ai")
    _, r2 = _invite(client, email="listing-used@test.ai")
    assert _register(client, r2.json()["code"], "listing-used@test.ai").status_code == 200
    _, r3 = _invite(client, email="listing-expired@test.ai")
    inv = db_session.query(models.RoleInvitation).filter_by(bound_email="listing-expired@test.ai").first()
    inv.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()
    _, r4 = _invite(client, email="listing-deleted@test.ai")
    client.delete(f"{UM}/invitations/{r4.json()['id']}")

    items = {i["email"]: i for i in client.get(f"{UM}/invitations").json()["items"]}
    assert items["listing-active@test.ai"]["status"] == "Active"
    assert items["listing-used@test.ai"]["status"] == "Used"
    assert items["listing-expired@test.ai"]["status"] == "Expired"
    assert items["listing-deleted@test.ai"]["status"] == "Deleted"


def test_invitation_listing_shows_code_created_by_and_timestamps(client):
    payload, r = _invite(client)
    code = r.json()["code"]
    row = [i for i in client.get(f"{UM}/invitations").json()["items"]
           if i["email"] == payload["email"]][0]
    assert row["code"] == code
    assert row["created_by"] == "admin@test.ai"
    assert row["created_at"] and row["expires_at"]


def test_invitation_listing_is_admin_only(client, as_role):
    as_role("u-safe-0001")
    assert client.get(f"{UM}/invitations").status_code == 403


def test_regenerate_issues_new_code_for_same_email_and_role(client, db_session):
    payload, r = _invite(client, role="safety_officer")
    old_code = r.json()["code"]
    inv_id = r.json()["id"]

    reg = client.post(f"{UM}/invitations/{inv_id}/regenerate")
    assert reg.status_code == 200, reg.text
    new = reg.json()
    assert new["code"] != old_code
    assert new["email"] == payload["email"]  # email unchanged
    assert new["role"] == "safety_officer"   # role unchanged

    # The previous code is invalidated immediately.
    v_old = client.get(f"{BASE}/invitations/validate",
                       params={"code": old_code, "email": payload["email"]})
    assert v_old.status_code == 403
    assert v_old.json()["detail"] == invitation_service.MSG_INVALID_CODE
    # The new code validates and registers.
    assert client.get(f"{BASE}/invitations/validate",
                      params={"code": new["code"], "email": payload["email"]}).status_code == 200
    stored = db_session.query(models.RoleInvitation).get(inv_id)
    assert stored.code == new["code"]
    assert verify_password(new["code"], stored.code_hash)


def test_regenerate_replaces_stored_code_so_old_one_cannot_register(client):
    payload, r = _invite(client)
    old_code = r.json()["code"]
    inv_id = r.json()["id"]
    new_code = client.post(f"{UM}/invitations/{inv_id}/regenerate").json()["code"]
    assert _register(client, old_code, payload["email"]).status_code == 403
    assert _register(client, new_code, payload["email"]).status_code == 200


def test_regenerate_renews_expiry(client, db_session):
    _, r = _invite(client)
    inv_id = r.json()["id"]
    inv = db_session.query(models.RoleInvitation).get(inv_id)
    old_expiry = inv.expires_at
    reg = client.post(f"{UM}/invitations/{inv_id}/regenerate")
    db_session.expire_all()
    inv = db_session.query(models.RoleInvitation).get(inv_id)
    assert reg.status_code == 200
    assert inv.expires_at > old_expiry


def test_non_admin_cannot_regenerate_or_delete(client, as_role):
    _, r = _invite(client)
    inv_id = r.json()["id"]
    as_role("u-safe-0001")
    assert client.post(f"{UM}/invitations/{inv_id}/regenerate").status_code == 403
    assert client.delete(f"{UM}/invitations/{inv_id}").status_code == 403


def test_another_admin_can_regenerate_someone_elses_invitation(client, as_role, db_session):
    """Any current Administrator may manage invitations (creator OR admin)."""
    _, r = _invite(client)
    inv_id = r.json()["id"]
    other_admin = models.User(
        id="u-admin-0002", email=_unique_email("admin2"), full_name="Admin Two",
        role="admin", hashed_password="x",
    )
    db_session.add(other_admin)
    db_session.commit()
    try:
        as_role("u-admin-0002")
        assert client.post(f"{UM}/invitations/{inv_id}/regenerate").status_code == 200
    finally:
        db_session.rollback()
        db_session.delete(other_admin)
        db_session.commit()


def test_regenerate_used_invitation_conflict(client):
    _, r = _invite(client)
    inv_id, code = r.json()["id"], r.json()["code"]
    email = r.json()["email"]
    assert _register(client, code, email).status_code == 200
    assert client.post(f"{UM}/invitations/{inv_id}/regenerate").status_code == 409


def test_regenerate_after_delete_conflict(client):
    _, r = _invite(client)
    inv_id = r.json()["id"]
    client.delete(f"{UM}/invitations/{inv_id}")
    assert client.post(f"{UM}/invitations/{inv_id}/regenerate").status_code == 409


def test_regenerate_unknown_invitation_404(client):
    assert client.post(f"{UM}/invitations/no-such-id/regenerate").status_code == 404
    assert client.delete(f"{UM}/invitations/no-such-id").status_code == 404


def test_delete_invalidates_code_immediately(client, db_session):
    payload, r = _invite(client)
    code = r.json()["code"]
    inv_id = r.json()["id"]
    del_resp = client.delete(f"{UM}/invitations/{inv_id}")
    assert del_resp.status_code == 200
    assert "no longer valid" in del_resp.json()["detail"].lower() or "deleted" in del_resp.json()["detail"].lower()

    # Validation and registration both fail with the deleted message.
    v = client.get(f"{BASE}/invitations/validate", params={"code": code, "email": payload["email"]})
    assert v.status_code == 403
    assert v.json()["detail"] == invitation_service.MSG_DELETED
    assert _register(client, code, payload["email"]).status_code == 403

    # Row kept for audit with deleted_at stamped.
    inv = db_session.query(models.RoleInvitation).get(inv_id)
    assert inv.deleted_at is not None


def test_delete_is_rejected_once_already_deleted(client):
    _, r = _invite(client)
    inv_id = r.json()["id"]
    assert client.delete(f"{UM}/invitations/{inv_id}").status_code == 200
    assert client.delete(f"{UM}/invitations/{inv_id}").status_code == 409


# ------------------------------------------------------------------ #
# 4. Permanent deletion (unchanged behaviour, re-verified)
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
    victim = _make_deleteable_user(db_session, id="u-inviter-0001", email="inviter@test.ai", role="admin")
    # The victim (an admin) minted two invitations: one pending, one used.
    p_inv = models.RoleInvitation(
        role="safety_officer", code_hash="hash", code="PEND-CODE-0001",
        full_name="P", bound_email="p@test.ai", invited_by_id=victim.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    u_inv = models.RoleInvitation(
        role="safety_officer", code_hash="hash", code="USED-CODE-0001",
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
