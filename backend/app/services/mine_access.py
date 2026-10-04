"""Mine-scope authorization for live webcam detection.

Implemented on the BACKEND so a crafted request (e.g. a changed ``mine_id``)
can never reach another mine's camera pipeline — the frontend gate is only a
convenience. Scope rules by role (no new roles; the four existing values):

    admin                  every mine
    mine_manager           only mines where ``mines.manager_id == user.id``
    safety_officer         only mines listed in ``users.permitted_mine_ids``
    environmental_officer  only mines listed in ``users.permitted_mine_ids``

``mine_manager`` keeps using the existing manager assignment on the mine row;
officers get an explicit per-user assignment list (``users.permitted_mine_ids``,
admin-managed via the ordinary user-update endpoint). An empty list means the
officer has NO live-detection mines — access is never granted implicitly.

Denials are explicit 403s with actionable messages; this module never
downgrades to a warning.
"""
from fastapi import HTTPException

from app.database.models import Mine, User

# Roles that may use live detection at all (admin is always allowed). The
# per-mine scope for each of these is enforced below.
LIVE_DETECTION_ROLES = {"mine_manager", "safety_officer", "environmental_officer"}

_MSG_NOT_PERMITTED = (
    "Live detection is not permitted for your role. "
    "Allowed roles: administrator, government officer, mine manager, safety officer."
)
_MSG_NOT_YOUR_MINE = (
    "Live detection is restricted to your assigned mine "
    "(the mine where you are registered as the manager)."
)
_MSG_NOT_PERMITTED_MINE = (
    "Live detection is restricted to the mines assigned to you. "
    "Ask an administrator to add this mine to your permitted mines."
)


def ensure_mine_access(user: User, mine: Mine) -> None:
    """Raise HTTP 403 unless ``user`` may run live detection on ``mine``.

    Called by the live-frame endpoint AFTER the mine's existence check, so
    unknown mines keep their existing error and real users get precise 403s.
    """
    role = user.role
    if role == "admin":
        return
    if role not in LIVE_DETECTION_ROLES:
        raise HTTPException(status_code=403, detail=_MSG_NOT_PERMITTED)
    if role == "mine_manager":
        if mine.manager_id != user.id:
            raise HTTPException(status_code=403, detail=_MSG_NOT_YOUR_MINE)
        return
    # safety_officer / environmental_officer: explicit assignment list only.
    permitted = user.permitted_mine_ids or []
    if mine.id not in permitted:
        raise HTTPException(status_code=403, detail=_MSG_NOT_PERMITTED_MINE)
