"""Compliance rules CRUD router (evaluation engine arrives in Phase 5)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import ComplianceRule
from app.database.session import get_db
from app.schemas import ComplianceRuleCreate, ComplianceRuleResponse, ComplianceRuleUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/compliance-rules", tags=["Compliance Rules"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(ComplianceRule, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[ComplianceRuleResponse])
def list_rules(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    parameter: str | None = None,
    severity: str | None = None,
    is_active: bool | None = None,
    mine_id: str | None = None,
    sort: str = Query(default="created_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "parameter": parameter,
            "severity": severity,
            "is_active": is_active,
            "mine_id": mine_id,
        },
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=ComplianceRuleResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("compliance_rules"))])
def create_rule(db: DbSession, payload: ComplianceRuleCreate):
    try:
        return service.create(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create rule: unknown mine_id.",
        )


@router.get("/{rule_id}", response_model=ComplianceRuleResponse)
def get_rule(db: DbSession, rule_id: str):
    return service.get(db, rule_id)


@router.patch("/{rule_id}", response_model=ComplianceRuleResponse,
               dependencies=[Depends(write_access("compliance_rules"))])
def update_rule(db: DbSession, rule_id: str, payload: ComplianceRuleUpdate):
    try:
        return service.update(db, rule_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not update rule: unknown mine_id.",
        )


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("compliance_rules"))])
def delete_rule(db: DbSession, rule_id: str):
    service.delete(db, rule_id)
