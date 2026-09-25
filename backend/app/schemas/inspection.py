"""Inspection API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InspectionType = Literal["safety", "environmental", "equipment", "compliance"]
InspectionStatus = Literal["scheduled", "in_progress", "completed", "cancelled"]
ComplianceResult = Literal["compliant", "non_compliant", "partial", "pending"]


class InspectionBase(BaseModel):
    mine_id: str
    inspector_id: str | None = None
    inspection_type: InspectionType = "safety"
    status: InspectionStatus = "scheduled"
    scheduled_at: datetime
    completed_at: datetime | None = None
    compliance_result: ComplianceResult = "pending"
    findings: str | None = None
    notes: str | None = None


class InspectionCreate(InspectionBase):
    pass


class InspectionUpdate(BaseModel):
    inspector_id: str | None = None
    inspection_type: InspectionType | None = None
    status: InspectionStatus | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    compliance_result: ComplianceResult | None = None
    findings: str | None = None
    notes: str | None = None


class InspectionResponse(InspectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
