"""Alembic environment: uses the application's engine and metadata, so
migrations always target the same database the app is configured for."""
from alembic import context

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.core.database import Base
from app.core.database import engine as app_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=str(app_engine.url), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = context.config.attributes.get("connection_engine", app_engine)
    with engine.connect() as connection:
        # render_as_batch: SQLite can't ALTER most column properties in place;
        # batch mode recreates the table, so future migrations work there too.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
