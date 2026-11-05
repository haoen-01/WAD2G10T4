# Supabase environment notes

Supabase is used as managed PostgreSQL for shared development and the hosted demo. It is not a
second application backend.

- FastAPI owns all domain writes.
- SQLAlchemy 2 and Alembic own application schema migrations.
- Do not edit the schema through Supabase Studio.
- Do not add Prisma or duplicate application migrations under this directory.
- Keep separate development and demo projects when account limits allow.
- Never run a destructive remote reset during a presentation.

The zero-setup local path uses SQLite and does not require Docker or the Supabase CLI.

## Files in this directory

- `migrations/*.sql` — the historical, hand-applied record of how the schema and its RLS posture
  were introduced over time, mirroring `server/alembic/versions`. Do not rewrite an entry that
  has already been applied to a live project.
- `rls_posture_apply.sql` — a single idempotent script that enables row-level security, clears
  `FORCE`, revokes `anon`/`authenticated` and installs `deny_browser_access` for every table the
  ORM defines, regardless of migration history. Safe to run any number of times. This is the file
  to run to close an RLS gap, not a hand-built concatenation of the migrations above, which are
  not safe to replay over a schema Alembic already created.
- `rls_posture_check.sql` — a read-only report of the posture the file above establishes. Run
  before and after applying it.

There is no `supabase_apply_all.sql` in this repository, committed or otherwise. If you find a
reference to one elsewhere, it means either an out-of-date note (point it at `rls_posture_apply.sql`
instead) or an uncommitted local file that was never a reviewable fix — do not run it.

See `docs/supabase.md`, "Row-level security", for the procedure.
