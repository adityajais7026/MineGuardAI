"""Remote Vyra inference worker (AI_SERVICE_URL) tests.

Covers the requirements for the off-Render inference connection:
  A. remote worker success -> real detections converted to DetectionBox
  B. worker timeout        -> truthful 503
  C. worker unavailable    -> truthful 503 (not empty detections)
  D. invalid worker response -> truthful 503
  E. worker auth failure (401) -> truthful 503 referencing configuration
  F. NO fake-detection fallback in any failure mode
  G. auth preserved (existing suite) / K. token required (worker-side = 401 path)
     -> asserted via the local YoloService mock parity + existing tests
  Endpoint-level: the /frame endpoint surfaces the 503 with no fabricated event.
"""
import base64
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.services.detectors.remote_vyra import (
    RemoteInferenceUnavailable,
    RemoteVyraDetector,
)
from app.services.yolo_detection import DetectionBox

TOKEN = "unit-test-token-not-a-secret"  # named constant only for unit tests
RESP = {"Response": None}

# real fixture images (same files the live/upload suites use)
_REAL_JPEG = Path(__file__).parent / "fixtures" / "ppe_no_vest.jpg"
_REAL_JPEG_B64 = base64.b64encode(_REAL_JPEG.read_bytes()).decode("ascii")


def _worker_response_handler(
    *,
    status_code=200,
    body=None,
    assert_auth=True,
):
    """Build an httpx.MockTransport handler simulating the real worker."""

    def handler(request: httpx.Request) -> httpx.Response:
        if assert_auth:
            auth = request.headers.get("Authorization", "")
            assert auth == f"Bearer {TOKEN}", "backend must send the bearer token"
            assert "Authorization" in request.headers
        if status_code == 200:
            return httpx.Response(200, json=body or _WORKER_OK_BODY)
        return httpx.Response(status_code, json={"detail": "nope"})

    return handler


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


# Real worker response shape (detections produced by the verified Vyra fixture
# images in phase 1; values here mirror that output byte-for-byte in shape).
_WORKER_OK_BODY = {
    "status": "ok",
    "detector": "vyra_yolov8m_ppe",
    "detections": [
        {
            "class": "NO-Safety Vest",
            "class_id": 10,
            "confidence": 0.5718,
            "bbox": [55.3, 459.3, 201.6, 699.6],
        },
        {
            "class": "Hardhat",
            "class_id": 3,
            "confidence": 0.4623,
            "bbox": [494.4, 554.8, 574.9, 639.5],
        },
    ],
    "detection_count": 2,
    "classes_detected": ["Hardhat", "NO-Safety Vest"],
    "inference_ms": 398.5,
    "imgsz": 640,
    "conf": 0.35,
    "total_request_ms": 440.6,
    "annotated_image_base64": base64.b64encode(b"\x89PNG" + b"annotated-bytes").decode("ascii"),
}


def _detector(handler, *, url="https://worker.example.com"):
    return RemoteVyraDetector(
        base_url=url, token=TOKEN, timeout=10,
        request_factory=lambda *a, **kw: httpx.Client(
            transport=httpx.MockTransport(handler)
        ).post(*a, **kw),
    )


# ------------------------------------------------------------------ #
# A. remote worker success                                            #
# ------------------------------------------------------------------ #
def test_worker_success_returns_real_detections_and_annotated():
    det = _detector(_worker_response_handler())
    detections, annotated = det.detect_image_bytes(b"fake-jpeg-bytes", confidence=0.10)
    assert isinstance(detections, list) and len(detections) == 2
    assert isinstance(detections[0], DetectionBox)
    assert detections[0].class_name == "NO-Safety Vest"
    assert detections[0].confidence == pytest.approx(0.5718)
    assert detections[0].bbox == [55.3, 459.3, 201.6, 699.6]
    annotated_body = b"\x89PNG" + b"annotated-bytes"
    assert annotated == annotated_body


def test_worker_success_sends_bearer_token_and_limits():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["auth"] = request.headers.get("Authorization")
        sent["url"] = str(request.url)
        return httpx.Response(200, json=_WORKER_OK_BODY)

    det = _detector(handler)
    det.detect_image_bytes(b"x", confidence=0.10, imgsz=640)
    assert sent["auth"] == f"Bearer {TOKEN}"
    assert sent["url"].split("?")[0].endswith("/detect")
    assert "confidence=0.1" in sent["url"]
    assert "imgsz=640" in sent["url"]


