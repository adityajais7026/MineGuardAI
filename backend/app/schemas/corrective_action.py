"""Corrective action API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActionPriority = Literal["low", "medium", "high", "critical"]
ActionStatus = Literal["pending", "in_progress", "completed", "overdue"]


class CorrectiveActionBase(BaseModel):
    incident_id: str | None = None
    inspection_id: str | None = None
    description: str = Field(min_length=1)
    assigned_to_id: str | None = None
    priority: ActionPriority = "medium"
    status: ActionStatus = "pending"
    due_date: datetime
    completion_date: datetime | None = None
    remarks: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "incident_id": "i-0002",
                "description": "Install additional CO sensors",
                "assigned_to_id": "u-mgr-0001",
                "priority": "critical",
                "due_date": "2026-10-01T00:00:00Z",
            }
        }
    )


class CorrectiveActionCreate(CorrectiveActionBase):
    pass


class CorrectiveActionUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1)
    assigned_to_id: str | None = None
    priority: ActionPriority | None = None
    status: ActionStatus | None = None
    due_date: datetime | None = None
    completion_date: datetime | None = None
    remarks: str | None = None
    incident_id: str | None = None
    inspection_id: str | None = None


class CorrectiveActionResponse(CorrectiveActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
