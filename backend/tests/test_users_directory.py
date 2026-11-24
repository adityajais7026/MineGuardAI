"""Admin → Users directory: role tabs, search, pagination and audited changes.

Covers the behaviour the redesigned Users page relies on:
  * server-side search by name, email, role and assigned mine
  * true per-role counts and true pagination totals
  * role / mine-assignment / activation changes written to the audit chain
  * privilege guards (no self role change, no demoting the last Administrator,
    no non-admin access to the directory or to role changes)
"""
import pytest
from sqlalchemy import func, select

from app.database.models import AuditEvent, User

UM = "/api/users"
ADMIN = "u-admin-0001"
MGR = "u-mgr-0001"
SAFETY = "u-safe-0001"
ENV = "u-env-0001"

ROLES = ("admin", "environmental_officer", "mine_manager", "safety_officer")


def _create_user(client, email: str, role: str = "safety_officer", **extra) -> dict:
    body = {
        "email": email,
        "full_name": extra.pop("full_name", "Temp User"),
        "password": "Password!123",
        "role": role,
        **extra,
    }
    r = client.post(UM, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _drop_user(db_session, user_id: str) -> None:
    user = db_session.get(User, user_id)
    if user is not None:
        db_session.delete(user)
        db_session.commit()


def _latest_audit(db_session, action: str, entity_id: str) -> AuditEvent | None:
    return db_session.execute(
        select(AuditEvent)
        .where(AuditEvent.action == action, AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
def test_search_by_email_returns_only_that_account(client):
    r = client.get(UM, params={"q": "manager@test.ai"})
    assert r.status_code == 200
    assert {u["email"] for u in r.json()["items"]} == {"manager@test.ai"}


def test_search_by_name_is_case_insensitive(client):
    r = client.get(UM, params={"q": "sAfEtY"})
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()["items"]}
    assert "safety@test.ai" in emails


def test_search_by_assigned_mine_name_returns_its_officers(client):
    """Officers are assigned to 'Test Mine' through permitted_mine_ids."""
    r = client.get(UM, params={"q": "Test Mine"})
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()["items"]}
    assert {"safety@test.ai", "env@test.ai"} <= emails
    # The manager of a different mine is not assigned to this one.
    assert "manager@test.ai" not in emails


def test_search_by_mine_code_matches_too(client):
    r = client.get(UM, params={"q": "MINE-TST"})
    assert r.status_code == 200
    assert {u["email"] for u in r.json()["items"]} >= {"safety@test.ai", "env@test.ai"}


def test_search_by_managed_mine_finds_the_manager(client):
    mine = client.post("/api/mines", json={
        "name": "Searchonly Pit", "code": "SRCH-1", "mine_type": "open_cast",
        "status": "operational", "location": "Test", "manager_id": MGR,
    })
    assert mine.status_code == 201, mine.text
    mine_id = mine.json()["id"]
    try:
        r = client.get(UM, params={"q": "Searchonly"})
        assert r.status_code == 200
        assert {u["email"] for u in r.json()["items"]} == {"manager@test.ai"}
    finally:
        assert client.delete(f"/api/mines/{mine_id}").status_code in (204, 200)


def test_search_with_no_match_returns_empty_page(client):
    r = client.get(UM, params={"q": "zzz-no-such-user-or-mine"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["total"] == 0


# --------------------------------------------------------------------------
# Role filters, counts, pagination
# --------------------------------------------------------------------------
def test_role_filter_returns_only_that_role(client):
    r = client.get(UM, params={"role": "safety_officer", "limit": 200})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and {u["role"] for u in items} == {"safety_officer"}


def test_unknown_role_filter_is_rejected(client):
    r = client.get(UM, params={"role": "superuser"})
    assert r.status_code == 422
    assert "superuser" in r.json()["detail"]


@pytest.mark.parametrize("role", ROLES)
def test_role_counts_match_the_database(client, db_session, role):
    body = client.get(f"{UM}/role-counts").json()
    expected = db_session.scalar(
        select(func.count()).select_from(User).where(User.role == role)
    )
    assert body["by_role"][role] == expected


def test_role_counts_total_and_status_split(client, db_session):
    body = client.get(f"{UM}/role-counts").json()
    expected_total = db_session.scalar(select(func.count()).select_from(User))
    assert body["total"] == expected_total
    assert body["active"] + body["inactive"] == expected_total
    assert sum(body["by_role"].values()) == expected_total


def test_role_counts_respect_the_search_term(client, db_session):
    body = client.get(f"{UM}/role-counts", params={"q": "manager@test.ai"}).json()
    assert body["total"] == 1
    assert body["by_role"]["mine_manager"] == 1
    assert body["by_role"]["admin"] == 0


def test_pagination_reports_true_total_and_slices(client, db_session):
    total = db_session.scalar(select(func.count()).select_from(User))
    first = client.get(UM, params={"limit": 2, "skip": 0}).json()
    assert first["total"] == total
    assert len(first["items"]) == 2
    assert first["limit"] == 2 and first["skip"] == 0

    second = client.get(UM, params={"limit": 2, "skip": 2}).json()
    assert second["total"] == total
    ids = {u["id"] for u in first["items"]} | {u["id"] for u in second["items"]}
    assert len(ids) == len(first["items"]) + len(second["items"])  # no overlap


# --------------------------------------------------------------------------
# Audited changes: role, mine assignment, activation
# --------------------------------------------------------------------------
def test_role_change_is_applied_and_audited(client, db_session):
    user = _create_user(client, "role-change@test.ai")
    try:
        r = client.patch(f"{UM}/{user['id']}", json={"role": "mine_manager"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "mine_manager"

        event = _latest_audit(db_session, "user.role_changed", user["id"])
        assert event is not None
        assert event.payload_json["from"] == "safety_officer"
        assert event.payload_json["to"] == "mine_manager"
        assert event.actor_id == ADMIN
        assert event.payload_json["_actor"]["email"] == "admin@test.ai"
    finally:
        _drop_user(db_session, user["id"])


def test_role_change_does_not_touch_mine_assignments(client, db_session):
    user = _create_user(client, "role-keeps-mines@test.ai")
    try:
        client.patch(f"{UM}/{user['id']}", json={"permitted_mine_ids": ["m-test-0001"]})
        r = client.patch(f"{UM}/{user['id']}", json={"role": "environmental_officer"})
        assert r.status_code == 200
        assert r.json()["permitted_mine_ids"] == ["m-test-0001"]
    finally:
        _drop_user(db_session, user["id"])


def test_mine_assignment_change_is_audited(client, db_session):
    user = _create_user(client, "mines-audit@test.ai")
    try:
        r = client.patch(f"{UM}/{user['id']}", json={"permitted_mine_ids": ["m-test-0001"]})
        assert r.status_code == 200
        event = _latest_audit(db_session, "user.mines_assigned", user["id"])
        assert event is not None
        assert event.payload_json["from"] == []
        assert event.payload_json["to"] == ["m-test-0001"]
        assert event.payload_json["added"] == ["m-test-0001"]
        assert event.payload_json["removed"] == []
    finally:
        _drop_user(db_session, user["id"])


def test_unchanged_mine_assignment_writes_no_audit_row(client, db_session):
    """Re-sending the same scope must not append a misleading audit entry."""
    user = _create_user(client, "noop-mines@test.ai")
    try:
        client.patch(f"{UM}/{user['id']}", json={"permitted_mine_ids": ["m-test-0001"]})
        before = db_session.scalar(select(func.count()).select_from(AuditEvent))
        r = client.patch(f"{UM}/{user['id']}", json={"permitted_mine_ids": ["m-test-0001"]})
        assert r.status_code == 200
        after = db_session.scalar(select(func.count()).select_from(AuditEvent))
        assert after == before
    finally:
        _drop_user(db_session, user["id"])


def test_deactivation_and_reactivation_are_audited(client, db_session):
    user = _create_user(client, "status-audit@test.ai")
    try:
        r = client.patch(f"{UM}/{user['id']}", json={"is_active": False})
        assert r.status_code == 200 and r.json()["is_active"] is False
        assert _latest_audit(db_session, "user.deactivated", user["id"]) is not None

        r = client.patch(f"{UM}/{user['id']}", json={"is_active": True})
        assert r.status_code == 200 and r.json()["is_active"] is True
        assert _latest_audit(db_session, "user.activated", user["id"]) is not None
    finally:
        _drop_user(db_session, user["id"])


# --------------------------------------------------------------------------
# Privilege guards
# --------------------------------------------------------------------------
def test_admin_cannot_change_their_own_role(client, db_session):
    r = client.patch(f"{UM}/{ADMIN}", json={"role": "safety_officer"})
    assert r.status_code == 400
    assert "own account" in r.json()["detail"]
    assert db_session.get(User, ADMIN).role == "admin"


def test_platform_always_keeps_an_active_administrator(client, db_session, as_role):
    """A demotion is allowed only while another active Administrator remains.

    Two guards together make it impossible to strand the platform:
      * this demotion succeeds because the second administrator stays active;
      * the remaining administrator can then not demote/deactivate themselves.
    """
    def active_admins() -> int:
        return db_session.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.is_active.is_(True)
            )
        )

    baseline = active_admins()
    second = _create_user(client, "second-admin@test.ai", role="admin")
    try:
        as_role(second["id"])
        r = client.patch(f"{UM}/{ADMIN}", json={"role": "safety_officer"})
        assert r.status_code == 200, r.text
        assert db_session.get(User, ADMIN).role == "safety_officer"

        # The actor is still an active Administrator, so the platform keeps one.
        assert active_admins() == baseline >= 1

        # The last Administrator cannot demote or deactivate themselves.
        own_role = client.patch(f"{UM}/{second['id']}", json={"role": "mine_manager"})
        assert own_role.status_code == 400
        assert "own account" in own_role.json()["detail"]
        own_status = client.patch(f"{UM}/{second['id']}", json={"is_active": False})
        assert own_status.status_code == 400
        assert db_session.get(User, second["id"]).role == "admin"
    finally:
        # Restore the shared seed row: this DB session is reused by later tests.
        restored = db_session.get(User, ADMIN)
        restored.role = "admin"
        db_session.commit()
        as_role(ADMIN)
        _drop_user(db_session, second["id"])


def test_non_admin_cannot_read_or_search_the_directory(client, as_role):
    try:
        as_role(SAFETY)
        assert client.get(UM).status_code == 403
        assert client.get(UM, params={"q": "admin"}).status_code == 403
        assert client.get(f"{UM}/role-counts").status_code == 403
    finally:
        as_role(ADMIN)


def test_non_admin_cannot_change_a_role_mine_or_status(client, as_role, db_session):
    try:
        as_role(SAFETY)
        r = client.patch(f"{UM}/{ENV}", json={"role": "admin"})
        assert r.status_code == 403
        assert db_session.get(User, ENV).role == "environmental_officer"

        assert client.patch(f"{UM}/{ENV}", json={"permitted_mine_ids": []}).status_code == 403
        assert client.patch(f"{UM}/{ENV}", json={"is_active": False}).status_code == 403
    finally:
        as_role(ADMIN)


def test_anonymous_cannot_search_or_count(anon_client):
    assert anon_client.get(UM, params={"q": "admin"}).status_code == 401
    assert anon_client.get(f"{UM}/role-counts").status_code == 401


def test_invalid_role_value_is_rejected_by_the_backend(client, db_session):
    r = client.patch(f"{UM}/{SAFETY}", json={"role": "superuser"})
    assert r.status_code == 422
    assert db_session.get(User, SAFETY).role == "safety_officer"


def test_audit_chain_stays_valid_after_the_directory_changes(client, db_session):
    """Directory events must not break the tamper-evident hash chain."""
    from app.services.governance import audit_chain

    before = audit_chain.verify_chain(db_session)
    user = _create_user(client, "chain-audit@test.ai")
    try:
        client.patch(f"{UM}/{user['id']}", json={"role": "mine_manager"})
        client.patch(f"{UM}/{user['id']}", json={"permitted_mine_ids": ["m-test-0001"]})
        client.patch(f"{UM}/{user['id']}", json={"is_active": False})
        after = audit_chain.verify_chain(db_session)
        assert after["entries"] > before["entries"]
        if before["valid"]:
            assert after["valid"] is True
        else:
            # Another test in the shared session already broke the chain; the
            # directory events must not move the break or add a second one.
            assert after["broken_at_seq"] == before["broken_at_seq"]
    finally:
        _drop_user(db_session, user["id"])
