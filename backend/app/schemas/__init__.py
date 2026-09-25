"""Central schema exports for routers."""
from app.schemas.alert import (
    AlertCreate,
    AlertResponse,
    AlertSeverity,
    AlertStatus,
    AlertType,
    AlertUpdate,
)
from app.schemas.camera_event import (
    CameraEventCreate,
    CameraEventResponse,
    CameraEventUpdate,
    DetectionSource,
)
from app.schemas.common import PaginatedResponse
from app.schemas.compliance_rule import (
    ComplianceRuleCreate,
    ComplianceRuleResponse,
    ComplianceRuleUpdate,
)
from app.schemas.corrective_action import (
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    CorrectiveActionUpdate,
)
from app.schemas.environmental_reading import (
    EnvironmentalReadingCreate,
    EnvironmentalReadingResponse,
)
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
)
from app.schemas.inspection import (
    InspectionCreate,
    InspectionResponse,
    InspectionUpdate,
)
from app.schemas.mine import MineCreate, MineResponse, MineUpdate
from app.schemas.restricted_zone import (
    RestrictedZoneCreate,
    RestrictedZoneResponse,
    RestrictedZoneUpdate,
)
from app.schemas.user import UserCreate, UserResponse, UserUpdate

__all__ = [
    "AlertCreate",
    "AlertResponse",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "AlertUpdate",
    "CameraEventCreate",
    "CameraEventResponse",
    "CameraEventUpdate",
    "DetectionSource",
    "ComplianceRuleCreate",
    "ComplianceRuleResponse",
    "ComplianceRuleUpdate",
    "CorrectiveActionCreate",
    "CorrectiveActionResponse",
    "CorrectiveActionUpdate",
    "EnvironmentalReadingCreate",
    "EnvironmentalReadingResponse",
    "IncidentCreate",
    "IncidentResponse",
    "IncidentUpdate",
    "InspectionCreate",
    "InspectionResponse",
    "InspectionUpdate",
    "MineCreate",
    "MineResponse",
    "MineUpdate",
    "PaginatedResponse",
    "RestrictedZoneCreate",
    "RestrictedZoneResponse",
    "RestrictedZoneUpdate",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
]
