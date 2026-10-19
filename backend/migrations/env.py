"""Alembic environment.

Used two ways:
- by the application (db.init_db), which passes an open connection in
  config.attributes["connection"] so migrations run inside its lock;
- by the `alembic` command line, which connects to FRUIT_FLY_DATABASE_URL.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from backend.app.config import Settings
from backend.app.db import Base, make_engine
from backend.migrations.autogen import compare_type, render_item

config = context.config
target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=compare_type,
        render_item=render_item,
        # SQLite can't ALTER most things; batch mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = make_engine(Settings.from_env().database_url)
    with engine.connect() as conn:
        run(conn)
    engine.dispose()