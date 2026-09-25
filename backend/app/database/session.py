"""
Database engine and session management.

Uses `DATABASE_URL` from settings:
- Supabase PostgreSQL connection string in production.
- Local SQLite file fallback for development (clearly a dev convenience).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def _build_engine_args() -> dict:
    # SQLite needs check_same_thread=False for FastAPI's threadpool.
    if settings.is_sqlite:
        return {"connect_args": {"check_same_thread": False}}
    # Supabase Postgres: enforce TLS and reuse pooled connections.
    return {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {"sslmode": "require"},
    }


engine = create_engine(settings.DATABASE_URL, **_build_engine_args())
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Session:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
