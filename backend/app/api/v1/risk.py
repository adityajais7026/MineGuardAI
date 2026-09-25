"""Risk classification endpoints (Phase 6). Formula lives in services/risk.py."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.models import Mine
from app.database.session import get_db
from app.services.risk import RiskAssessment, compute_all_risks, compute_risk

router = APIRouter(prefix="/risk", tags=["Risk Classification"],
                   dependencies=[Depends(get_current_user)])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/mines", response_model=list[RiskAssessment])
def risk_for_all_mines(db: DbSession):
    """Risk assessment for every mine (sorted highest risk first)."""
    assessments = compute_all_risks(db)
    assessments.sort(key=lambda a: a.score, reverse=True)
    return assessments


@router.get("/mines/{mine_id}", response_model=RiskAssessment)
def risk_for_mine(db: DbSession, mine_id: str):
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise HTTPException(status_code=404, detail=f"Mine '{mine_id}' not found")
    return compute_risk(db, mine)
