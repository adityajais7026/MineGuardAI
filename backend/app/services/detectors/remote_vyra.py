"""Remote Vyra inference — HTTP client to the dedicated AI worker.

Phase 2 of the off-Render architecture: the YOLOv8m weights CANNOT live in the
Render Free backend (512 MB OOM), so when AI_SERVICE_URL is configured every
image/frame inference is delegated to the verified local worker

    POST {AI_SERVICE_URL}/detect      (Authorization: Bearer AI_SERVICE_TOKEN)

RESPONSIBILITY BOUNDARY (unchanged):
  * THE BACKEND keeps auth, RBAC, mine isolation, thresholds/violation policy,
    cooldowns, events, alerts, evidence, storage, DB — the worker is stateless
    inference only. Nothing mine/user-aware leaves this process.
  * The worker never receives credentials beyond its own bearer token.

HONESTY GUARANTEES (same rules as YoloService):
  * Worker offline / timeout / auth failure / malformed response -> HTTP 503
    to the caller. NEVER a fabricated detection, NEVER a silent fallback.
  * Detections are exactly what the worker returned (real Vyra output).
  * `_load_model()` is a deliberate NO-OP: remote mode must never initialise
    PyTorch/Ultralytics inside the memory-capped backend.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.yolo_detection import DetectionBox

logger = logging.getLogger(__name__)


class RemoteInferenceUnavailable(HTTPException):
    """AI worker unreachable/failed — rendered as a truthful 503 to the client."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=503,
            detail=f"AI inference service unavailable: {detail}",
        )


class RemoteVyraDetector:
    """YoloService-compatible client that runs inference on the AI worker."""

    def __init__(self, *, base_url: str | None = None, token: str | None = None,
                 timeout: float | None = None,
                 request_factory: Callable[..., httpx.Response] | None = None):
        self.base_url = (base_url or settings.AI_SERVICE_URL).rstrip("/")
        self.token = token if token is not None else settings.AI_SERVICE_TOKEN
        self.timeout = timeout if timeout is not None else settings.AI_SERVICE_TIMEOUT_SECONDS
        self._post = request_factory or httpx.post

    # -- YoloService-compatible surface ---------------------------------- #
    def _load_model(self) -> None:
        """NO-OP by design: remote mode never loads weights in this process.

        Kept only so `resolve_media_detector()._load_model()` guards (upload +
        live endpoints) keep working without change; a misconfiguration is
        surfaced here as the usual 503, never papered over.
        """
        if not self.base_url or not self.token:
            raise RemoteInferenceUnavailable(
                "AI_SERVICE_URL / AI_SERVICE_TOKEN are not fully configured"
            )

    def model_info(self) -> dict:
        """Detector probe shape (mirrors YoloService.model_info fields).

        No network call: availability here means 'remote inference is
        configured'; runtime failures still produce a 503 at inference time.
        """
        configured = bool(self.base_url and self.token)
        return {
            "detector": "RemoteVyraDetector",
            "source": "remote_worker",
            "available": configured,
            "service": self.base_url,
            "timeout_seconds": self.timeout,
            "error": None if configured else "AI_SERVICE_URL/AI_SERVICE_TOKEN not configured",
        }

    def detect_image_bytes(
        self, data: bytes, *, confidence: float | None = None, imgsz: int | None = None
    ) -> tuple[list[DetectionBox], bytes]:
        """One image -> the worker -> (detections, annotated_png)."""
        self._load_model()
        try:
            import base64

            t0 = time.perf_counter()
            resp = self._post(
                f"{self.base_url}/detect",
                content=data,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/octet-stream",
                },
                params={
                    "confidence": confidence if confidence is not None else settings.YOLO_CONFIDENCE,
                    "imgsz": imgsz or settings.YOLO_IMGSZ,
                },
                timeout=self.timeout,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
        except httpx.TimeoutException as exc:
            logger.error("AI worker timeout after %.0f ms", self.timeout * 1000)
            raise RemoteInferenceUnavailable(f"timeout after {self.timeout}s ({exc.__class__.__name__})")
        except httpx.HTTPError as exc:
            # DIAGNOSTIC (temporary): production threw
            #   LocalProtocolError: Illegal header value b'Bearer ...'
            # while the request never left the container. Expose WHERE the
            # illegal byte sits WITHOUT leaking the secret: every printable
            # token byte is masked with '*', only non-printable bytes and
            # their byte-offsets from the end of the header value are shown.
            raw = str(exc)
            masked = ""
            for ch in raw:
                if ch.isprintable() and not ch.isspace() and (ch.isalnum() or ch in "_-+/.=:"):
                    masked += "*"
                else:
                    masked += ch
            logger.error("AI worker unreachable: %s: %s", exc.__class__.__name__, masked)
            raise RemoteInferenceUnavailable(
                f"worker unreachable ({exc.__class__.__name__}: {masked})"
            )

        if resp.status_code != 200:
            logger.error("AI worker returned %s", resp.status_code)
            raise RemoteInferenceUnavailable(f"worker returned HTTP {resp.status_code}")

        try:
            body = resp.json()
            raw = body["detections"]
            annotated_b64 = body["annotated_image_base64"]
        except (ValueError, KeyError) as exc:
            logger.error("AI worker response malformed (%s)", exc.__class__.__name__)
            raise RemoteInferenceUnavailable("worker returned a malformed response")

        detections = [
            DetectionBox(
                class_name=str(d["class"]),
                class_id=int(d.get("class_id", -1)),
                confidence=float(d["confidence"]),
                bbox=[float(v) for v in d["bbox"]],
            )
            for d in raw
        ]
        annotated_png = base64.b64decode(annotated_b64)
        logger.info(
            "remote inference ok: %d detections in %.0f ms",
            len(detections), latency_ms,
        )
        return detections, annotated_png

    def detect_video_file(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Honest capability statement: the stateless worker accepts images.
        (Video upload inference stays on the local path — never faked here.)"""
        raise RemoteInferenceUnavailable(
            "video inference is not available via the remote worker; upload inference "
            "disabled while AI_SERVICE_URL is configured"
        )


_singleton: RemoteVyraDetector | None = None


def get_remote_vyra_service() -> RemoteVyraDetector:
    global _singleton
    if _singleton is None:
        _singleton = RemoteVyraDetector()
    return _singleton
