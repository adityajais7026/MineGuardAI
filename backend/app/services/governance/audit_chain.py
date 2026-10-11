"""Tamper-evident audit trail (SHA-256 hash chain).

event_hash(N) = sha256(prev_hash(N-1) + canonical_json(entry_N)).

The first entry chains from the constant GENESIS (all-zero 64-hex). Any edit
to a past row invalidates every later hash, which verify_chain() detects.

This is a hash chain, NOT a blockchain; the UI must say
"tamper-evident audit log". Entries are APPEND-ONLY: there is no update or
delete API — important records are never silently rewritten.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditEvent

GENESIS = "0" * 64


def canonical_json(obj: object) -> str:
    """Stable serialization: sorted keys, compact separators, explicit dates."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, fields: dict) -> str:
    material = prev_hash + canonical_json(fields)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_event(
    db: Session,
    *,
    actor_id: str | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    mine_id: str | None = None,
    payload: dict | None = None,
) -> AuditEvent:
    """Append one event to the chain (commits)."""
    last = db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.event_hash if last else GENESIS

    fields = {
        "seq": seq,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "mine_id": mine_id,
        "payload": payload,
    }
    event_hash = compute_hash(prev_hash, fields)

    event = AuditEvent(
        seq=seq,
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        mine_id=mine_id,
        payload_json=payload,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def verify_chain(db: Session) -> dict:
    """Recompute the full chain. Returns a verification report."""
    events = db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
    prev = GENESIS
    for e in events:
        if e.prev_hash != prev:
            return {"valid": False, "broken_at_seq": e.seq, "reason": "prev_hash mismatch", "entries": len(events)}
        fields = {
            "seq": e.seq,
            "actor_id": e.actor_id,
            "actor_role": e.actor_role,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "mine_id": e.mine_id,
            "payload": e.payload_json,
        }
        if compute_hash(prev, fields) != e.event_hash:
            return {"valid": False, "broken_at_seq": e.seq, "reason": "event_hash mismatch", "entries": len(events)}
        prev = e.event_hash
    return {"valid": True, "entries": len(events), "head_hash": prev if events else GENESIS}
