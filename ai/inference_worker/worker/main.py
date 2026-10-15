"""Phase 1 worker FastAPI app: /health + token-gated POST /detect.

Standalone: imports nothing from backend/. Vyra is loaded once at startup;
if it fails to load, /detect returns 503 with a clear message and /health
reports model_loaded=false — never fake detections.

Auth: `Authorization: Bearer <AI_WORKER_TOKEN>`. Constant-time compare; the
token value is never logged. Local-only binding by default (127.0.0.1).
"""
from __future__ import annotations

import base64
import hmac
import logging
import time

from fastapi import FastAPI, HTTPException, Query, Request

from worker.detector import VyraDetector, VyraNotLoadedError
from worker.settings import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("worker")

app = FastAPI(title="MineGuardAI Vyra inference worker (Phase 1, local)")
detector = VyraDetector(settings.model_path)

JPEG_MAGIC = b"\xff\xd8"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_IMAGE_BYTES = 64  # a real encoded image is never smaller


@app.on_event("startup")
def load_model_once() -> None:
    """Load the EXISTING Vyra weights exactly once at worker startup."""
    if not settings.token:
        raise SystemExit("AI_WORKER_TOKEN is required (random secret; never in git).")
    detector.load()
    if detector.loaded:
        logger.info("Vyra ready: %d classes", len(detector.classes))
    else:
        logger.error("Vyra NOT loaded: %s", detector.load_error)


@app.get("/health")
def health():
    """Honest probe: model_loaded true only when Vyra is really in memory."""
    return {
        "status": "ok" if detector.loaded else "degraded",
        "model_loaded": detector.loaded,
        "model_path": settings.model_path,
        "classes": detector.classes if detector.loaded else None,
        "load_error": detector.load_error,
        "load_seconds": detector.load_seconds,
    }


def _require_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token (Authorization: Bearer <token>)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    supplied = auth[len("Bearer "):].strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), settings.token.encode()):
        # Identical response for missing/invalid tokens prevents token probing.
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.post("/detect")
async def detect(
    request: Request,
    confidence: float = Query(default=None, ge=0.01, le=1.0),
    imgsz: int = Query(default=None, ge=64, le=1280),
    annotate: bool = Query(default=None),
    return_base64: bool = Query(default=None),
):
    """Real Vyra inference on raw JPEG/PNG bytes. Bearer token required.

    Returns JSON with detections; when annotation is on (default) the annotated
    PNG is attached as `annotated_image_base64` (the same convention the backend
    uses for frame evidence; base64 is 1.33x, acceptable locally — Phase 2 can
    switch to multipart for lower overhead).
    """
    _require_token(request)

    if not detector.loaded:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Vyra model not loaded ({detector.load_error}); "
                "no detections can be truthfully reported."
            ),
        )

    max_bytes = int(settings.max_image_mb * 1024 * 1024)
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"Image too large (limit {settings.max_image_mb} MB)"
        )
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty request body")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"Image too large (limit {settings.max_image_mb} MB)"
        )
    if not (data.startswith(JPEG_MAGIC) or data.startswith(PNG_MAGIC)):
        raise HTTPException(
            status_code=415, detail="Unsupported media type: body must be JPEG or PNG bytes"
        )
    if len(data) < MIN_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Malformed image (too small)")

    t0 = time.perf_counter()
    try:
        res = detector.detect(
            data,
            confidence=confidence if confidence is not None else settings.default_confidence,
            imgsz=imgsz if imgsz is not None else settings.default_imgsz,
            annotate=(annotate if annotate is not None else settings.return_annotated),
        )
    except VyraNotLoadedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # ultralytics/opencv unexpected errors
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}")
    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    annotated_png = res.pop("annotated_png", None)
    want_annotated_field = (
        return_base64 if return_base64 is not None else True
    )
    body = {
        "status": "ok",
        "detector": "vyra_yolov8m_ppe",
        **res,
        "image_bytes": len(data),
        "total_request_ms": total_ms,
    }
    if annotated_png is not None and want_annotated_field:
        body["annotated_image_base64"] = base64.b64encode(annotated_png).decode("ascii")
        body["annotated_image_bytes"] = len(annotated_png)
    return body
