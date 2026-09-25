"""Compliance rule API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleOperator = Literal[">", ">=", "<", "<="]
Severity = Literal["low", "medium", "high", "critical"]


class ComplianceRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    parameter: str = Field(min_length=1, max_length=50)
    operator: RuleOperator = ">"
    threshold: float
    unit: str = Field(min_length=1, max_length=20)
    severity: Severity = "medium"
    is_active: bool = True
    mine_id: str | None = Field(default=None, description="NULL applies the rule to all mines")


class ComplianceRuleCreate(ComplianceRuleBase):
    pass


class ComplianceRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    parameter: str | None = Field(default=None, min_length=1, max_length=50)
    operator: RuleOperator | None = None
    threshold: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    severity: Severity | None = None
    is_active: bool | None = None
    mine_id: str | None = None


class ComplianceRuleResponse(ComplianceRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
