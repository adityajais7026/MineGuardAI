"""Alert API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlertType = Literal["environmental", "safety", "equipment", "compliance"]
AlertSeverity = Literal["low", "medium", "high", "critical"]
AlertStatus = Literal["new", "acknowledged", "investigating", "resolved"]


class AlertBase(BaseModel):
    mine_id: str
    alert_type: AlertType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    severity: AlertSeverity = "medium"
    source: str = Field(default="manual", max_length=60)
    status: AlertStatus = "new"
    source_reading_id: str | None = None
    source_event_id: str | None = None
    assigned_to_id: str | None = None


class AlertCreate(AlertBase):
    pass


class AlertUpdate(BaseModel):
    """Workflow update; timestamps are set server-side on transitions."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    severity: AlertSeverity | None = None
    status: AlertStatus | None = None
    assigned_to_id: str | None = None


class AlertResponse(AlertBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
