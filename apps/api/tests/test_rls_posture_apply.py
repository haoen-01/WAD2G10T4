"""`infra/supabase/rls_posture_apply.sql` names every table the ORM defines, and nothing else.

This is deliberately a fast, database-free unit test: it parses the guarded-table array out
of the SQL file as plain text and compares it against `Base.metadata`, the same source of
truth Alembic itself uses. It cannot prove the SQL actually establishes the posture on a
live PostgreSQL server -- that is `test_postgres_integration.py`'s job, gated on CI's
`postgres` marker -- but it does prove a newly added table cannot silently go uncovered,
without needing a database to say so.
"""

from __future__ import annotations

import re
from pathlib import Path

from silverloop.db_models import Base

REPO_ROOT = Path(__file__).resolve().parents[3]
APPLY_SQL_PATH = REPO_ROOT / "infra" / "supabase" / "rls_posture_apply.sql"

_ARRAY_RE = re.compile(r"array\[(.*?)\]", re.DOTALL)
_QUOTED_NAME_RE = re.compile(r"'([a-zA-Z_][a-zA-Z0-9_]*)'")


def _guarded_tables() -> list[str]:
    text = APPLY_SQL_PATH.read_text()
    match = _ARRAY_RE.search(text)
    assert match, f"no 'array[...]' literal found in {APPLY_SQL_PATH}"
    return _QUOTED_NAME_RE.findall(match.group(1))


def _orm_tablenames() -> set[str]:
    names = set(Base.metadata.tables.keys())
    assert names, "Base.metadata has no tables -- db_models.py or the import path is stale"
    return names


def test_rls_posture_apply_names_every_orm_table() -> None:
    guarded = _guarded_tables()
    missing = _orm_tablenames() - set(guarded)
    assert not missing, (
        f"tables defined in db_models.py but missing from the guarded-table array in "
        f"{APPLY_SQL_PATH.name}: {sorted(missing)}"
    )


def test_rls_posture_apply_names_no_table_the_orm_does_not_define() -> None:
    guarded = _guarded_tables()
    extra = set(guarded) - _orm_tablenames()
    assert not extra, (
        f"{APPLY_SQL_PATH.name} names tables the ORM does not define (typo, or a table "
        f"removed from db_models.py without removing it here): {sorted(extra)}"
    )


def test_rls_posture_apply_has_no_duplicate_table_names() -> None:
    guarded = _guarded_tables()
    assert len(guarded) == len(set(guarded)), (
        f"{APPLY_SQL_PATH.name} names a table more than once: "
        f"{sorted({t for t in guarded if guarded.count(t) > 1})}"
    )


def _strip_sql_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))


def test_rls_posture_apply_contains_no_schema_or_data_statements() -> None:
    """The whole point of this file is that it cannot fail because of table existence. Pin
    that it never contains the statement kinds that could turn it back into a script the
    live-project rollback failure can happen to again. Comment lines are stripped first: the
    file's own prose explains this property using the words it must not contain as SQL."""
    text = _strip_sql_comments(APPLY_SQL_PATH.read_text().lower())
    for forbidden in (
        "create table",
        "drop table",
        "alter table public.%i add column",
        "insert into",
        "update public.",
        "delete from",
    ):
        assert forbidden not in text, f"{APPLY_SQL_PATH.name} contains a {forbidden!r} statement"
