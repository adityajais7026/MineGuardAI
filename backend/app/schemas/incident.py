"""Incident API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IncidentCategory = Literal[
    "fall_of_ground", "machinery", "vehicle", "gas", "fire", "electrical", "other"
]
IncidentSeverity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["open", "investigating", "action_required", "resolved", "closed"]


class IncidentBase(BaseModel):
    mine_id: str
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: IncidentCategory = "other"
    severity: IncidentSeverity = "medium"
    status: IncidentStatus = "open"
    evidence_ref: str | None = Field(default=None, max_length=500)
    reported_by_id: str | None = None
    occurred_at: datetime | None = None


class IncidentCreate(IncidentBase):
    pass


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: IncidentCategory | None = None
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    evidence_ref: str | None = Field(default=None, max_length=500)
    reported_by_id: str | None = None


class IncidentResponse(IncidentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
