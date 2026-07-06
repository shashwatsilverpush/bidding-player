"""Alembic environment — async engine, autogenerate target = app models."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context

# Import Base + all models so target_metadata is fully populated.
from app.db import Base
from app.models import *  # noqa: F401,F403  (registers tables on Base.metadata)
from app.settings import get_settings
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the real (async) DB URL from settings, stripping libpq-only params
# (sslmode/channel_binding) asyncpg rejects; SSL is passed via connect_args.
from app.db import async_engine_args  # noqa: E402

_db_url, _db_connect_args = async_engine_args(get_settings().database_url)
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
        connect_args=_db_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
