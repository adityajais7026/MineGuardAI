"""Environmental reading API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReadingSource = Literal["simulated", "sensor", "external"]
ReadingStatus = Literal["normal", "violation"]


class EnvironmentalReadingBase(BaseModel):
    mine_id: str
    parameter: str = Field(min_length=1, max_length=50)
    value: float
    unit: str = Field(min_length=1, max_length=20)
    source: ReadingSource = "simulated"
    recorded_at: datetime | None = Field(
        default=None, description="Defaults to now when omitted"
    )


class EnvironmentalReadingCreate(EnvironmentalReadingBase):
    pass


class EnvironmentalReadingResponse(EnvironmentalReadingBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # Threshold/status are resolved server-side: threshold mirrors the matching
    # active compliance rule (or the submitted value), status is computed by a
    # simple comparison ONLY as a display convenience in Phase 4.
    # Full rule evaluation + alerting arrives with the Phase 5 compliance engine.
    threshold: float
    status: ReadingStatus
    rule_id: str | None
    created_at: datetime
