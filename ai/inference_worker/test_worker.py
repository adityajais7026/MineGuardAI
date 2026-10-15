"""Local Phase 1 test script: real images -> /detect on the running worker.

Usage (worker already running):
    cd backend
    .venv/Scripts/python.exe ../ai/inference_worker/test_worker.py \
        --image path/to/ppe.jpg --image path/to/violation.jpg

Requires AI_WORKER_TOKEN in the environment (same value the worker uses).
Sends REAL images, prints REAL detections and measured latency — nothing is
fabricated. Also checks /health, an unauthenticated call (expects 401) and a
malformed-image call (expects 415).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = f"http://{os.environ.get('AI_WORKER_HOST', '127.0.0.1')}:{os.environ.get('AI_WORKER_PORT', '8081')}"


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("AI_WORKER_TOKEN")
    if not token:
        print("ERROR: AI_WORKER_TOKEN env var required.")
        raise SystemExit(2)
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", action="append", default=[], help="JPEG/PNG path (repeatable)")
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    if not args.image:
        print("ERROR: pass at least one --image (use real photos, not synthetic ones)")
        return 2

    token_env = os.environ.get("AI_WORKER_TOKEN")
    failures: list[str] = []
    print(f"Worker: {BASE}\n")

    # ---- /health --------------------------------------------------------
    start = time.perf_counter()
    r = httpx.get(f"{BASE}/health", timeout=120)
    print(f"GET /health -> {r.status_code} ({(time.perf_counter()-start)*1000:.0f} ms)")
    print(json.dumps(r.json(), indent=2)[:800], "\n")
    if r.status_code != 200 or not r.json().get("model_loaded"):
        failures.append("health/model_loaded: Vyra not loaded — stopping")
        print("FATAL:", failures)
        return 1

    # ---- negative: no token --------------------------------------------
    r = httpx.post(f"{BASE}/detect", content=x if (x := b"") else b"", timeout=30)
    okay = r.status_code == 401
    print(f"POST /detect (no token) -> {r.status_code} (expect 401) {'OK' if okay else 'FAIL'}")
    if not okay:
        failures.append("unauthenticated /detect was not 401")

    # ---- negative: token, garbage body ----------------------------------
    r = httpx.post(f"{BASE}/detect", content=b"not an image" + b"x" * 100,
                   headers=_auth_headers(), timeout=30)
    okay = r.status_code == 415
    print(f"POST /detect (non-image) -> {r.status_code} (expect 415) {'OK' if okay else 'FAIL'}")
    if not okay:
        failures.append("non-image body was not 415")

    # ---- real images ----------------------------------------------------
    results = []
    for path in args.image:
        p = Path(path)
        if not p.exists():
            failures.append(f"test image missing on disk: {p}")
            continue
        data = p.read_bytes()
        is_jpeg = data[:2] == b"\xff\xd8"
        is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
        if not (is_jpeg or is_png):
            failures.append(f"{p.name}: not a real JPEG/PNG (magic bytes missing)")
            continue
        start = time.perf_counter()
        r = httpx.post(
            f"{BASE}/detect",
            content=data,
            headers={**_auth_headers(), "Content-Type": "image/jpeg" if is_jpeg else "image/png"},
            params={"confidence": args.confidence, "imgsz": args.imgsz},
            timeout=300,
        )
        total_ms = (time.perf_counter() - start) * 1000
        print(f"\nPOST /detect {p.name} ({len(data)} bytes, {'JPEG' if is_jpeg else 'PNG'}) -> {r.status_code}")
        if r.status_code != 200:
            print(r.text[:400])
            failures.append(f"{p.name}: detect returned {r.status_code}")
            continue
        body = r.json()
        img_bytes = body.get("annotated_image_base64")
        if img_bytes:
            out = Path(f"inference_worker_test_output_{p.stem}.png")
            out.write_bytes(base64.b64decode(img_bytes))
            print(f"  annotated evidence saved: {out}")
        print(f"  image_bytes          : {body.get('image_bytes')}")
        print(f"  inference_ms         : {body.get('inference_ms')}")
        print(f"  total_request_ms     : {body.get('total_request_ms')} (client-side: {total_ms:.0f})")
        print(f"  detection_count      : {body.get('detection_count')}")
        print(f"  classes_detected     : {body.get('classes_detected')}")
        for d in body.get("detections", []):
            print(f"    - {d['class']:<16} conf={d['confidence']:<6} bbox={d['bbox']}")
        results.append({"image": p.name, **{k: body.get(k) for k in
                        ("inference_ms", "total_request_ms", "detection_count", "classes_detected")}})

    print("\nLatency summary:")
    for res in results:
        print(f"  {res['image']}: inference {res['inference_ms']} ms, request {res['total_request_ms']} ms")

    print("\nRESULT:", "PASS" if not failures else f"FAIL — {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
