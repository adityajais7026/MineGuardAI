"""Restricted zone API schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RestrictedZoneBase(BaseModel):
    mine_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    camera_id: str | None = Field(default=None, max_length=60)
    is_active: bool = True


class RestrictedZoneCreate(RestrictedZoneBase):
    pass


class RestrictedZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    camera_id: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class RestrictedZoneResponse(RestrictedZoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
