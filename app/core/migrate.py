"""Database schema management with Alembic (ARCH-002).

The old approach (`sync_table_columns`) could only ever *add* columns, and
wasn't even run for every table. Schema changes are now Alembic revisions in
`migrations/versions/`. To add one:

    alembic revision --autogenerate -m "describe the change"

and review the generated file.

Existing databases created before Alembic was introduced have no
`alembic_version` table. On their first start they are brought up to the
baseline schema with the legacy additive sync (safe: every change up to the
baseline only added tables and columns) and then stamped, after which normal
Alembic upgrades apply.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.database import Base, engine

logger = logging.getLogger("ratatosk.migrate")

ROOT = Path(__file__).resolve().parent.parent.parent
# Data changes made by Alembic revisions, re-applied for pre-Alembic
# databases (which are stamped at head without running the revisions).
# Every statement must be idempotent.
LEGACY_DATA_MIGRATIONS = [
    # 0002_rename_default_brand
    "UPDATE system_settings SET brand_name = 'Ratatosk', version = version + 1 WHERE brand_name = 'SecureDrop'",
    "UPDATE system_settings SET smtp_from_name = 'Ratatosk' WHERE smtp_from_name = 'SecureDrop'",
]

_SQLITE_TYPE_MAP = {"BOOLEAN": "BOOLEAN", "INTEGER": "INTEGER", "VARCHAR": "VARCHAR", "TEXT": "TEXT"}


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection_engine"] = engine
    return cfg


def sync_table_columns(engine: Engine, model) -> None:
    """Legacy additive sync: ALTER TABLE ADD COLUMN for any model column a
    pre-Alembic database is missing. Only used once, before stamping."""
    table = model.__table__
    inspector = inspect(engine)
    if table.name not in inspector.get_table_names():
        return
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
                    escaped = value.replace("'", "''")
                    default_clause = f" DEFAULT '{escaped}'"
            not_null = " NOT NULL" if (not column.nullable and default_clause) else ""
            logger.info("Adding missing column %s.%s", table.name, column.name)
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}{default_clause}{not_null}'))


def run_migrations() -> None:
    import app.models  # noqa: F401 - register every model on Base.metadata

    tables = set(inspect(engine).get_table_names())
    cfg = alembic_config()
    if "alembic_version" not in tables and tables & {"users", "files", "system_settings"}:
        # A pre-Alembic (1.x) database. Its schema is brought straight to the
        # *current* models with the additive sync (every change since 1.x only
        # added tables and columns), so it's stamped at head - running the
        # schema revisions on top would recreate what already exists. Data
        # migrations are applied explicitly instead.
        logger.warning("Pre-Alembic database detected - bringing it to the current schema and stamping it")
        Base.metadata.create_all(bind=engine)
        for mapper in Base.registry.mappers:
            sync_table_columns(engine, mapper.class_)
        with engine.begin() as conn:
            for statement in LEGACY_DATA_MIGRATIONS:
                conn.execute(text(statement))
        command.stamp(cfg, "head")
        return
    command.upgrade(cfg, "head")
