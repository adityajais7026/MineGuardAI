"""Compliance engine endpoints (Phase 5). Business logic lives in services."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import Mine
from app.database.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.environmental_reading import EnvironmentalReadingResponse
from app.services.compliance import (
    EvaluationResult,
    IngestResult,
    ingest_reading,
    reevaluate_mine,
)

router = APIRouter(prefix="/compliance", tags=["Compliance Engine"],
                   dependencies=[Depends(get_current_user)])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("/ingest", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
@router.post("/ingest", response_model=IngestResult, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("compliance_engine"))])
def ingest_reading_endpoint(
    db: DbSession,
    mine_id: str,
    parameter: str = Query(min_length=1, max_length=50),
    value: float = Query(),
    unit: str = Query(min_length=1, max_length=20),
    source: str = Query(default="simulated", pattern="^(simulated|sensor|external)$"),
    recorded_at: datetime | None = None,
):
    """Store a reading, evaluate it against active rules, raise an alert on violation.

    This is the Phase 5 pipeline endpoint: Environmental Reading -> Rule
    Evaluation -> COMPLIANT / WARNING / VIOLATION -> alert (with dedupe).
    """
    try:
        return ingest_reading(db, mine_id=mine_id, parameter=parameter, value=value, unit=unit,
                              source=source, recorded_at=recorded_at)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/evaluate/{mine_id}", response_model=list[EvaluationResult])
def evaluate_mine(db: DbSession, mine_id: str):
    """Re-evaluate a mine's readings from the last 7 days (display refresh)."""
    if db.get(Mine, mine_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Mine '{mine_id}' not found")
    return reevaluate_mine(db, mine_id)
