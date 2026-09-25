"""
Pytest fixtures: isolated SQLite database per session + seeded demo rows.

Each run gets a throwaway DB file, so tests never touch the dev or production
database. The app's get_db dependency is overridden to use the test session.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.security import get_current_user
from app.database.session import Base, get_db
from app.main import app
from app.database import models

TEST_DB = Path(__file__).parent / "_test_api.db"


@pytest.fixture(scope="session")
def db_engine():
    TEST_DB.unlink(missing_ok=True)
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{TEST_DB}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("pragma foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def db_session(db_engine):
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    now = datetime.now(timezone.utc)

    session.add_all([
        models.User(id="u-admin-0001", email="admin@test.ai", full_name="Admin", role="admin", hashed_password="x"),
        models.User(id="u-mgr-0001", email="manager@test.ai", full_name="Manager", role="mine_manager", hashed_password="x"),
        models.User(id="u-safe-0001", email="safety@test.ai", full_name="Safety", role="safety_officer", hashed_password="x"),
        models.User(id="u-env-0001", email="env@test.ai", full_name="Env", role="environmental_officer", hashed_password="x"),
        models.Mine(id="m-test-0001", name="Test Mine", code="MINE-TST", mine_type="open_cast",
                    status="operational", location="Testville"),
        models.ComplianceRule(id="r-test-0001", name="PM2.5 limit", parameter="pm2_5", operator=">",
                              threshold=60.0, unit="µg/m³", severity="high", mine_id=None),
        models.RestrictedZone(id="z-test-0001", mine_id="m-test-0001", name="Blast Zone", camera_id="CAM-T1"),
        models.RestrictedZone(id="z-test-0002", mine_id="m-other-0001", name="Other Zone", camera_id="CAM-O1"),
        models.Mine(id="m-other-0001", name="Other Mine", code="MINE-OTH", mine_type="mixed",
                    status="operational", location="Elsewhere"),
        models.EnvironmentalReading(id="rd-test-0001", mine_id="m-test-0001", parameter="pm2_5",
                                    value=90.0, unit="µg/m³", threshold=60.0, status="violation",
                                    source="simulated", recorded_at=now - timedelta(hours=1)),
    ])
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    """TestClient authenticated as admin (admin passes every role check)."""
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    admin = db_session.get(models.User, "u-admin-0001")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def anon_client(db_session):
    """TestClient WITHOUT auth override: requests carry no token -> 401s."""
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def as_role(db_session, client):
    """Re-authenticate the shared client as a different seeded user."""
    def _set(user_id: str):
        user = db_session.get(models.User, user_id)
        app.dependency_overrides[get_current_user] = lambda: user
        return user
    return _set
