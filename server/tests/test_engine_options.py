"""Connection pool options for a server database, checked without connecting to one.

`create_engine` is lazy: building an engine opens no connection, so the pool it configures can be
inspected against a placeholder URL that points nowhere.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool

from silverloop.config import Settings
from silverloop.sql_repository import SqlAlchemyRepository, _engine_options

POOLER_URL = "postgresql+psycopg://user:secret@pooler.invalid:5432/postgres?sslmode=require"

_POOL_ENV = (
    "DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "DATABASE_POOL_RECYCLE_SECONDS",
    "DATABASE_POOL_PRE_PING",
    "DATABASE_POOL_USE_LIFO",
    "DATABASE_POOL_PING_IDLE_SECONDS",
    "DATABASE_POOL_KEEPALIVES",
    "DATABASE_POOL_KEEPALIVES_IDLE_SECONDS",
    "DATABASE_POOL_KEEPALIVES_INTERVAL_SECONDS",
    "DATABASE_POOL_KEEPALIVES_COUNT",
)


@pytest.fixture
def default_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # `pnpm test` can load the developer's `.env` into the environment; the defaults are the
    # subject here, so none of the pool variables may arrive from outside.
    for name in _POOL_ENV:
        monkeypatch.delenv(name, raising=False)
    return Settings()


def test_server_database_defaults_skip_pre_ping_use_lifo_recycle_early_and_keep_alive(
    default_settings: Settings,
) -> None:
    options = _engine_options(POOLER_URL, settings=default_settings)

    assert options == {
        "pool_pre_ping": False,
        "pool_recycle": 120,
        "pool_size": 10,
        "max_overflow": 4,
        "pool_use_lifo": True,
        "connect_args": {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    }
    # The most connections one process holds stays under the session pooler's 15-client cap.
    assert int(options["pool_size"]) + int(options["max_overflow"]) < 15


def test_pool_and_keepalive_settings_are_overridable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_POOL_SIZE", "3")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DATABASE_POOL_RECYCLE_SECONDS", "60")
    monkeypatch.setenv("DATABASE_POOL_PRE_PING", "true")
    monkeypatch.setenv("DATABASE_POOL_USE_LIFO", "false")
    monkeypatch.setenv("DATABASE_POOL_KEEPALIVES_IDLE_SECONDS", "15")
    monkeypatch.setenv("DATABASE_POOL_KEEPALIVES_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("DATABASE_POOL_KEEPALIVES_COUNT", "2")

    options = _engine_options(POOLER_URL, settings=Settings())

    assert options == {
        "pool_pre_ping": True,
        "pool_recycle": 60,
        "pool_size": 3,
        "max_overflow": 1,
        "pool_use_lifo": False,
        "connect_args": {
            "keepalives": 1,
            "keepalives_idle": 15,
            "keepalives_interval": 5,
            "keepalives_count": 2,
        },
    }


def test_keepalives_can_be_switched_off(default_settings: Settings) -> None:
    settings = default_settings.model_copy(update={"database_pool_keepalives": False})

    assert "connect_args" not in _engine_options(POOLER_URL, settings=settings)


def test_a_keepalive_written_into_the_url_wins(default_settings: Settings) -> None:
    url = f"{POOLER_URL}&keepalives_idle=90"

    connect_args = _engine_options(url, settings=default_settings)["connect_args"]

    assert "keepalives_idle" not in connect_args
    assert connect_args["keepalives"] == 1
    assert connect_args["keepalives_count"] == 3


def test_psycopg2_urls_get_keepalives_too(default_settings: Settings) -> None:
    options = _engine_options(
        "postgresql://user:secret@pooler.invalid/postgres", settings=default_settings
    )

    assert options["connect_args"]["keepalives"] == 1


def test_a_non_libpq_driver_gets_no_libpq_parameters(default_settings: Settings) -> None:
    options = _engine_options(
        "postgresql+pg8000://user:secret@pooler.invalid/postgres", settings=default_settings
    )

    assert "connect_args" not in options
    assert options["pool_recycle"] == 120


def test_sqlite_keeps_its_own_options(default_settings: Settings) -> None:
    assert _engine_options("sqlite+pysqlite:///:memory:", settings=default_settings) == {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    file_options = _engine_options("sqlite+pysqlite:///./.demo/x.db", settings=default_settings)
    assert "poolclass" not in file_options
    assert "pool_recycle" not in file_options


def test_the_engine_is_built_with_the_pool_options_without_connecting(
    default_settings: Settings,
) -> None:
    engine = SqlAlchemyRepository._create_engine(POOLER_URL, settings=default_settings)
    try:
        pool = engine.pool
        assert pool.size() == 10  # type: ignore[attr-defined]
        assert pool._recycle == 120
        assert pool._pre_ping is False
        assert pool._pool.use_lifo is True  # type: ignore[attr-defined]
        # The idle ping stands in for the pre-ping: a checkout listener, installed without
        # connecting.
        assert len(pool.dispatch.checkout) == 1
        assert len(pool.dispatch.checkin) == 1
        assert pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        engine.dispose()


def test_the_idle_ping_is_not_installed_when_every_checkout_pre_pings(
    default_settings: Settings,
) -> None:
    settings = default_settings.model_copy(update={"database_pool_pre_ping": True})
    engine = SqlAlchemyRepository._create_engine(POOLER_URL, settings=settings)
    try:
        assert engine.pool._pre_ping is True
        assert len(engine.pool.dispatch.checkout) == 0
    finally:
        engine.dispose()


def test_the_idle_ping_threshold_is_overridable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_POOL_PING_IDLE_SECONDS", raising=False)
    assert Settings().database_pool_ping_idle_seconds == 30.0
    monkeypatch.setenv("DATABASE_POOL_PING_IDLE_SECONDS", "5")
    assert Settings().database_pool_ping_idle_seconds == 5.0


def test_sqlite_gets_no_idle_ping(default_settings: Settings) -> None:
    engine = SqlAlchemyRepository._create_engine(
        "sqlite+pysqlite:///:memory:", settings=default_settings
    )
    try:
        assert len(engine.pool.dispatch.checkout) == 0
    finally:
        engine.dispose()
