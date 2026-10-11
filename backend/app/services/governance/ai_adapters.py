"""AI capability adapters: OCR, voice transcription, translation.

Every adapter is a provider abstraction with a DEMO fallback. The demo
adapter NEVER fabricates plausible content: it returns an explicit
"UNAVAILABLE / NOT CONNECTED" result the UI must show verbatim. When a real
provider is configured (API keys via settings), the adapter calls it.

Rule: AI output is always a SUGGESTION with model name + raw text; a human
reviews and confirms before anything becomes an official record.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class AiResult:
    """Uniform adapter result. status: ok | unavailable | error."""

    capability: str
    status: str
    provider: str
    text: str | None = None
    fields: dict = field(default_factory=dict)
    language: str | None = None
    model: str | None = None
    message: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.status == "ok"


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_extract(image_bytes: bytes, mime_type: str = "image/jpeg") -> AiResult:
    """Extract text from a document image.

    Provider order: configured OCR provider (none built-in by default) ->
    explicit UNAVAILABLE. We never pretend to have read a document.
    """
    provider = (settings.OCR_PROVIDER or "none").lower()
    if provider in ("", "none", "demo"):
        return AiResult(
            capability="ocr",
            status="unavailable",
            provider="none",
            message="OCR NOT CONNECTED — no provider configured. Upload reviewed manually; no text was extracted.",
        )
    # Real providers would be dispatched here (e.g. an HTTP OCR API).
    return AiResult(
        capability="ocr",
        status="unavailable",
        provider=provider,
        message=f"OCR provider '{provider}' is configured but not implemented in this build.",
    )


# ---------------------------------------------------------------------------
# Voice transcription
# ---------------------------------------------------------------------------

def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm", language: str | None = None) -> AiResult:
    """Speech-to-text. Regional languages only if the provider supports them.

    We NEVER silently translate: transcription returns the provider's own
    language code, and translation is a separate, explicit step.
    """
    provider = (settings.VOICE_PROVIDER or "none").lower()
    if provider in ("", "none", "demo"):
        return AiResult(
            capability="voice",
            status="unavailable",
            provider="none",
            message="VOICE TRANSCRIPTION NOT CONNECTED — no provider configured. Record audio and type the report manually.",
        )
    return AiResult(
        capability="voice",
        status="unavailable",
        provider=provider,
        message=f"Voice provider '{provider}' is configured but not implemented in this build.",
    )


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = {"en": "English", "hi": "हिन्दी (Hindi)"}


def translate_text(text: str, target_language: str = "hi") -> AiResult:
    """Translate safety notices / selected UI content.

    Regulatory text is NEVER auto-translated for legal use: callers must keep
    and display the ORIGINAL alongside any translation.
    """
    provider = (settings.TRANSLATION_PROVIDER or "none").lower()
    if target_language not in SUPPORTED_LANGUAGES:
        return AiResult(
            capability="translation",
            status="error",
            provider=provider,
            message=f"Unsupported target language '{target_language}'. Supported: {sorted(SUPPORTED_LANGUAGES)}",
        )
    if provider in ("", "none", "demo"):
        return AiResult(
            capability="translation",
            status="unavailable",
            provider="none",
            message="TRANSLATION NOT CONNECTED — showing original text only.",
        )
    return AiResult(
        capability="translation",
        status="unavailable",
        provider=provider,
        message=f"Translation provider '{provider}' is configured but not implemented in this build.",
    )