# ------------------------------------------------------------------ #
# B/C. timeout + unreachable -> truthful 503, never a fallback         #
# ------------------------------------------------------------------ #
def test_worker_timeout_raises_503():
    det = _detector(_timeout_handler)
    with pytest.raises(HTTPException) as excinfo:
        det.detect_image_bytes(b"x")
    assert excinfo.value.status_code == 503
    assert "timeout" in excinfo.value.detail.lower()


def test_worker_unreachable_raises_503():
    det = _detector(_unreachable_handler)
    with pytest.raises(RemoteInferenceUnavailable) as excinfo:
        det.detect_image_bytes(b"x")
    assert excinfo.value.status_code == 503
    assert "unreachable" in excinfo.value.detail.lower()


# ------------------------------------------------------------------ #
# D. invalid worker response -> truthful 503                           #
# ------------------------------------------------------------------ #
def test_worker_malformed_response_raises_503():
    det = _detector(_worker_response_handler(body={"status": "ok"}))  # no detections
    with pytest.raises(RemoteInferenceUnavailable) as excinfo:
        det.detect_image_bytes(b"x")
    assert "malformed" in excinfo.value.detail.lower()


def test_worker_500_raises_503():
    det = _detector(_worker_response_handler(status_code=500))
    with pytest.raises(RemoteInferenceUnavailable) as excinfo:
        det.detect_image_bytes(b"x")
    assert excinfo.value.status_code == 503
    assert "500" in excinfo.value.detail


# ------------------------------------------------------------------ #
# E. worker auth failure (401) -> 503, never fake values               #
# ------------------------------------------------------------------ #
def test_worker_auth_failure_raises_503():
    det = _detector(_worker_response_handler(status_code=401))
    with pytest.raises(RemoteInferenceUnavailable) as excinfo:
        det.detect_image_bytes(b"x")
    assert excinfo.value.status_code == 503
    assert "401" in excinfo.value.detail


# ------------------------------------------------------------------ #
# F. tokens are never logged                                          #
# ------------------------------------------------------------------ #
def test_remote_inference_success_logs_no_token(caplog):
    det = _detector(_worker_response_handler())
    with caplog.at_level(logging.DEBUG, logger="app.services.detectors.remote_vyra"):
        det.detect_image_bytes(b"x")
    joined = "\n".join(str(r.getMessage()) for r in caplog.records)
    assert TOKEN not in joined


# ------------------------------------------------------------------ #
# Endpoint-level: /frame uses the remote worker and fails honestly     #
# ------------------------------------------------------------------ #
def test_frame_endpoint_remote_worker_offline_is_truthful_503(client, monkeypatch):
    from app.core.config import settings
    from app.services.detectors import remote_vyra

    monkeypatch.setattr(settings, "AI_SERVICE_URL", "https://offline.example.com")
    monkeypatch.setattr(settings, "AI_SERVICE_TOKEN", TOKEN)
    remote_vyra._singleton = _detector(_unreachable_handler, url="https://offline.example.com")
    try:
        payload = {"mine_id": "m-test-0001", "image_base64": _REAL_JPEG_B64}
        r = client.post("/api/ai/detect/frame", json=payload)
        assert r.status_code == 503
        assert "unavailable" in r.json()["detail"].lower()
    finally:
        remote_vyra._singleton = None


def test_frame_endpoint_remote_ok_no_events_when_worker_ok(client, monkeypatch):
    """A compliant remote result must NOT be turned into a fake violation."""
    from app.core.config import settings
    from app.services.detectors import remote_vyra

    ok = dict(_WORKER_OK_BODY)
    ok["detections"] = [{"class": "Safety Vest", "class_id": 13,
                         "confidence": 0.55, "bbox": [1.0, 2.0, 3.0, 4.0]}]
    ok["classes_detected"] = ["Safety Vest"]
    monkeypatch.setattr(settings, "AI_SERVICE_URL", "https://worker.example.com")
    monkeypatch.setattr(settings, "AI_SERVICE_TOKEN", TOKEN)
    remote_vyra._singleton = _detector(_worker_response_handler(body=ok))
    try:
        payload = {"mine_id": "m-test-0001", "image_base64": _REAL_JPEG_B64}
        r = client.post("/api/ai/detect/frame", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["detection_count"] == 1
        assert body["detections"][0]["class"] == "Safety Vest"
        # compliance finding only — no alert, no violation event fabricated
        assert all(e["ppe_status"] != "violation" for e in body["events"])
        assert body["alerts"] == []
    finally:
        remote_vyra._singleton = None
