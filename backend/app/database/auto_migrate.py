"""Additive, idempotent schema self-heal run at API start-up.

Why: ``Base.metadata.create_all`` creates missing *tables* but never adds new
*columns* to existing ones. When a release adds a column (e.g.
``users.must_change_password`` / ``users.token_version``) and the SQL file in
``database/migrations`` was not applied by hand, every query touching the table
fails with "column does not exist" -> HTTP 500 "Internal database error"
(login included).

This module only ever ADDS: missing tables and missing columns. It never drops,
renames or rewrites anything, so it is safe on a production database. Any
failure is logged and swallowed so it can never stop the API from booting.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn

logger = logging.getLogger(__name__)


def ensure_schema(engine: Engine) -> list[str]:
    """Create missing tables and add missing columns. Returns what was changed."""
    # Imported here so every model is registered on Base.metadata first.
    from app.database import models  # noqa: F401
    from app.database.session import Base

    changes: list[str] = []
    try:
        Base.metadata.create_all(engine)  # checkfirst: only absent tables

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                # Adding NOT NULL without a default would fail on populated
                # tables; relax it unless the column carries a server default.
                if column.server_default is None and not column.nullable:
                    ddl = ddl.replace(" NOT NULL", "")
                stmt = f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'
                try:
                    with engine.begin() as conn:
                        conn.execute(text(stmt))
                    changes.append(f"{table.name}.{column.name}")
                    logger.warning("Schema self-heal: added %s.%s", table.name, column.name)
                except Exception as exc:  # noqa: BLE001 - never block start-up
                    logger.error("Schema self-heal failed for %s.%s: %s", table.name, column.name, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Schema self-heal skipped: %s", exc)
    return changes
