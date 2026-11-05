"""RLS posture is established by the code path that creates the tables, and reported by `/ready`.

`infra/supabase/rls_posture_apply.sql` has been the one-step fix for the gap described in
`docs/supabase.md`, "Row-level security" -- but it was a *manual* one-step fix. The lifespan runs
`alembic upgrade head` on every start, and on Supabase `ALTER DEFAULT PRIVILEGES` grants `anon`
and `authenticated` on every new table in `public`, so the window between "Alembic created it" and
"a human remembered to paste the script" was an open table.

These are the database-free halves of the fix: the SQLite path must stay untouched (the offline
profile migrates on every start), the lifespan must call the apply immediately after the upgrade,
and `/ready` must carry the posture field. The live-catalogue half is
`test_postgres_integration.py`, gated on the `postgres` marker.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from silverloop import migrations
from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.migrations import apply_rls_posture
from silverloop.sql_repository import SqlAlchemyRepository


def _offline_settings(database_url: str) -> Settings:
    return Settings(
        app_env="development",
        database_url=database_url,
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        llm_enabled=False,
        auth_enabled=False,
    )


def test_apply_rls_posture_is_a_no_op_on_sqlite(tmp_path) -> None:
    """RLS, `pg_policies` and the `anon`/`authenticated` roles are PostgreSQL concepts. The
    offline demo runs the whole lifespan on SQLite, so this has to return without touching the
    connection rather than fail or half-apply."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'offline.db'}"
    repository = SqlAlchemyRepository(database_url)
    try:
        apply_rls_posture(database_url)  # must not raise
        assert repository.readiness("offline").database_backend == "sqlite"
    finally:
        repository.close()


def test_sqlite_readiness_reports_no_open_tables_rather_than_every_table(
    repository: SqlAlchemyRepository,
) -> None:
    """The posture field must read as "nothing to report" off PostgreSQL, not as "every table is
    open" -- SQLite has no `pg_class.relrowsecurity` to be false."""
    assert repository.readiness("offline").tables_without_rls == []


def test_the_lifespan_applies_the_posture_immediately_after_the_migration(
    repository: SqlAlchemyRepository, tmp_path, monkeypatch
) -> None:
    """Order is the whole point: a posture applied before `alembic upgrade head` would miss the
    tables that upgrade creates, which is exactly the gap this closes."""
    calls: list[str] = []
    monkeypatch.setattr(migrations, "upgrade_database", lambda url: calls.append("upgrade"))
    monkeypatch.setattr(migrations, "apply_rls_posture", lambda url: calls.append("posture"))
    monkeypatch.setattr("silverloop.main.upgrade_database", migrations.upgrade_database)
    monkeypatch.setattr("silverloop.main.apply_rls_posture", migrations.apply_rls_posture)

    application = create_app(
        repository,
        settings=_offline_settings(f"sqlite+pysqlite:///{tmp_path / 'lifespan.db'}"),
        migrate_on_start=True,
    )
    with TestClient(application):
        pass

    assert calls == ["upgrade", "posture"]


def test_readiness_exposes_the_posture_over_http(client: TestClient) -> None:
    payload = client.get("/ready").json()

    assert payload["tables_without_rls"] == []
