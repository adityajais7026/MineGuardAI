"""Mine API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MineType = Literal["open_cast", "underground", "mixed"]
MineStatus = Literal["operational", "maintenance", "suspended", "closed"]


class MineBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9-]+$")
    mine_type: MineType = "open_cast"
    status: MineStatus = "operational"
    location: str = Field(min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    manager_id: str | None = None
    description: str | None = None


class MineCreate(MineBase):
    pass


class MineUpdate(BaseModel):
    """PATCH-style update; only provided fields are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=2, max_length=20, pattern=r"^[A-Z0-9-]+$")
    mine_type: MineType | None = None
    status: MineStatus | None = None
    location: str | None = Field(default=None, min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    manager_id: str | None = None
    description: str | None = None


class MineResponse(MineBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
