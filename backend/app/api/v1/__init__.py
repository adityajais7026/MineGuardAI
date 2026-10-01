"""All v1 API routers, aggregated for registration in main.py."""
from app.api.v1 import (
    alerts,
    ai,
    auth,
    camera_events,
    compliance,
    compliance_rules,
    corrective_actions,
    dashboard,
    detect,
    environmental_readings,
    incidents,
    inspections,
    live_detect,
    mines,
    restricted_zones,
    risk,
    user_management,
    users,
)

all_routers = [
    auth.router,
    user_management.router,  # static /users routes must precede users' /{user_id}
    users.router,
    mines.router,
    compliance_rules.router,
    environmental_readings.router,
    compliance.router,
    risk.router,
    dashboard.router,
    ai.router,
    detect.router,
    live_detect.router,
    restricted_zones.router,
    camera_events.router,
    alerts.router,
    incidents.router,
    inspections.router,
    corrective_actions.router,
]

__all__ = ["all_routers"]
