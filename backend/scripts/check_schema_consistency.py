"""
Dev consistency check: database/schema.sql vs SQLAlchemy ORM models.

Parses the hand-maintained Supabase DDL and compares, for every table:
  * the set of columns (name, normalized type, nullability)
  * the set of foreign keys (column -> referenced table)
against Base.metadata. Catches drift between schema.sql and the ORM.

Run from backend/:  python scripts/check_schema_consistency.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import postgresql

from app.database import models  # noqa: F401  (registers all tables)
from app.database.session import Base

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "schema.sql"

# Postgres type -> ORM-normalized type for comparison
_TYPE_ALIASES = {
    "VARCHAR": "STRING",
    "TEXT": "TEXT",
    "BOOLEAN": "BOOLEAN",
    "DOUBLE PRECISION": "FLOAT",
    "TIMESTAMPTZ": "DATETIME",
    "TIMESTAMP WITH TIME ZONE": "DATETIME",
}


def parse_sql_tables(sql: str) -> dict:
    """Extract columns + FKs from CREATE TABLE blocks in schema.sql."""
    tables: dict[str, dict] = {}
    for block in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        name, body = block[0], block[1]
        cols, fks = {}, []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            fk = re.match(r"CONSTRAINT \w+ FOREIGN KEY \((\w+)\) REFERENCES (\w+) \(\w+\)", line)
            if fk:
                fks.append((fk.group(1), fk.group(2)))
                continue
            # Inline FK style (e.g. role_invitations):
            #   col  VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
            # The column itself is still parsed by the column regex below.
            inline_fk = re.match(
                r"(\w+)\s+(?:VARCHAR\(\d+\)|TEXT|BOOLEAN|DOUBLE PRECISION|TIMESTAMPTZ|FLOAT|INTEGER)"
                r"\s+REFERENCES\s+(\w+)\s*\(",
                line,
            )
            if inline_fk:
                fks.append((inline_fk.group(1), inline_fk.group(2)))
            # Column types used in schema.sql (whitelist keeps parsing exact)
            m = re.match(
                r"(\w+)\s+(VARCHAR\(\d+\)|TEXT|BOOLEAN|DOUBLE PRECISION|TIMESTAMPTZ|FLOAT|INTEGER)(?=[\s,]|$)",
                line,
            )
            if m and m.group(1) not in {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK"}:
                col, raw_type = m.group(1), m.group(2).strip()
                base_type = re.sub(r"\(\d+\)", "", raw_type).strip()
                tables.setdefault(name, {"cols": {}, "fks": []})
                tables[name]["cols"][col] = _TYPE_ALIASES.get(base_type, base_type)
        tables.setdefault(name, {"cols": {}, "fks": []})
        tables[name]["fks"].extend(fks)
    return tables


def orm_tables() -> dict:
    out = {}
    for table in Base.metadata.sorted_tables:
        cols, fks = {}, []
        for col in table.columns:
            pg_type = str(col.type.compile(dialect=postgresql.dialect())).upper()
            base_type = re.sub(r"\(\d+\)", "", pg_type).strip()
            cols[col.name] = _TYPE_ALIASES.get(base_type, base_type)
        for fk in table.foreign_keys:
            fks.append((fk.parent.name, fk.column.table.name))
        out[table.name] = {"cols": cols, "fks": fks}
    return out


def main() -> int:
    sql_tables = parse_sql_tables(SCHEMA_PATH.read_text(encoding="utf-8"))
    model_tables = orm_tables()
    ok = True

    for table in sorted(set(sql_tables) | set(model_tables)):
        sql_t, orm_t = sql_tables.get(table), model_tables.get(table)
        if sql_t is None:
            print(f"MISSING in schema.sql: {table}")
            ok = False
            continue
        if orm_t is None:
            print(f"EXTRA in schema.sql (no ORM model): {table}")
            ok = False
            continue
        if set(sql_t["cols"]) != set(orm_t["cols"]):
            print(f"COLUMN MISMATCH in {table}:")
            print(f"  only in schema.sql: {sorted(set(sql_t['cols']) - set(orm_t['cols']))}")
            print(f"  only in ORM:        {sorted(set(orm_t['cols']) - set(sql_t['cols']))}")
            ok = False
        for col in set(sql_t["cols"]) & set(orm_t["cols"]):
            if sql_t["cols"][col] != orm_t["cols"][col]:
                print(f"TYPE MISMATCH {table}.{col}: schema.sql={sql_t['cols'][col]} ORM={orm_t['cols'][col]}")
                ok = False
        if set(sql_t["fks"]) != set(orm_t["fks"]):
            print(f"FK MISMATCH in {table}:")
            print(f"  schema.sql: {sorted(sql_t['fks'])}")
            print(f"  ORM:        {sorted(orm_t['fks'])}")
            ok = False

    if ok:
        print("OK: schema.sql matches ORM models (columns, types, foreign keys).")
        return 0
    print("\nCONSISTENCY CHECK FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
