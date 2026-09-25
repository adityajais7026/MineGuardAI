"""Camera event API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CameraEventType = Literal[
    "person_without_helmet",
    "person_without_vest",
    "restricted_zone_entry",
    "vehicle_in_restricted_area",
    "fire_smoke",
    "unsafe_crowding",
    "other",
]
CameraSeverity = Literal["low", "medium", "high", "critical"]
CameraEventStatus = Literal["new", "investigating", "resolved"]
DetectionSource = Literal["simulated", "yolo", "opencv"]


class CameraEventBase(BaseModel):
    mine_id: str
    zone_id: str | None = None
    camera_id: str = Field(min_length=1, max_length=60)
    event_type: CameraEventType
    detected_object: str | None = Field(default=None, max_length=120)
    zone_label: str | None = Field(default=None, max_length=255)
    confidence: float = Field(ge=0, le=1)
    severity: CameraSeverity = "medium"
    status: CameraEventStatus = "new"
    detection_source: DetectionSource = "simulated"
    model_version: str | None = Field(default=None, max_length=60)
    image_ref: str | None = Field(default=None, max_length=500)
    video_ref: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | None = None


class CameraEventCreate(CameraEventBase):
    pass


class CameraEventUpdate(BaseModel):
    zone_id: str | None = None
    zone_label: str | None = Field(default=None, max_length=255)
    severity: CameraSeverity | None = None
    status: CameraEventStatus | None = None
    image_ref: str | None = Field(default=None, max_length=500)
    video_ref: str | None = Field(default=None, max_length=500)


class CameraEventResponse(CameraEventBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    occurred_at: datetime
    created_at: datetime
