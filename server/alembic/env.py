from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, make_url, pool

from alembic import context
from silverloop.config import get_settings
from silverloop.db_models import Base
from silverloop.sql_repository import _sync_database_url

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers=False` is load-bearing, not tidiness. The default is True, and
    # `alembic.ini` names only root/sqlalchemy/alembic, so a migration run -- which happens in
    # the API's own lifespan, after `create_app` has already built the loggers -- would switch
    # off `silverloop.request` and `silverloop.agent` for the rest of the process. The structured
    # request log and the planner's provider-failure warning are operator surfaces; they must
    # survive `alembic upgrade head`.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.attributes.get("database_url_configured"):
    database_url = get_settings().database_url
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url))

target_metadata = Base.metadata


def _ensure_sqlite_parent_exists(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _ensure_sqlite_parent_exists(config.get_main_option("sqlalchemy.url"))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
