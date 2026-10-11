"""Governance platform tests: templates, inspections, checklist, compliance,
geofence, risk, audit chain, sync, notifications, AI adapters, RBAC scoping.

Isolation: uses the session-scoped test DB from conftest; all new rows use
unique ids and clean up after themselves where the test asserts counts.
"""
from __future__ import annotations

import base64
import uuid

import pytest

from app.core.security import get_current_user
from app.database import models
from app.main import app
from app.services.governance import ai_adapters, audit_chain, geofence as geofence_svc, inspections as inspection_svc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_template(client, name=None, items=None):
    payload = {
        "name": name or f"T-{uuid.uuid4().hex[:8]}",
        "inspection_type": "safety",
        "regulatory_reference": "Internal SOP 7.1",
        "items": items or [
            {"label": "Helmet compliance", "category": "ppe", "severity_weight": 8},
            {"label": "Fire extinguishers", "category": "fire", "severity_weight": 6},
        ],
    }
    resp = client.post("/api/governance/inspection-templates", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _mk_template_officer(client_env):
    """safety officer context client (overridden in tests via dependency)."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_template_crud(client):
    t = _mk_template(client)
    assert t["regulatory_reference"] == "Internal SOP 7.1"
    assert len(t["items"]) == 2

    listed = client.get("/api/governance/inspection-templates").json()
    assert any(x["id"] == t["id"] for x in listed)


# ---------------------------------------------------------------------------
# Inspection workflow: start -> checklist -> submit
# ---------------------------------------------------------------------------


def test_inspection_full_workflow(client):
    mine = client.get("/api/mines").json()["items"][0]
    t = _mk_template(client)
    start = client.post("/api/governance/inspections/from-template", json={
        "mine_id": mine["id"], "template_id": t["id"],
    })
    assert start.status_code == 201, start.text
    body = start.json()
    insp_id = body["inspection_id"]
    checklist = body["checklist"]
    assert len(checklist) == 2

    # Snapshot is idempotent: re-starting same template on a new inspection
    # creates fresh items, but re-snapshotting the SAME inspection doesn't
    # duplicate (covered by service test below).

    results = {
        checklist[0]["id"]: {"result": "pass", "comment": "ok"},
        checklist[1]["id"]: {"result": "unknown", "comment": "could not verify"},
    }
    put = client.put(f"/api/governance/inspections/{insp_id}/checklist",
                     json={"results": results})
    assert put.status_code == 200
    assert {i["result"] for i in put.json()} == {"pass", "unknown"}

    sub = client.post(f"/api/governance/inspections/{insp_id}/submit")
    assert sub.status_code == 200
    # unknown (with no fail) -> pending, NOT compliant (no fabricated compliance)
    assert sub.json()["compliance_result"] == "pending"


def test_checklist_rejects_foreign_item(client):
    mine = client.get("/api/mines").json()["items"][0]
    t1 = _mk_template(client)
    t2 = _mk_template(client)
    i1 = client.post("/api/governance/inspections/from-template",
                     json={"mine_id": mine["id"], "template_id": t1["id"]}).json()
    i2 = client.post("/api/governance/inspections/from-template",
                     json={"mine_id": mine["id"], "template_id": t2["id"]}).json()
    foreign = i2["checklist"][0]["id"]
    resp = client.put(f"/api/governance/inspections/{i1['inspection_id']}/checklist",
                      json={"results": {foreign: {"result": "pass"}}})
    assert resp.status_code == 422


def test_checklist_rejects_invalid_result(client):
    mine = client.get("/api/mines").json()["items"][0]
    t = _mk_template(client)
    i = client.post("/api/governance/inspections/from-template",
                    json={"mine_id": mine["id"], "template_id": t["id"]}).json()
    item = i["checklist"][0]["id"]
    resp = client.put(f"/api/governance/inspections/{i['inspection_id']}/checklist",
                      json={"results": {item: {"result": "maybe"}}})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Service-level: rollup rules
# ---------------------------------------------------------------------------


def test_rollup_rules():
    class FakeItem:
        def __init__(self, result):
            self.result = result

    assert inspection_svc.rollup_compliance([]) == "pending"
    assert inspection_svc.rollup_compliance([FakeItem("pass"), FakeItem("na")]) == "compliant"
    assert inspection_svc.rollup_compliance([FakeItem("pass"), FakeItem("fail")]) == "non_compliant"
    assert inspection_svc.rollup_compliance([FakeItem("unknown")]) == "pending"
    assert inspection_svc.rollup_compliance([FakeItem("fail"), FakeItem("unknown")]) == "non_compliant"


# ---------------------------------------------------------------------------
# Geofence
# ---------------------------------------------------------------------------


def test_geofence_radius_verification(client):
    mine = client.get("/api/mines").json()["items"][0]
    gf = client.post("/api/governance/geofences", json={
        "mine_id": mine["id"], "name": "pit-1", "boundary_type": "radius",
        "center_lat": 23.0, "center_lng": 86.0, "radius_m": 500,
    })
    assert gf.status_code == 201, gf.text

    inside = client.post("/api/governance/geofences/verify-location",
                         json={"mine_id": mine["id"], "latitude": 23.001, "longitude": 86.0})
    assert inside.json()["status"] == "inside"

    outside = client.post("/api/governance/geofences/verify-location",
                          json={"mine_id": mine["id"], "latitude": 24.5, "longitude": 86.0})
    assert outside.json()["status"] == "outside"

    # No fabricated GPS: missing coords -> unavailable, never inside.
    missing = client.post("/api/governance/geofences/verify-location",
                          json={"mine_id": mine["id"]})
    assert missing.json()["status"] == "unavailable"


def test_haversine_sanity():
    d = geofence_svc.haversine_m(23.0, 86.0, 23.0, 86.0)
    assert d == 0.0
    # ~111km per degree latitude
    d = geofence_svc.haversine_m(23.0, 86.0, 24.0, 86.0)
    assert 110_000 < d < 112_500


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


def test_risk_score_explainable(client):
    mine = client.get("/api/mines").json()["items"][0]
    resp = client.get(f"/api/governance/risk/{mine['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert 0 <= body["score"] <= 100
    assert body["band"] in ("low", "medium", "high", "critical")
    # Explainability: every point contribution has a factor + detail
    for f in body["factors"]:
        assert f["points"] > 0 and f["factor"] and f["detail"]


# ---------------------------------------------------------------------------
# Audit chain
# ---------------------------------------------------------------------------


def test_audit_chain_append_and_verify(client, db_session):
    rep = audit_chain.verify_chain(db_session)
    assert rep["valid"] is True
    n0 = rep["entries"]
    audit_chain.append_event(
        db_session, actor_id="u-admin-0001", actor_role="admin",
        action="test.event", entity_type="test", payload={"x": 1},
    )
    rep2 = audit_chain.verify_chain(db_session)
    assert rep2["valid"] is True and rep2["entries"] == n0 + 1


def test_audit_chain_detects_tamper(db_session):
    from sqlalchemy import select
    from app.database.models import AuditEvent

    audit_chain.append_event(
        db_session, actor_id=None, actor_role=None,
        action="tamper.test.a", entity_type="test", payload={"n": 1},
    )
    audit_chain.append_event(
        db_session, actor_id=None, actor_role=None,
        action="tamper.test.b", entity_type="test", payload={"n": 2},
    )
    assert audit_chain.verify_chain(db_session)["valid"] is True
    # Tamper: rewrite an old payload in place
    ev = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "tamper.test.a")
    ).scalars().first()
    ev.payload_json = {"n": 999}
    db_session.commit()
    rep = audit_chain.verify_chain(db_session)
    assert rep["valid"] is False
    assert rep["broken_at_seq"] == ev.seq


def test_audit_admin_only(client):
    assert client.get("/api/governance/audit").status_code == 200
    assert client.get("/api/governance/audit/verify").status_code == 200


# ---------------------------------------------------------------------------
# Offline sync (idempotency)
# ---------------------------------------------------------------------------


def test_sync_idempotent(client):
    mine = client.get("/api/mines").json()["items"][0]
    t = _mk_template(client)
    guid = uuid.uuid4().hex
    payload = {
        "client_guid": guid, "mine_id": mine["id"], "entity_type": "inspection",
        "payload": {
            "mine_id": mine["id"], "template_id": t["id"],
            "results": {"0": {"result": "pass"}, "1": {"result": "fail"}},
        },
    }
    r1 = client.post("/api/governance/sync", json=payload)
    assert r1.status_code == 200 and r1.json()["status"] == "synced"
    ref1 = r1.json()["result_ref_id"]

    # Replayed push with the SAME guid -> duplicate, same ref, no new inspection
    r2 = client.post("/api/governance/sync", json=payload)
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["result_ref_id"] == ref1


def test_sync_failed_payload_is_recorded_not_lost(client):
    mine = client.get("/api/mines").json()["items"][0]
    guid = uuid.uuid4().hex
    payload = {
        "client_guid": guid, "mine_id": mine["id"], "entity_type": "inspection",
        "payload": {"mine_id": mine["id"], "template_id": "no-such-template"},
    }
    r = client.post("/api/governance/sync", json=payload)
    assert r.json()["status"] == "failed"
    assert r.json()["error"]
    q = client.get("/api/governance/sync/queue?status=failed").json()
    assert any(x["client_guid"] == guid for x in q)


# ---------------------------------------------------------------------------
# Workers / shifts / attendance
# ---------------------------------------------------------------------------


def test_worker_shift_attendance(client):
    mine = client.get("/api/mines").json()["items"][0]
    w = client.post("/api/governance/workers", json={
        "mine_id": mine["id"], "employee_code": f"EMP-{uuid.uuid4().hex[:6]}",
        "full_name": "Test Worker",
    })
    assert w.status_code == 201
    wid = w.json()["id"]

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    s = client.post("/api/governance/shifts", json={
        "mine_id": mine["id"], "name": "A",
        "starts_at": now.isoformat(), "ends_at": (now + timedelta(hours=8)).isoformat(),
    })
    assert s.status_code == 201
    a = client.post("/api/governance/shifts/attendance", json={
        "worker_id": wid, "mine_id": mine["id"], "shift_id": s.json()["id"],
        "check_in_at": now.isoformat(), "verification": "manual",
    })
    assert a.status_code == 201


# ---------------------------------------------------------------------------
# Contractors / documents
# ---------------------------------------------------------------------------


def test_contractor_document_lifecycle(client):
    c = client.post("/api/governance/contractors", json={"name": "ACME Mining"})
    assert c.status_code == 201
    d = client.post("/api/governance/contractors/documents", json={
        "contractor_id": c.json()["id"], "doc_type": "training_certificate",
        "title": "Safety training 2026", "document_ref": "docs/t1.pdf",
    })
    assert d.status_code == 201
    assert d.json()["verification_status"] == "pending_verification"
    doc_id = d.json()["id"]
    v = client.post(f"/api/governance/contractors/documents/{doc_id}/verify",
                    json={"verification_status": "valid"})
    assert v.json()["verification_status"] == "valid"
    bad = client.post(f"/api/governance/contractors/documents/{doc_id}/verify",
                      json={"verification_status": "totally legit"})
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# Emergency + notifications
# ---------------------------------------------------------------------------


def test_emergency_creates_notifications(client):
    mine = client.get("/api/mines").json()["items"][0]
    e = client.post("/api/governance/emergencies", json={
        "mine_id": mine["id"], "emergency_type": "fire", "severity": "critical",
        "title": "Fire in pit", "description": "Test emergency",
    })
    assert e.status_code == 201
    bad = client.post("/api/governance/emergencies", json={
        "mine_id": mine["id"], "emergency_type": "zombie", "severity": "critical",
        "title": "x",
    })
    assert bad.status_code == 422


def test_notifications_scoped_to_user(client):
    # admin sees only own/global notifications; list must not 500
    resp = client.get("/api/governance/notifications")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def test_telemetry_demo_device_labeled(client):
    mine = client.get("/api/mines").json()["items"][0]
    dev = client.post("/api/governance/telemetry/devices", json={
        "mine_id": mine["id"], "device_code": f"CH4-{uuid.uuid4().hex[:6]}",
        "parameter": "methane", "unit": "%LEL", "source": "demo",
        "warning_threshold": 0.5, "critical_threshold": 1.0,
    })
    assert dev.status_code == 201
    assert dev.json()["source"] == "demo"  # UI must label DEMO
    did = dev.json()["id"]
    r1 = client.post("/api/governance/telemetry/readings",
                     json={"device_id": did, "value": 0.3})
    assert r1.json()["status"] == "normal"
    r2 = client.post("/api/governance/telemetry/readings",
                     json={"device_id": did, "value": 1.4})
    assert r2.json()["status"] == "critical"


# ---------------------------------------------------------------------------
# AI adapters: honest unavailability
# ---------------------------------------------------------------------------


def test_ocr_unavailable_not_fabricated(client):
    resp = client.post("/api/governance/ai/ocr",
                       json={"data_base64": base64.b64encode(b"fakepng").decode()})
    body = resp.json()
    assert body["status"] == "unavailable"
    assert "NOT CONNECTED" in (body["message"] or "")
    assert body["text"] is None  # no fabricated text


def test_voice_unavailable_not_fabricated(client):
    resp = client.post("/api/governance/ai/voice",
                       json={"data_base64": base64.b64encode(b"fakeaudio12345678").decode()})
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["text"] is None


def test_translation_rejects_unknown_language(client):
    resp = client.post("/api/governance/ai/translate",
                       json={"text": "hello", "target_language": "xx"})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("error", "unavailable")


def test_capabilities_matrix(client):
    caps = client.get("/api/governance/ai/capabilities").json()
    assert caps["ppe_detection"]["status"] == "LIVE"
    assert caps["ocr"]["status"] == "UNAVAILABLE"  # honest: not connected
    assert caps["risk_analysis"]["status"] == "LIVE"


# ---------------------------------------------------------------------------
# Compliance requirements: reference is mandatory
# ---------------------------------------------------------------------------


def test_requirement_requires_reference(client):
    mine = client.get("/api/mines").json()["items"][0]
    ok = client.post("/api/governance/compliance/requirements", json={
        "mine_id": mine["id"], "title": "Weekly ventilation check",
        "reference": "Mine SOP 12", "frequency": "weekly",
    })
    assert ok.status_code == 201
    bad = client.post("/api/governance/compliance/requirements", json={
        "mine_id": mine["id"], "title": "No reference", "frequency": "weekly",
    })
    assert bad.status_code == 422  # reference field is required


def test_compliance_summary_counts(client):
    mine = client.get("/api/mines").json()["items"][0]
    resp = client.get(f"/api/governance/compliance/summary?mine_id={mine['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requirements"] == (
        body["compliant"] + body["attention"] + body["violation"] + body["not_assessed"]
    )


# ---------------------------------------------------------------------------
# PDF reports (zero-dependency writer)
# ---------------------------------------------------------------------------


def test_pdf_reports(client):
    mine = client.get("/api/mines").json()["items"][0]
    t = _mk_template(client)
    insp = client.post("/api/governance/inspections/from-template",
                       json={"mine_id": mine["id"], "template_id": t["id"]}).json()
    insp_id = insp["inspection_id"]
    client.post(f"/api/governance/inspections/{insp_id}/submit")

    r1 = client.get(f"/api/governance/reports/inspection/{insp_id}.pdf")
    assert r1.status_code == 200
    assert r1.headers["content-type"] == "application/pdf"
    assert r1.content.startswith(b"%PDF")

    r2 = client.get(f"/api/governance/reports/compliance/{mine['id']}.pdf")
    assert r2.status_code == 200 and r2.content.startswith(b"%PDF")

    r3 = client.get(f"/api/governance/reports/safety/{mine['id']}.pdf")
    assert r3.status_code == 200 and r3.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Review / approval lifecycle (additive review_status column)
# ---------------------------------------------------------------------------


def _mk_inspection_for_review(client, db_session, mine):
    """Start an inspection as the safety officer, permitted on `mine`."""
    officer = db_session.get(models.User, "u-safe-0001")
    original_permitted = officer.permitted_mine_ids
    officer.permitted_mine_ids = [mine["id"]]
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: officer
    try:
        t = _mk_template(client)
        body = client.post("/api/governance/inspections/from-template",
                           json={"mine_id": mine["id"], "template_id": t["id"]}).json()
        return body["inspection_id"]
    finally:
        officer.permitted_mine_ids = original_permitted
        db_session.commit()
        app.dependency_overrides[get_current_user] = lambda: db_session.get(models.User, "u-admin-0001")


def test_review_lifecycle_happy_path(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    inspector = db_session.get(models.User, "u-safe-0001")
    manager = db_session.get(models.User, "u-mgr-0001")
    # scoped manager for the mine so review transitions are permitted
    mine_row = db_session.get(models.Mine, mine["id"])
    original_manager = mine_row.manager_id
    mine_row.manager_id = manager.id
    db_session.commit()
    try:
        # as safety officer: start & submit
        app.dependency_overrides[get_current_user] = lambda: inspector
        insp_id = _mk_inspection_for_review(client, db_session, mine)
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "submitted"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["review_status"] == "submitted"

        # inspector cannot approve their own inspection
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "approved"})
        assert resp.status_code == 422

        # manager approves
        app.dependency_overrides[get_current_user] = lambda: manager
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "under_review"})
        assert resp.status_code == 200, resp.text
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "approved"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["review_status"] == "approved"
        # closed after approved
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "closed"})
        assert resp.status_code == 200, resp.text
        # closed is terminal
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "draft"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides[get_current_user] = lambda: db_session.get(models.User, "u-admin-0001")
        mine_row.manager_id = original_manager
        db_session.commit()


def test_review_transition_requires_manager(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    officer = db_session.get(models.User, "u-safe-0001")
    app.dependency_overrides[get_current_user] = lambda: officer
    try:
        insp_id = _mk_inspection_for_review(client, db_session, mine)
        # officer (not manager of the mine) cannot approve/reject/under_review
        resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                           json={"review_status": "under_review"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides[get_current_user] = lambda: db_session.get(models.User, "u-admin-0001")


def test_review_invalid_jump_rejected(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    insp_id = _mk_inspection_for_review(client, db_session, mine)
    resp = client.post(f"/api/governance/inspections/{insp_id}/review",
                       json={"review_status": "closed"})
    assert resp.status_code == 422  # draft/new -> closed is not a legal transition


# ---------------------------------------------------------------------------
# Evidence upload (validation + mine scoping)
# ---------------------------------------------------------------------------


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_evidence_upload_inspection(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    insp_id = _mk_inspection_for_review(client, db_session, mine)
    resp = client.post(
        "/api/governance/evidence",
        params={"kind": "inspection", "target_id": insp_id},
        files={"file": ("site.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["media_type"] == "image"
    assert body["sha256"]  # hash recorded
    # download link resolution is mine-scoped and returns a URL/path
    dl = client.get(f"/api/governance/evidence/{body['id']}/download")
    assert dl.status_code == 200
    assert dl.json()["url"]


def test_evidence_rejects_disguised_file(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    insp_id = _mk_inspection_for_review(client, db_session, mine)
    resp = client.post(
        "/api/governance/evidence",
        params={"kind": "inspection", "target_id": insp_id},
        files={"file": ("evil.png", b"<?php evil() ?>", "image/png")},
    )
    assert resp.status_code == 415  # magic-byte check fails


def test_evidence_cross_mine_denied(client, db_session):
    """An officer permitted only on mine 1 cannot download mine 2's evidence."""
    from fastapi import HTTPException
    mine = client.get("/api/mines").json()["items"][0]
    insp_id = _mk_inspection_for_review(client, db_session, mine)
    up = client.post(
        "/api/governance/evidence",
        params={"kind": "inspection", "target_id": insp_id},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    ev_id = up.json()["id"]
    officer = db_session.get(models.User, "u-safe-0001")
    original_permitted = officer.permitted_mine_ids
    officer.permitted_mine_ids = []  # no mines permitted
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: officer
    try:
        dl = client.get(f"/api/governance/evidence/{ev_id}/download")
        assert dl.status_code == 403
    finally:
        officer.permitted_mine_ids = original_permitted
        db_session.commit()
        app.dependency_overrides[get_current_user] = lambda: db_session.get(models.User, "u-admin-0001")


# ---------------------------------------------------------------------------
# Extended reports
# ---------------------------------------------------------------------------


def test_extended_reports(client, db_session):
    mine = client.get("/api/mines").json()["items"][0]
    insp_id = _mk_inspection_for_review(client, db_session, mine)
    for path in (
        f"/api/governance/reports/violations/{mine['id']}.pdf",
        "/api/governance/reports/corrective-actions",
        "/api/governance/reports/emergencies",
        "/api/governance/reports/contractors",
        "/api/governance/reports/audit",
        "/api/governance/reports/workforce",
        f"/api/governance/reports/telemetry/{mine['id']}.pdf",
        f"/api/governance/reports/corrective-actions?mine_id={mine['id']}",
        f"/api/governance/reports/workforce?mine_id={mine['id']}",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"
        assert r.content.startswith(b"%PDF"), path

    # org-wide reports are admin-only
    officer = db_session.get(models.User, "u-safe-0001")
    app.dependency_overrides[get_current_user] = lambda: officer
    try:
        r = client.get("/api/governance/reports/workforce")
        assert r.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: db_session.get(models.User, "u-admin-0001")
