"""One-off MSG91 production diagnostics (admin-only; remove after RCA).

Purpose: compare the exact outbound OTP request made by THIS container with
the known-working local request, and capture MSG91's sanitized verdict per
variant. Exposes no secrets: credentials appear only as fingerprints
(length/charset/quote/whitespace flags), identifiers are dummy all-zero
numbers (never a real subscriber), and success request ids are redacted.
"""
from __future__ import annotations

import hashlib
import re
import socket

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status

from app.core.config import settings
from app.core.security import get_current_user

router = APIRouter(prefix="/auth/otp-diag", tags=["Diagnostics"])

_SEND_URL = "https://control.msg91.com/api/v5/widget/sendOtp"
_SEND_URL_ALT = "https://api.msg91.com/api/v5/widget/sendOtp"
_DUMMY = "910000000000"  # all-zero dummy number: no SMS can be delivered anywhere


def _require_admin(user=Depends(get_current_user)):
    if getattr(user, "role", "") != "admin":
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def _fingerprint(value: str) -> dict:
    """Shape info only — never any character of the secret itself.

    sha256_8 lets two operators prove value EQUALITY without disclosure:
    a 32-bit prefix of a high-entropy 27-char key is not reversible.
    """
    return {
        "len": len(value or ""),
        "alnum_only": bool(re.fullmatch(r"[A-Za-z0-9]+", value or "")),
        "hex24": bool(re.fullmatch(r"[0-9a-f]{24}", value or "")),
        "quoted": bool(value) and value[0] in "\"'" and value[-1] == value[0],
        "has_whitespace": any(ch.isspace() for ch in (value or "")),
        "sha256_8": hashlib.sha256((value or "").encode()).hexdigest()[:8],
    }


@router.get("/env")
def env_fingerprint(_: None = Depends(_require_admin)) -> dict:
    """Static configuration fingerprint of the running container."""
    return {
        "authkey": _fingerprint(settings.MSG91_AUTHKEY),
        "widget_id": _fingerprint(settings.MSG91_WIDGET_ID),
        "base_url": settings.MSG91_BASE_URL,
        "otp_sms_disabled": settings.OTP_SMS_DISABLED,
        "container_host": socket.gethostname(),
    }


def _probe(label: str, url: str, headers: dict, body: dict) -> dict:
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=15.0,
                          follow_redirects=False)
    except httpx.HTTPError as exc:
        return {"label": label, "transport_error": exc.__class__.__name__}
    try:
        parsed = resp.json()
    except ValueError:
        parsed = {}
    message = str(parsed.get("message", ""))[:80]
    if str(parsed.get("type", "")).lower() == "success":
        message = f"<reqId redacted, len={len(str(parsed.get('message', '')))}>"
    return {
        "label": label,
        "http_status": resp.status_code,
        "type": parsed.get("type"),
        "code": parsed.get("code"),
        "message": message,
        "cf_ray": (resp.headers.get("cf-ray") or "")[:12],
        "cf_mitigated": resp.headers.get("cf-mitigated"),
        "server": resp.headers.get("server"),
    }


@router.post("/probe")
def run_probes(_: None = Depends(_require_admin)) -> dict:
    """Three controlled send attempts from this container (dummy number only).

    A: byte-exact replay of the production request (same helper defaults).
    B: same + Accept and browser-style User-Agent headers.
    C: same as B against MSG91's alternate API hostname.
    """
    authkey = settings.MSG91_AUTHKEY
    widget_id = settings.MSG91_WIDGET_ID
    base_headers = {"authkey": authkey, "Content-Type": "application/json"}
    probes = [
        _probe("A_exact_replay", _SEND_URL, base_headers,
               {"widgetId": widget_id, "identifier": _DUMMY}),
        _probe("B_with_accept_ua", _SEND_URL,
               {**base_headers, "Accept": "application/json",
                "User-Agent": "MineGuardAI/1.0"},
               {"widgetId": widget_id, "identifier": _DUMMY}),
        _probe("C_alt_host", _SEND_URL_ALT,
               {**base_headers, "Accept": "application/json"},
               {"widgetId": widget_id, "identifier": _DUMMY}),
        # Calibration: documented missing-credential behavior is HTTP 401.
        # If this IP instead gets the generic 403, the block happens BEFORE
        # auth evaluation => source-level rejection, not a value problem.
        _probe("D_no_authkey", _SEND_URL,
               {"Content-Type": "application/json"},
               {"widgetId": widget_id, "identifier": _DUMMY}),
        _probe("E_empty_widget", _SEND_URL, base_headers,
               {"widgetId": "", "identifier": _DUMMY}),
    ]
    egress_ip = None
    try:
        egress_ip = httpx.get("https://api.ipify.org?format=json",
                              timeout=10.0).json().get("ip")
    except (httpx.HTTPError, ValueError):
        pass
    return {"egress_ip": egress_ip, "container_host": socket.gethostname(),
            "probes": probes}
