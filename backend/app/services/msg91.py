"""MSG91 OTP Widget provider (server-side only).

Uses the official OTP Widget server-side APIs, which send SMS through the
widget's own default SMS configuration (no custom DLT template involved):

    Send   : POST {base}/api/v5/widget/sendOtp
             headers: authkey; body: {"widgetId": ..., "identifier": mobile}
             -> {"type": "success", "message": "<request_id>"}
    Verify : POST {base}/api/v5/widget/verifyOtp
             headers: authkey; body: {"widgetId": ..., "reqId": ..., "otp": ...}
             -> {"type": "success", ...} | {"type": "error", "message": ...}

MSG91 generates and validates the code; we track the request id and enforce
our own expiry/attempt/cooldown policy around it. The authkey is sent ONLY as
a header to MSG91 and is never returned, rendered or logged.
"""
import logging
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Country code default (India) — callers may pass a full international number.
DEFAULT_COUNTRY = "91"

_WIDGET_SEND_ENDPOINT = "/api/v5/widget/sendOtp"
_WIDGET_VERIFY_ENDPOINT = "/api/v5/widget/verifyOtp"

# Universal valid code when OTP_SMS_DISABLED=True (dev/tests only). Never set
# that flag in production. Real mode never consults this constant.
TEST_OTP_CODE = "424242"


class Msg91Error(RuntimeError):
    """Raised when MSG91 widget send/verify fails (network, provider rejection)."""


def normalize_mobile(raw: str) -> str:
    """Normalise a user-supplied mobile into the widget's identifier form.

    Accepts '+91 99999 99999', '91-9999999999', leading zeros, etc. and
    returns bare digits with country code, e.g. '919999999999'.
    Raises ValueError for obviously invalid input (length/digits only).
    """
    digits = "".join(ch for ch in (raw or "").strip() if ch.isdigit())
    if not digits:
        raise ValueError("Mobile number must contain digits")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:          # local 10-digit (India) — add default CC
        digits = DEFAULT_COUNTRY + digits
    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("Mobile number must be 10-15 digits including country code")
    return digits


def mask_mobile(mobile: str) -> str:
    """Masked form safe for logs/UI: e.g. '9199******90' (never full number)."""
    if len(mobile) < 6:
        return "****"
    return mobile[:4] + "*" * (len(mobile) - 5) + mobile[-1]


def _require_config() -> str:
    widget_id = settings.MSG91_WIDGET_ID
    if not settings.MSG91_AUTHKEY:
        raise Msg91Error("MSG91 authkey is not configured")
    if not widget_id:
        raise Msg91Error("MSG91 widget id is not configured")
    return widget_id


def send_otp_widget(mobile: str) -> str:
    """Trigger the widget's default SMS OTP for `mobile`; returns the request id.

    Raises Msg91Error on any failure. Never includes the authkey in raised
    messages or logs.
    """
    if settings.OTP_SMS_DISABLED:
        logger.info("SMS disabled (OTP_SMS_DISABLED) — skipped delivery to %s", mask_mobile(mobile))
        return f"disabled-{uuid.uuid4()}"

    widget_id = _require_config()
    url = settings.MSG91_BASE_URL.rstrip("/") + _WIDGET_SEND_ENDPOINT
    headers = {"authkey": settings.MSG91_AUTHKEY, "Content-Type": "application/json"}
    payload = {"widgetId": widget_id, "identifier": mobile}

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=settings.MSG91_SEND_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        # Log only the error class — never URL/headers/payload.
        logger.warning("MSG91 widget send failed: %s", exc.__class__.__name__)
        raise Msg91Error("SMS provider unreachable") from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    # MSG91 may answer request-level errors with HTTP 200 + type:"error".
    if response.status_code >= 400 or str(body.get("type", "")).lower() == "error":
        logger.warning(
            "MSG91 widget send rejected (status=%s, provider_error=%s)",
            response.status_code,
            str(body.get("message", ""))[:80],
        )
        raise Msg91Error("SMS provider rejected the request")

    request_id = str(body.get("message", "")).strip()
    if not request_id:
        logger.warning("MSG91 widget send returned no request id (status=%s)", response.status_code)
        raise Msg91Error("SMS provider returned an unexpected response")
    logger.info("MSG91 widget OTP sent to %s", mask_mobile(mobile))
    return request_id


def verify_otp_widget(request_id: str, code: str) -> bool:
    """Check `code` with MSG91 against the widget challenge `request_id`.

    Returns True only for a verified code. Provider-level rejections
    (wrong code) return False; transport/config problems raise Msg91Error
    so callers can distinguish 'wrong OTP' from 'provider down'.
    """
    if settings.OTP_SMS_DISABLED:
        return code == TEST_OTP_CODE

    widget_id = _require_config()
    url = settings.MSG91_BASE_URL.rstrip("/") + _WIDGET_VERIFY_ENDPOINT
    headers = {"authkey": settings.MSG91_AUTHKEY, "Content-Type": "application/json"}
    payload = {"widgetId": widget_id, "reqId": request_id, "otp": code}

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=settings.MSG91_SEND_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.warning("MSG91 widget verify failed: %s", exc.__class__.__name__)
        raise Msg91Error("SMS provider unreachable") from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        logger.warning("MSG91 widget verify rejected (status=%s)", response.status_code)
        raise Msg91Error("SMS provider rejected the request")
    return str(body.get("type", "")).lower() == "success"
