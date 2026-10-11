"""Idempotent migration: inspection review/approval lifecycle columns.

Adds the NULLABLE columns required by the governance review workflow to
EXISTING databases created before the upgrade (Base.metadata.create_all only
creates missing TABLES; it does not alter existing ones):

    inspections.review_status   TEXT NULL
    inspections.reviewed_by_id  TEXT NULL
    inspections.reviewed_at     TIMESTAMP NULL
    inspections.review_notes    TEXT NULL

Fresh development databases (created via seed_demo.py / create_all) already
have these columns; this script detects and skips them, so it is safe to run
any number of times. No existing column is changed or dropped. Postgres and
SQLite are both supported.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.database.session import Base, engine  # noqa: E402

COLUMNS = {
    "review_status": "VARCHAR(20)",
    "reviewed_by_id": "VARCHAR(36)",
    "review_notes": "TEXT",
    # TIMESTAMP WITH TIME ZONE on Postgres; SQLite ignores the precision part.
    "reviewed_at": "TIMESTAMP",
}


def main() -> int:
    inspector = inspect(engine)
    if "inspections" not in inspector.get_table_names():
        print("inspections table not found — create the schema first (seed_demo.py). Nothing to do.")
        return 0
    existing = {c["name"] for c in inspector.get_columns("inspections")}
    missing = [c for c in COLUMNS if c not in existing]
    if not missing:
        print("inspections review columns already present. Nothing to do.")
        return 0

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    with engine.begin() as conn:
        for col in missing:
            sql_type = COLUMNS[col]
            if is_sqlite:
                ddl = f'ALTER TABLE inspections ADD COLUMN "{col}" {sql_type if col != "reviewed_at" else "DATETIME"}'
            else:
                ddl = f'ALTER TABLE inspections ADD COLUMN IF NOT EXISTS "{col}" {sql_type}'
            print(f"  + inspections.{col}")
            conn.execute(text(ddl))
        # Partial index supported on both backends via WHERE IS NOT NULL.
        if "review_status" in missing:
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_inspections_review_status "
                    "ON inspections (review_status) WHERE review_status IS NOT NULL"
                ))
                print("  + ix_inspections_review_status (partial)")
            except Exception as exc:  # SQLite < 3.8.8 has no partial indexes
                print(f"  ! skipped partial index ({exc}) — add a plain one instead")
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inspections_review_status ON inspections (review_status)"))
                print("  + plain ix_inspections_review_status")
    print("Migration complete.")
    return 0


if __name__ == "__main__":
    # create_all first so a totally fresh DB is also brought up to date.
    Base.metadata.create_all(engine)
    raise SystemExit(main())
