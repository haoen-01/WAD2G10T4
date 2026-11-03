"""The Supabase RLS mirror has drifted twice already (see `docs/supabase.md`, "Known drift").

`infra/supabase/migrations/*.sql` is hand-applied and hand-written -- nothing runs it in CI, and
nothing previously asserted that every table Alembic knows about actually gets `enable row level
security` plus a `deny_browser_access` policy for `anon`/`authenticated` in that directory. This
test closes that gap with plain string/regex parsing over the `.sql` files -- no database, no
`sqlparse` dependency -- because the property it pins ("every table is covered") only needs to
survive a bare-metal read of the files, and a parser this simple stays honest about exactly what
it checked.

It intentionally does not try to be a general SQL parser. Two mirror-writing patterns exist in
this directory (see the file's own comments): a table named directly in `alter table
public.<name> enable row level security` / `create policy deny_browser_access on public.<name>`,
and a `do $$ ... foreach <var> in array array['a', 'b', ...] ... %I ... $$` block that applies the
same two statements to every name in the array. Both are covered below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "infra" / "supabase" / "migrations"
ALEMBIC_VERSIONS_DIR = REPO_ROOT / "server" / "alembic" / "versions"
DB_MODELS_PATH = REPO_ROOT / "server" / "src" / "silverloop" / "db_models.py"

_TABLENAME_RE = re.compile(r'__tablename__\s*=\s*"(\w+)"')
_DIRECT_RLS_RE = re.compile(r"alter table public\.(\w+)\s+enable row level security", re.IGNORECASE)
_DIRECT_DENY_RE = re.compile(r"deny_browser_access on public\.(\w+)\b", re.IGNORECASE)
_FOREACH_ARRAY_RE = re.compile(r"foreach\s+(\w+)\s+in array array\[([^\]]+)\]", re.IGNORECASE)
_QUOTED_NAME_RE = re.compile(r"'([a-zA-Z_][a-zA-Z0-9_]*)'")
_REVISION_RE = re.compile(r'^revision:\s*str\s*=\s*"(\w+)"', re.MULTILINE)
_DOWN_REVISION_RE = re.compile(r'^down_revision:\s*str\s*\|\s*None\s*=\s*"?(\w+)"?', re.MULTILINE)
_MIRROR_BUMP_RE = re.compile(
    r"update public\.alembic_version\s+set version_num\s*=\s*'(\w+)'", re.IGNORECASE
)


def _migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, f"no migration files found under {MIGRATIONS_DIR}"
    return files


def _tablenames_in_db_models() -> set[str]:
    text = DB_MODELS_PATH.read_text()
    names = set(_TABLENAME_RE.findall(text))
    assert names, "no __tablename__ declarations found -- the regex or the path is stale"
    return names


def _dynamic_block_span(text: str, match: re.Match[str]) -> str:
    """The enclosing `do $$ ... $$;` block for one `foreach ... in array array[...]` match.

    Falls back to the whole file when no `do $$` is found before it, which only makes the
    coverage check stricter (a table would need to appear in the whole file's RLS/deny text, not
    just its own block) rather than silently passing something it should not.
    """
    start = text.rfind("do $$", 0, match.start())
    end = text.find("$$;", match.end())
    if start == -1 or end == -1:
        return text
    return text[start:end]


def _rls_and_deny_coverage() -> tuple[set[str], set[str]]:
    """Every table with RLS enabled, and every table with a `deny_browser_access` policy, across
    the whole mirror directory -- literal table names plus names bound through a `foreach`/array
    loop applied with `%I` inside the same `do` block.
    """
    rls_tables: set[str] = set()
    deny_tables: set[str] = set()

    for path in _migration_files():
        text = path.read_text()
        rls_tables.update(_DIRECT_RLS_RE.findall(text))
        deny_tables.update(_DIRECT_DENY_RE.findall(text))

        for match in _FOREACH_ARRAY_RE.finditer(text):
            names = set(_QUOTED_NAME_RE.findall(match.group(2)))
            block = _dynamic_block_span(text, match)
            if "enable row level security" in block:
                rls_tables.update(names)
            if "deny_browser_access" in block:
                deny_tables.update(names)

    return rls_tables, deny_tables


def _alembic_heads() -> set[str]:
    """Revisions with no other revision naming them as `down_revision` -- the head(s) of the
    Alembic graph, read straight from the migration scripts rather than trusting a cached value.
    """
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for path in sorted(ALEMBIC_VERSIONS_DIR.glob("*.py")):
        text = path.read_text()
        revision_match = _REVISION_RE.search(text)
        if not revision_match:
            continue
        revisions.add(revision_match.group(1))
        down_match = _DOWN_REVISION_RE.search(text)
        if down_match and down_match.group(1) not in ("None", ""):
            down_revisions.add(down_match.group(1))
    heads = revisions - down_revisions
    assert heads, "no Alembic head found -- the revision/down_revision regex may be stale"
    return heads


def test_every_orm_table_has_rls_enabled_in_the_mirror() -> None:
    rls_tables, _ = _rls_and_deny_coverage()
    missing = _tablenames_in_db_models() - rls_tables
    assert not missing, (
        f"tables with no 'enable row level security' statement in "
        f"infra/supabase/migrations/*.sql: {sorted(missing)}"
    )


def test_every_orm_table_has_a_deny_browser_access_policy_in_the_mirror() -> None:
    _, deny_tables = _rls_and_deny_coverage()
    missing = _tablenames_in_db_models() - deny_tables
    assert not missing, (
        f"tables with no 'deny_browser_access' policy for anon/authenticated in "
        f"infra/supabase/migrations/*.sql: {sorted(missing)}"
    )


def test_the_newest_mirror_file_bumps_alembic_version_to_the_current_head() -> None:
    """`/ready` compares the live Alembic revision to the repo head; the mirror's own
    `alembic_version` bump has to track the same head, or a hand-applied Supabase database ends
    up reporting a revision Alembic itself never reaches."""
    newest = _migration_files()[-1]
    bump_match = _MIRROR_BUMP_RE.search(newest.read_text())
    assert bump_match, f"{newest.name} has no 'update public.alembic_version set version_num' bump"

    heads = _alembic_heads()
    assert bump_match.group(1) in heads, (
        f"{newest.name} bumps alembic_version to {bump_match.group(1)!r}, "
        f"but the current Alembic head(s) are {sorted(heads)}"
    )


@pytest.mark.parametrize("table_name", sorted(_tablenames_in_db_models()))
def test_table_is_covered_individually(table_name: str) -> None:
    """Parametrized so a newly added, uncovered table fails by name rather than only appearing
    inside one combined `missing` set -- a clearer signal in CI output."""
    rls_tables, deny_tables = _rls_and_deny_coverage()
    assert table_name in rls_tables, f"{table_name}: no RLS in the Supabase mirror"
    assert table_name in deny_tables, f"{table_name}: no deny_browser_access policy in the mirror"
