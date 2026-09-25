"""
Supabase Storage service for camera media (enhancement phase).

Organised paths inside the private `mineguard-media` bucket:
    camera/{mine_id}/images/{uuid}.{ext}    original uploaded images
    camera/{mine_id}/videos/{uuid}.{ext}    original uploaded videos
    camera/{mine_id}/results/{uuid}.{ext}   annotated images/videos

Storage abstraction: SupabaseStorage when credentials exist; LocalStorage
(under backend/media/, gitignored) otherwise so development continues to work
without credentials. Both satisfy the same interface, and NOTHING is faked:
Local-storage uploads are clearly reported as local files, never as Supabase
uploads.

Only metadata/paths live in PostgreSQL — never binary media.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

# Whitelisted MIME types (validated against actual bytes where possible).
ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}

# Magic-byte signatures: never trust the client-supplied content type alone.
_FILE_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # WebP: RIFF....WEBP
    (b"\x1a\x45\xdf\xa3", "video/webm"),
]


def sniff_mime(data: bytes) -> str | None:
    """Detect MIME from magic bytes; returns canonical type or None if unknown.

    MP4/MOV (ISO-BMFF) files carry 'ftyp' at offset 4 (after the 4-byte box
    size), so they are checked separately.
    """
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "video/mp4"
    for sig, mime in _FILE_SIGNATURES:
        if data.startswith(sig):
            if mime == "image/webp":
                return "image/webp" if data[8:12] == b"WEBP" else None
            return mime
    return None


@dataclass
class StoredObject:
    """Reference to one stored object (metadata only — safe for the DB)."""

    provider: str  # "supabase" | "local"
    bucket: str
    path: str      # object path inside the bucket
    mime_type: str
    size_bytes: int
    url: str | None  # access URL (signed for Supabase, local static path)


class StorageBackend(ABC):
    @abstractmethod
    def upload_bytes(self, data: bytes, *, path: str, mime_type: str) -> StoredObject:
        """Upload bytes to the given object path."""

    @abstractmethod
    def create_access_url(self, path: str, expires_seconds: int = 3600) -> str | None:
        """Return a time-limited access URL, or None if not applicable."""


class SupabaseStorage(StorageBackend):
    """Real Supabase Storage uploads via the REST API (service role key, backend only)."""

    def __init__(self) -> None:
        if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
            raise RuntimeError(
                "SupabaseStorage requires SUPABASE_URL and SUPABASE_SERVICE_KEY "
                "environment variables."
            )
        self.base_url = settings.SUPABASE_URL.rstrip("/")
        self.service_key = settings.SUPABASE_SERVICE_KEY
        self.bucket = settings.SUPABASE_MEDIA_BUCKET

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.service_key}",
            "apikey": self.service_key,
        }
        if extra:
            headers.update(extra)
        return headers

    def upload_bytes(self, data: bytes, *, path: str, mime_type: str) -> StoredObject:
        import httpx

        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{path}"
        response = httpx.post(
            url,
            content=data,
            headers=self._headers({"Content-Type": mime_type, "x-upsert": "true"}),
            timeout=120,
        )
        if response.status_code not in (200, 201):
            # Surface storage errors clearly; never pretend the upload worked.
            raise RuntimeError(
                f"Supabase Storage upload failed ({response.status_code}): {response.text[:300]}"
            )
        return StoredObject(
            provider="supabase",
            bucket=self.bucket,
            path=path,
            mime_type=mime_type,
            size_bytes=len(data),
            url=None,  # private bucket: access only via create_access_url
        )

    def create_access_url(self, path: str, expires_seconds: int = 3600) -> str | None:
        """Create a signed URL for a PRIVATE bucket object (backend holds the key)."""
        import httpx

        url = f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{path}"
        response = httpx.post(
            url,
            json={"expiresIn": expires_seconds},
            headers=self._headers({"Content-Type": "application/json"}),
            timeout=30,
        )
        if response.status_code != 200:
            logger.error("Signed URL creation failed for %s: %s", path, response.text[:200])
            return None
        signed = response.json().get("signedURL") or response.json().get("signedUrl")
        return f"{self.base_url}/storage/v1{signed}" if signed else None


class LocalStorage(StorageBackend):
    """Development fallback storing files under backend/media/ (gitignored).

    Clearly reports provider="local" so nothing masquerades as Supabase.
    """

    def __init__(self) -> None:
        self.root = Path(settings.CAMERA_SNAPSHOT_DIR) / "media"
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_bytes(self, data: bytes, *, path: str, mime_type: str) -> StoredObject:
        target = self.root / path
        # Path traversal guard: resolved path must stay inside the media root.
        if not str(target.resolve()).startswith(str(self.root.resolve())):
            raise ValueError("Invalid storage path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredObject(
            provider="local",
            bucket=settings.SUPABASE_MEDIA_BUCKET,
            path=path,
            mime_type=mime_type,
            size_bytes=len(data),
            url=f"/media/{path}",
        )

    def create_access_url(self, path: str, expires_seconds: int = 3600) -> str | None:
        return f"/media/{path}"


def get_storage() -> StorageBackend:
    """Factory: real Supabase Storage when configured, else local dev storage."""
    if settings.STORAGE_PROVIDER == "supabase":
        try:
            return SupabaseStorage()
        except RuntimeError as exc:
            logger.warning("Supabase Storage unavailable (%s) — using local storage.", exc)
    return LocalStorage()


def build_media_path(mine_id: str, kind: str, extension: str) -> str:
    """Object path builder: camera/{mine_id}/{kind}/{uuid}.{ext}."""
    if kind not in {"images", "videos", "results"}:
        raise ValueError("kind must be images|videos|results")
    safe_mine = re.sub(r"[^A-Za-z0-9_-]", "", mine_id)[:40] or "unknown-mine"
    safe_ext = re.sub(r"[^A-Za-z0-9]", "", extension)[:5] or "bin"
    return f"camera/{safe_mine}/{kind}/{uuid4().hex}.{safe_ext}"
