"""Evidence file storage: reuse the existing Supabase/local storage backend.

Evidence binaries go to  evidence/{mine_id}/{kind}/{uuid}.{ext}  in the same
storage bucket used by camera media. Only the metadata row (Evidence) is kept
in the database; bytes never live in Postgres. SHA-256 is computed over the
raw bytes so any later file tampering is detectable.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database.models import Evidence
from app.services.storage import get_storage

# Evidence media extension map (post-magic-byte canonical types only).
_MEDIA_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    "audio/webm": "webm", "audio/mpeg": "mp3", "audio/wav": "wav",
    "audio/mp4": "m4a", "audio/ogg": "ogg",
    "application/pdf": "pdf",
}


def store_evidence_file(
    db: Session,
    *,
    mine_id: str,
    kind: str,
    target_fks: dict,
    media_type: str,
    data: bytes,
    mime_type: str,
    original_filename: str | None,
    uploaded_by_id: str,
    description: str | None = None,
) -> Evidence:
    """Persist one evidence file and its metadata row, committing atomically."""
    storage = get_storage()
    ext = _MEDIA_EXT.get(mime_type, "bin")
    path = f"evidence/{mine_id}/{kind}/{uuid4().hex}.{ext}"
    try:
        stored = storage.upload_bytes(data, path=path, mime_type=mime_type)
    except Exception as exc:  # storage failure must not create a phantom row
        raise HTTPException(status_code=502,
                            detail=f"Evidence storage failed: {exc}") from exc

    row = Evidence(
        mine_id=mine_id,
        kind=kind,
        media_type=media_type,
        file_path=stored.path,
        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        description=description,
        uploaded_by_id=uploaded_by_id,
        **target_fks,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
