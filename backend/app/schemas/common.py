"""Common API response wrappers for consistent frontend consumption."""
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated list envelope."""

    items: list[T]
    total: int
    skip: int
    limit: int
