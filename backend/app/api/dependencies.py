"""Shared dependencies used across API routers."""
from typing import Annotated

from fastapi import Depends, Query

from app.core.security import CurrentUser


def pagination_params(
    skip: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=200, description="Max records to return")] = 100,
) -> dict:
    return {"skip": skip, "limit": limit}


PaginationParams = Annotated[dict, Depends(pagination_params)]
