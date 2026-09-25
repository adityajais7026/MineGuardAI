"""Environmental readings router.

Phase 4 scope: plain CRUD + threshold resolution against the matching active
compliance rule. A simple value/threshold comparison sets `status` for display
convenience only — the real compliance engine (violation -> alert) is Phase 5.
"""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import ComplianceRule, EnvironmentalReading, Mine
from app.database.session import get_db
from app.schemas import EnvironmentalReadingCreate, EnvironmentalReadingResponse
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/environment", tags=["Environmental Readings"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(EnvironmentalReading, default_order="recorded_at")

DbSession = Annotated[Session, Depends(get_db)]

# Operators supported by compliance rules (mirrors ck_rules_operator).
_OPERATORS = {
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
}


def _resolve_threshold(db: Session, mine_id: str, parameter: str) -> ComplianceRule | None:
    """Most specific active rule: mine-specific first, then global."""
    rule = db.scalar(
        select(ComplianceRule)
        .where(
            ComplianceRule.parameter == parameter,
            ComplianceRule.is_active.is_(True),
            ComplianceRule.mine_id == mine_id,
        )
        .limit(1)
    )
    if rule is None:
        rule = db.scalar(
            select(ComplianceRule)
            .where(
                ComplianceRule.parameter == parameter,
                ComplianceRule.is_active.is_(True),
                ComplianceRule.mine_id.is_(None),
            )
            .limit(1)
        )
    return rule


@router.get("", response_model=PaginatedResponse[EnvironmentalReadingResponse])
def list_readings(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    parameter: str | None = None,
    reading_status: str | None = Query(default=None, alias="status"),
    recorded_after: datetime | None = None,
    recorded_before: datetime | None = None,
    sort: str = Query(default="recorded_at"),
    order: Literal["asc", "desc"] = "desc",
):
    """List readings with mine/parameter/status/time-range filters."""
    query = select(EnvironmentalReading)
    if mine_id:
        query = query.where(EnvironmentalReading.mine_id == mine_id)
    if parameter:
        query = query.where(EnvironmentalReading.parameter == parameter)
    if reading_status:
        query = query.where(EnvironmentalReading.status == reading_status)
    if recorded_after:
        query = query.where(EnvironmentalReading.recorded_at >= recorded_after)
    if recorded_before:
        query = query.where(EnvironmentalReading.recorded_at <= recorded_before)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_field = sort if sort in {"recorded_at", "value", "created_at", "parameter"} else "recorded_at"
    col = getattr(EnvironmentalReading, sort_field)
    query = query.order_by(col.desc() if order == "desc" else col.asc())

    items = db.execute(query.offset(skip).limit(limit)).scalars().all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=EnvironmentalReadingResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("environment"))])
def create_reading(db: DbSession, payload: EnvironmentalReadingCreate):
    """Create a reading; threshold comes from the matching active compliance rule.

    The rule is linked via rule_id so Phase 5's engine can trace every reading.
    """
    if db.get(Mine, payload.mine_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown mine_id '{payload.mine_id}'.")

    rule = _resolve_threshold(db, payload.mine_id, payload.parameter)
    threshold = rule.threshold if rule else payload.value  # no rule -> neutral threshold
    status_value = "normal"
    if rule is not None:
        check = _OPERATORS[rule.operator]
        status_value = "violation" if check(payload.value, rule.threshold) else "normal"

    reading = EnvironmentalReading(
        mine_id=payload.mine_id,
        rule_id=rule.id if rule else None,
        parameter=payload.parameter,
        value=payload.value,
        unit=payload.unit,
        threshold=threshold,
        status=status_value,
        source=payload.source,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


@router.get("/{reading_id}", response_model=EnvironmentalReadingResponse)
def get_reading(db: DbSession, reading_id: str):
    return service.get(db, reading_id)


@router.delete("/{reading_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("environment"))])
def delete_reading(db: DbSession, reading_id: str):
    service.delete(db, reading_id)
