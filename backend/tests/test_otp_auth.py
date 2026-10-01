"""MSG91 OTP Widget auth flow tests.

No real SMS is sent (OTP_SMS_DISABLED=True via fixture) and no network call
happens: the widget provider skips delivery in that mode and accepts the fixed
dev/test code (msg91.TEST_OTP_CODE). The full server-side flow (challenge
lifecycle, attempts, expiry, cooldowns, rate caps) is exercised without any
provider dependency. Provider-contract tests stub httpx to verify the exact
widget API request shape. The test DB is session-scoped, so every test uses a
fresh mobile/email and per-test rows are cleaned up.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.security import decode_token, hash_password
from app.database import models
from app.services import invitations as invitation_service
from app.services import msg91

BASE = "/api/auth"

_mobile_gen = iter(range(80000, 89999))


def _unique_mobile() -> str:
    return f"9177{next(_mobile_gen):08d}"


# The fixed code accepted when SMS delivery is disabled (tests/dev only).
TEST_CODE = msg91.TEST_OTP_CODE


@pytest.fixture()
def mobile():
    return _unique_mobile()


@pytest.fixture()
def sms_client(anon_client, monkeypatch):
    """Anonymous client with SMS delivery disabled (no MSG91 spend, no network)."""
    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", True)
    return anon_client


@pytest.fixture()
def otp_capture():
    """In widget mode the code is fixed: a compatibility shim for the shared
    helpers so the flow-driving code stays identical across provider modes."""

    class _FixedCode:
        def last(self) -> str:
            return TEST_CODE

    return _FixedCode()


def _start_and_verify(sms_client, otp_capture, mob, purpose="register"):
    """Drive send + verify; returns the endpoint response for the verify step."""
    r = sms_client.post(f"{BASE}/{purpose}/otp/start", json={"mobile": mob})
    assert r.status_code == 200, r.text
    code = otp_capture.last()
    return sms_client.post(f"{BASE}/{purpose}/otp/verify", json={"mobile": mob, "otp": code})


def _invite_code(client, role: str, email: str, full_name: str = "OTP User") -> str:
    """Mint an invitation code as the admin (registration is code-only)."""
    r = client.post("/api/users/invite", json={"role": role, "full_name": full_name, "email": email})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _register_payload(sms_client, otp_capture, mob, code, email=None):
    """Final-step payload: OTP-verified token + invitation code (mandatory)."""
    r = _start_and_verify(sms_client, otp_capture, mob)
    assert r.status_code == 200, r.text
    return {
        "token": r.json()["token"],
        "email": email or f"user-{mob[-4:]}@test.ai",
        "invitation_code": code,
        "password": "Password!123",
    }


def _latest_challenge(db_session, mob, purpose="register"):
    return (
        db_session.query(models.OtpChallenge)
        .filter_by(subject=msg91.normalize_mobile(mob), purpose=purpose)
        .order_by(models.OtpChallenge.created_at.desc(), models.OtpChallenge.id.desc())
        .first()
    )


# ------------------------------------------------------------------ #
# 1. Send OTP
# ------------------------------------------------------------------ #
def test_register_send_otp_returns_masked_mobile(sms_client, otp_capture, mobile):
    r = sms_client.post(f"{BASE}/register/otp/start", json={"mobile": f"+91 {mobile[2:]}"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"mobile_masked", "cooldown_seconds", "expires_in_minutes"}
    assert "*" in body["mobile_masked"] and mobile not in body["mobile_masked"]
    assert body["cooldown_seconds"] > 0 and body["expires_in_minutes"] > 0


def test_register_send_otp_rejects_already_registered_mobile(sms_client, db_session, mobile):
    dup = models.User(id="u-otp-dup", email="dup@test.ai", full_name="Dup",
                      role="safety_officer", mobile=mobile, hashed_password="x")
    db_session.add(dup)
    db_session.commit()
    try:
        r = sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
        assert r.status_code == 409
    finally:
        db_session.rollback()
        db_session.delete(dup)
        db_session.commit()


def test_register_send_otp_rejects_garbage_mobile(sms_client):
    r = sms_client.post(f"{BASE}/register/otp/start", json={"mobile": "not-a-phone"})
    assert r.status_code == 400


# ------------------------------------------------------------------ #
# 2. Verify OTP + 3. Registration
# ------------------------------------------------------------------ #
def test_register_verify_returns_single_use_pending_token(sms_client, otp_capture, mobile):
    r = _start_and_verify(sms_client, otp_capture, mobile)
    assert r.status_code == 200
    payload = decode_token(r.json()["token"])
    assert payload["sub"] == msg91.normalize_mobile(mobile)
    assert payload["typ"] == "prp"  # pending-registration, NOT a login token


def test_register_complete_creates_active_inspector_and_issues_jwt(sms_client, client, db_session, otp_capture, mobile):
    email = f"inspector-{mobile[-4:]}@test.ai"
    code = _invite_code(client, "safety_officer", email)
    payload = _register_payload(sms_client, otp_capture, mobile, code, email=email)
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["user"]["role"] == "safety_officer"  # from the invitation
    assert body["user"]["is_active"] is True
    assert body["user"]["mobile"] == msg91.normalize_mobile(mobile)

    # The JWT is a normal MineGuardAI token with the invitation's role.
    claims = decode_token(body["access_token"])
    assert claims["role"] == "safety_officer" and claims["iss"] == "mineguardai"

    user = db_session.query(models.User).filter_by(email=payload["email"]).first()
    assert user is not None and user.hashed_password.startswith("$2")


def test_register_complete_rejects_reused_token(sms_client, client, otp_capture, mobile):
    email = f"reuse-{mobile[-4:]}@test.ai"
    code = _invite_code(client, "safety_officer", email)
    payload = _register_payload(sms_client, otp_capture, mobile, code, email=email)
    r1 = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r1.status_code == 200
    # A second completion (same token or same code) cannot create anything.
    r2 = sms_client.post(f"{BASE}/register/complete", json={**payload, "email": "second@test.ai"})
    assert r2.status_code in (400, 401, 403, 409)


def test_register_duplicate_email_rejected(sms_client, client, db_session, otp_capture, mobile):
    email = f"dup-{mobile[-4:]}@test.ai"
    code = _invite_code(client, "safety_officer", email)
    payload = _register_payload(sms_client, otp_capture, mobile, code, email=email)
    clash = models.User(id="u-otp-clash", email=email, full_name="Clash",
                        role="mine_manager", hashed_password="x")
    db_session.add(clash)
    db_session.commit()
    try:
        r = sms_client.post(f"{BASE}/register/complete", json=payload)
        assert r.status_code == 409
    finally:
        db_session.rollback()
        db_session.delete(clash)
        db_session.commit()


def test_wrong_otp_burns_an_attempt_then_succeeds_with_right_one(sms_client, otp_capture, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    code = otp_capture.last()
    r = sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": "000000"})
    assert r.status_code == 401
    r = sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": code})
    assert r.status_code == 200  # still within attempt limit


# ------------------------------------------------------------------ #
# MSG91 OTP Widget provider contract (no network: httpx.post is stubbed)
# ------------------------------------------------------------------ #
class _StubResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"type": "success", "message": "req-1"}

    def json(self):
        return self._body


def test_send_otp_widget_uses_default_sms_configuration(monkeypatch):
    """Widget send contract: authkey header, widgetId+identifier body, and NO
    template_id anywhere — the widget's default SMS config delivers the OTP."""
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _StubResponse(200, {"type": "success", "message": "request-id-abc"})

    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", False)
    monkeypatch.setattr(settings, "MSG91_AUTHKEY", "test-authkey-not-real")
    monkeypatch.setattr(settings, "MSG91_WIDGET_ID", "test-widget-id")
    monkeypatch.setattr(msg91.httpx, "post", fake_post)

    request_id = msg91.send_otp_widget("919999999999")

    assert request_id == "request-id-abc"
    assert captured["url"].endswith("/api/v5/widget/sendOtp")
    assert captured["json"] == {"widgetId": "test-widget-id", "identifier": "919999999999"}
    assert captured["headers"]["authkey"] == "test-authkey-not-real"
    assert "template" not in str(captured["json"]).lower()


