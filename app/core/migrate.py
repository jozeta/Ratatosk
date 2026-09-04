"""Minimal in-place schema migration for SQLite.

There's no Alembic in this project; new columns added to a model over time
are added to any pre-existing table with `ALTER TABLE ... ADD COLUMN`, so a
running deployment's data (including the seeded admin account) survives an
upgrade instead of requiring a full DB reset.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("securedrop.migrate")

_SQLITE_TYPE_MAP = {
    "BOOLEAN": "BOOLEAN",
    "INTEGER": "INTEGER",
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
}


def sync_table_columns(engine: Engine, model) -> None:
    table = model.__table__
    inspector = inspect(engine)
    if table.name not in inspector.get_table_names():
        return  # brand-new table: create_all() already handled it with full schema

    existing = {col["name"] for col in inspector.get_columns(table.name)}
    with engine.begin() as conn:
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(engine.dialect)
            default_clause = ""
            if column.default is not None and column.default.is_scalar:
                value = column.default.arg
                if isinstance(value, bool):
                    default_clause = f" DEFAULT {1 if value else 0}"
                elif isinstance(value, (int, float)):
                    default_clause = f" DEFAULT {value}"
                elif isinstance(value, str):
                    default_clause = f" DEFAULT '{value}'"
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{default_clause}'
            logger.info("Migrating: %s", ddl)
            conn.execute(text(ddl))
