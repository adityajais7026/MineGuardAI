"""
Generic CRUD service layer.

Every entity router builds a CrudService around its ORM model + schemas so
list/create/get/update/delete behaviour stays consistent (pagination,
filtering, sorting, 404 handling) with minimal duplication.

Phase 4 note: services raise HTTPException directly — appropriate for this
scale; an exception-mapping layer can be added later if services are reused
outside the API layer.
"""
from typing import Any, Sequence

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.orm import Session


class CrudService:
    """Reusable CRUD operations for one ORM model."""

    def __init__(self, model: type, default_order: str = "created_at"):
        self.model = model
        self.default_order = default_order
        self._pk = sa_inspect(model).primary_key[0].name
        self._columns = {c.key for c in sa_inspect(model).attrs}

    # ------------------------------------------------------------------
    def list(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        sort: str | None = None,
        order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        """Return (items, total). Whitelisted equality filters + safe sorting."""
        query = select(self.model)
        for field, value in (filters or {}).items():
            if value is not None and field in self._columns:
                query = query.where(getattr(self.model, field) == value)

        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

        sort_field = sort if sort in self._columns else self.default_order
        order_col = getattr(self.model, sort_field)
        query = query.order_by(order_col.desc() if order == "desc" else order_col.asc())

        items = db.execute(query.offset(skip).limit(limit)).scalars().all()
        return items, total

    # ------------------------------------------------------------------
    def get(self, db: Session, entity_id: str) -> Any:
        entity = db.get(self.model, entity_id)
        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{self.model.__tablename__} '{entity_id}' not found",
            )
        return entity

    # ------------------------------------------------------------------
    def create(self, db: Session, data: BaseModel) -> Any:
        payload = data.model_dump(exclude_unset=True)
        # Ignore client-supplied timestamps; DB defaults own them.
        for ts in ("created_at", "updated_at"):
            payload.pop(ts, None)
        entity = self.model(**payload)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    # ------------------------------------------------------------------
    def update(self, db: Session, entity_id: str, data: BaseModel) -> Any:
        entity = self.get(db, entity_id)
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            if field in self._columns:
                setattr(entity, field, value)
        db.commit()
        db.refresh(entity)
        return entity

    # ------------------------------------------------------------------
    def delete(self, db: Session, entity_id: str) -> None:
        entity = self.get(db, entity_id)
        db.delete(entity)
        db.commit()