def test_verify_otp_widget_sends_reqid_and_otp(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _StubResponse(200, {"type": "success", "message": "<jwt>"})

    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", False)
    monkeypatch.setattr(settings, "MSG91_AUTHKEY", "test-authkey-not-real")
    monkeypatch.setattr(settings, "MSG91_WIDGET_ID", "test-widget-id")
    monkeypatch.setattr(msg91.httpx, "post", fake_post)

    assert msg91.verify_otp_widget("request-id-abc", "1234") is True
    assert captured["url"].endswith("/api/v5/widget/verifyOtp")
    assert captured["json"] == {"widgetId": "test-widget-id", "reqId": "request-id-abc", "otp": "1234"}


def test_verify_otp_widget_wrong_code_returns_false(monkeypatch):
    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", False)
    monkeypatch.setattr(settings, "MSG91_AUTHKEY", "test-authkey-not-real")
    monkeypatch.setattr(settings, "MSG91_WIDGET_ID", "test-widget-id")
    monkeypatch.setattr(
        msg91.httpx, "post",
        lambda *a, **k: _StubResponse(200, {"type": "error", "message": "OTP verified failed"}),
    )

    assert msg91.verify_otp_widget("request-id-abc", "9999") is False


def test_send_otp_widget_200_error_body_is_failure(monkeypatch):
    """MSG91 quirk: request-level errors can arrive with HTTP 200."""
    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", False)
    monkeypatch.setattr(settings, "MSG91_AUTHKEY", "test-authkey-not-real")
    monkeypatch.setattr(settings, "MSG91_WIDGET_ID", "test-widget-id")
    monkeypatch.setattr(
        msg91.httpx, "post",
        lambda *a, **k: _StubResponse(200, {"type": "error", "message": "Invalid widget id"}),
    )

    with pytest.raises(msg91.Msg91Error, match="rejected"):
        msg91.send_otp_widget("919999999999")


def test_send_otp_widget_fails_closed_without_widget_id(monkeypatch):
    def fake_post(*a, **k):
        raise AssertionError("HTTP request must not be attempted without config")

    monkeypatch.setattr(settings, "OTP_SMS_DISABLED", False)
    monkeypatch.setattr(settings, "MSG91_AUTHKEY", "test-authkey-not-real")
    monkeypatch.setattr(settings, "MSG91_WIDGET_ID", "")
    monkeypatch.setattr(msg91.httpx, "post", fake_post)

    with pytest.raises(msg91.Msg91Error):
        msg91.send_otp_widget("919999999999")


# ------------------------------------------------------------------ #
# 4. Login OTP
# ------------------------------------------------------------------ #
@pytest.fixture()
def otp_user(db_session):
    """Existing user WITH a verified mobile (so OTP login applies)."""
    db_session.rollback()
    user = models.User(id="u-otp-login", email="otpuser@test.ai", full_name="OTP Login",
                       role="mine_manager", mobile="917700000003", hashed_password="x")
    user.hashed_password = hash_password("Secret@123")
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.rollback()
    db_session.delete(user)
    db_session.commit()


def test_login_otp_flow_issues_same_jwt(sms_client, otp_capture, otp_user):
    email = "otpuser@test.ai"
    r = sms_client.post(f"{BASE}/login/otp/start", json={"email": email, "password": "Secret@123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["otp_required"] is True and "*" in body["mobile_masked"]

    r = sms_client.post(f"{BASE}/login/otp/verify", json={"email": email, "otp": TEST_CODE})
    assert r.status_code == 200
    claims = decode_token(r.json()["access_token"])
    assert claims["sub"] == "u-otp-login"
    assert claims["iss"] == "mineguardai"
    assert claims["role"] == "mine_manager"


def test_login_otp_start_rejects_wrong_password(sms_client, otp_user):
    r = sms_client.post(f"{BASE}/login/otp/start",
                        json={"email": "otpuser@test.ai", "password": "wrong"})
    assert r.status_code == 401


def test_login_otp_verify_wrong_code_is_401(sms_client, otp_user):
    email = "otpuser@test.ai"
    r = sms_client.post(f"{BASE}/login/otp/start", json={"email": email, "password": "Secret@123"})
    assert r.status_code == 200
    r = sms_client.post(f"{BASE}/login/otp/verify", json={"email": email, "otp": "000000"})
    assert r.status_code == 401


def test_login_without_mobile_skips_otp(sms_client, db_session):
    """Accounts without a registered mobile answer otp_required=False."""
    db_session.rollback()
    user = models.User(id="u-nomobile", email="nomobile@test.ai", full_name="NoMo",
                       role="safety_officer", hashed_password=hash_password("NoMo@12345"))
    db_session.add(user)
    db_session.commit()
    try:
        r = sms_client.post(f"{BASE}/login/otp/start",
                            json={"email": "nomobile@test.ai", "password": "NoMo@12345"})
        assert r.status_code == 200
        assert r.json()["otp_required"] is False
    finally:
        db_session.rollback()
        db_session.delete(user)
        db_session.commit()


# ------------------------------------------------------------------ #
# 5. Invalid / expired OTP
# ------------------------------------------------------------------ #
def test_verify_without_active_challenge_is_410(sms_client, mobile):
    r = sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": "123456"})
    assert r.status_code == 410


def test_expired_otp_is_410(sms_client, db_session, otp_capture, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    code = otp_capture.last()
    ch = _latest_challenge(db_session, mobile)
    ch.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    r = sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": code})
    assert r.status_code == 410
    # The dev/test code must now be useless even with a fresh challenge off.
    assert code == TEST_CODE


def test_attempts_exhausted_locks_challenge(sms_client, db_session, otp_capture, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    otp_capture.last()  # real code discarded — we brute-force wrong codes
    responses = [
        sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": "000000"})
        for _ in range(settings.MSG91_OTP_MAX_ATTEMPTS + 1)
    ]
    # Wrong entries return 401 until attempts run out (403, challenge locked);
    # any further verify finds no active challenge (410).
    assert responses[-2].status_code == 403
    assert responses[-1].status_code == 410
    ch = _latest_challenge(db_session, mobile)
    assert ch.consumed_at is not None


# ------------------------------------------------------------------ #
# 6. Resend / rate limiting
# ------------------------------------------------------------------ #
def test_resend_inside_cooldown_is_429(sms_client, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    r = sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_hourly_send_cap_is_enforced(sms_client, db_session, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    ch = _latest_challenge(db_session, mobile)
    # Simulate 6 sends within the last hour (cap = 6), outside the cooldown.
    ch.request_count = 6
    ch.last_sent_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS + 5)
    db_session.commit()
    r = sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    assert r.status_code == 429


# ------------------------------------------------------------------ #
# 7. Registration policy (INVITATION-CODE ONLY)
# ------------------------------------------------------------------ #
def test_registration_without_code_is_rejected_with_exact_message(sms_client, otp_capture, mobile):
    """NO PUBLIC REGISTRATION: every role requires a valid invitation code."""
    payload = _register_payload(sms_client, otp_capture, mobile, code=None)
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 400
    assert r.json()["detail"] == invitation_service.MSG_CODE_REQUIRED


def test_registration_with_invalid_code_is_rejected(sms_client, otp_capture, mobile):
    email = f"nocode-{mobile[-4:]}@test.ai"
    payload = _register_payload(sms_client, otp_capture, mobile, code="AAAA-BBBB-CCCC", email=email)
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 403
    assert r.json()["detail"] == invitation_service.MSG_INVALID_CODE


def test_registration_with_wrong_email_for_code_is_rejected(sms_client, client, otp_capture, mobile):
    """The code is strictly bound to its email — no swapping identities."""
    code = _invite_code(client, "environmental_officer", "gov-bound@test.ai")
    payload = _register_payload(sms_client, otp_capture, mobile, code, email="another@test.ai")
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 403
    assert r.json()["detail"] == invitation_service.MSG_WRONG_EMAIL


def test_invitation_grants_its_minted_role(sms_client, client, otp_capture):
    """A Government Officer invitation creates an active environmental_officer
    even though no role is ever selectable in the payload."""
    code = _invite_code(client, "environmental_officer", "gov-invited@test.ai")
    payload = _register_payload(sms_client, otp_capture, _unique_mobile(), code,
                                email="gov-invited@test.ai")
    resp = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["role"] == "environmental_officer"
    assert body["user"]["is_active"] is True
    assert body["access_token"]


def test_admin_registration_with_valid_invitation_succeeds(sms_client, client, db_session, otp_capture, mobile):
    email = f"admin-new-{mobile[-4:]}@test.ai"
    code = _invite_code(client, "admin", email)
    payload = _register_payload(sms_client, otp_capture, mobile, code, email=email)
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"


def test_invitation_is_single_use(sms_client, client, otp_capture):
    email1, email2 = "admin2@test.ai", "admin3@test.ai"
    code = _invite_code(client, "admin", email1)
    payload1 = _register_payload(sms_client, otp_capture, _unique_mobile(), code, email=email1)
    assert sms_client.post(f"{BASE}/register/complete", json=payload1).status_code == 200
    payload2 = _register_payload(sms_client, otp_capture, _unique_mobile(), code, email=email2)
    r = sms_client.post(f"{BASE}/register/complete", json=payload2)
    assert r.status_code == 403
    assert r.json()["detail"] == invitation_service.MSG_ALREADY_USED


def test_mine_manager_registration_with_code_creates_active_account(sms_client, client, db_session, otp_capture, mobile):
    """Positive test: Mine Manager registration via code -> active + JWT."""
    email = f"mgr-otp-{mobile[-4:]}@test.ai"
    code = _invite_code(client, "mine_manager", email)
    payload = _register_payload(sms_client, otp_capture, mobile, code, email=email)
    r = sms_client.post(f"{BASE}/register/complete", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["user"]["role"] == "mine_manager"
    assert body["user"]["is_active"] is True

    claims = decode_token(body["access_token"])
    assert claims["role"] == "mine_manager" and claims["iss"] == "mineguardai"


# ------------------------------------------------------------------ #
# 8. JWT issuance / secret hygiene
# ------------------------------------------------------------------ #
def test_pending_registration_token_cannot_authenticate(sms_client, otp_capture, mobile):
    r = _start_and_verify(sms_client, otp_capture, mobile)
    prp = r.json()["token"]
    res = sms_client.get("/api/mines", headers={"Authorization": f"Bearer {prp}"})
    assert res.status_code == 401


def test_otp_endpoints_do_not_leak_secrets(sms_client, otp_capture, mobile):
    sms_client.post(f"{BASE}/register/otp/start", json={"mobile": mobile})
    code = otp_capture.last()
    r = sms_client.post(f"{BASE}/register/otp/verify", json={"mobile": mobile, "otp": "111111"})
    body = r.text
    assert code not in body                       # real OTP never echoed
    assert settings.MSG91_AUTHKEY not in body     # authkey never echoed
    assert settings.MSG91_WIDGET_ID not in body   # widget id never echoed
    assert mobile not in body                     # full mobile never echoed


def test_classic_login_still_works_without_mobile(sms_client, db_session):
    """Regression guard: seeded-style user without mobile uses classic login."""
    db_session.rollback()
    user = models.User(id="u-classic", email="classic@test.ai", full_name="Classic",
                       role="safety_officer", hashed_password=hash_password("Classic@123"))
    db_session.add(user)
    db_session.commit()
    try:
        r = sms_client.post(f"{BASE}/login", data={"username": "classic@test.ai", "password": "Classic@123"})
        assert r.status_code == 200
        assert r.json()["access_token"]
    finally:
        db_session.rollback()
        db_session.delete(user)
        db_session.commit()
