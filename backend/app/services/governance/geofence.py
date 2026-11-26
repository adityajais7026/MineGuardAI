"""GPS / geofence verification.

Real coordinates only: the server never generates or "fixes" a GPS value.
Verification answers one of three states — inside | outside | unavailable —
and OUTSIDE is a warning, never a silent auto-pass.
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Geofence

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """Ray-casting point-in-polygon; polygon is [[lat, lng], ...]."""
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        lat_i, lng_i = polygon[i][0], polygon[i][1]
        lat_j, lng_j = polygon[j][0], polygon[j][1]
        if (lng_i > lng) != (lng_j > lng):
            intersect_lat = (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i) + lat_i
            if lat < intersect_lat:
                inside = not inside
        j = i
    return inside


def verify_location(db: Session, mine_id: str, lat: float | None, lng: float | None) -> dict:
    """Classify a device GPS point against the mine's active geofence(s)."""
    if lat is None or lng is None:
        return {"status": "unavailable", "message": "Location unavailable — device did not provide GPS coordinates."}
    fences = db.execute(
        select(Geofence).where(Geofence.mine_id == mine_id, Geofence.is_active.is_(True))
    ).scalars().all()
    if not fences:
        return {"status": "unavailable", "message": "No geofence configured for this mine."}

    for f in fences:
        if f.boundary_type == "radius":
            if f.center_lat is None or f.center_lng is None or f.radius_m is None:
                continue
            if haversine_m(lat, lng, f.center_lat, f.center_lng) <= f.radius_m:
                return {"status": "inside", "geofence_id": f.id}
        else:
            if f.polygon_json and _point_in_polygon(lat, lng, f.polygon_json):
                return {"status": "inside", "geofence_id": f.id}
    return {"status": "outside", "message": "Location is outside the authorized mine boundary."}
