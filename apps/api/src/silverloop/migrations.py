import logging
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic import command
from silverloop.sql_repository import _sync_database_url

_LOGGER = logging.getLogger("silverloop.migrations")

# `apps/api/src/silverloop/migrations.py` -> repository root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
RLS_POSTURE_APPLY_SQL = _REPO_ROOT / "infra" / "supabase" / "rls_posture_apply.sql"


def upgrade_database(database_url: str) -> None:
    api_root = Path(__file__).parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    command.upgrade(config, "head")


def apply_rls_posture(database_url: str) -> None:
    """Re-establish the browser-deny posture on every public ORM table. No-op off PostgreSQL.

    Alembic creates the tables; nothing in that path made them safe. On Supabase,
    `ALTER DEFAULT PRIVILEGES` grants `anon` and `authenticated` on every new table in `public`,
    so the window between "the lifespan ran `alembic upgrade head`" and "a human pasted
    `infra/supabase/rls_posture_apply.sql`" was an open table -- a gap `docs/supabase.md` records
    happening three times. Running the same file from the same lifespan, immediately after the
    upgrade, closes that window for existing databases as well as new ones, touches no applied
    migration, and derives its table list from `Base.metadata` (via the file's own array, pinned
    to the ORM by `test_rls_posture_apply.py`) so it cannot drift.

    The file is executed byte-for-byte through the raw driver cursor, exactly as
    `test_postgres_integration._execute_plpgsql` does and for the same two reasons: SQLAlchemy's
    `text()` reads a `:name` inside a `$$ ... $$` body as a bind parameter, and
    `exec_driver_sql` hands psycopg a parameter sequence, which makes it parse the file's own
    `format('... %I ...', t)` calls as placeholders and reject `%I`. It is naturally idempotent
    (`enable row level security`, `no force`, `revoke`; the one `create policy` is guarded by a
    `pg_policies` lookup), so running it on every start is a no-op once the posture holds.

    Failures are logged, not raised. The posture is a property of the database, and a database
    that refuses it is exactly what `/ready`'s `tables_without_rls` exists to report -- crashing
    the process would take away the surface that names the problem. One known cause is a
    non-Supabase PostgreSQL, where `anon`/`authenticated` do not exist and the script's `revoke`
    aborts its own block; see `docs/supabase.md`.
    """
    url = _sync_database_url(database_url)
    if make_url(url).get_backend_name() != "postgresql":
        # SQLite (the offline profile migrates on every start) has no RLS, no `pg_policies` and
        # no Data API roles. Returning here is the whole of the SQLite path.
        return

    if not RLS_POSTURE_APPLY_SQL.exists():
        # A deployment that ships `apps/api` without `infra/` still starts; it simply cannot
        # establish the posture, and `/ready` says so.
        _LOGGER.error(
            "rls_posture_apply_missing",
            extra={"path": str(RLS_POSTURE_APPLY_SQL)},
        )
        return

    statement = RLS_POSTURE_APPLY_SQL.read_text()
    engine = create_engine(url)
    try:
        with engine.begin() as connection, connection.connection.cursor() as cursor:
            cursor.execute(statement)
    except Exception as exc:  # noqa: BLE001 -- driver errors bypass SQLAlchemy's wrapping
        _LOGGER.error("rls_posture_apply_failed", extra={"error": str(exc)})
    finally:
        engine.dispose()
