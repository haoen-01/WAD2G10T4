-- Care+ RLS posture check (read-only).
--
-- Reports, for every ordinary table in the `public` schema: whether row-level security is
-- enabled, whether FORCE ROW LEVEL SECURITY is set, the names of every policy defined on
-- it, and every table-level privilege grant currently held by the `anon` or `authenticated`
-- Data API roles.
--
-- This file contains no DDL, no DML and no PL/pgSQL -- a single `select` -- so it changes
-- nothing and is safe for anyone with read access to run at any time. Run it before and
-- after applying `infra/supabase/rls_posture_apply.sql` and keep both outputs: the "before"
-- run shows the gap, the "after" run is the evidence it closed.
--
-- A table is in the closed, correct posture this project wants when, in one row:
--   rls_enabled            = true
--   rls_forced             = false   (FastAPI connects as the table owner and must keep its
--                                     RLS bypass; forcing RLS would lock it out too)
--   policies                = {deny_browser_access}   (exactly this one policy, nothing else)
--   anon_or_auth_grants     = {}     (empty array: neither Data API role holds any privilege)
--
-- `public.alembic_version` is Alembic's own bookkeeping table, not part of the domain
-- schema in `server/src/silverloop/db_models.py`; it is included here because it is a
-- real table in the same schema and the original mirror
-- (`infra/supabase/migrations/202608200001_silverloop_core.sql`) already covers it, but it
-- is not one of the tables `rls_posture_apply.sql` or the CI test enumerate.

select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  c.relforcerowsecurity as rls_forced,
  coalesce(
    (
      select array_agg(p.policyname order by p.policyname)
      from pg_policies p
      where p.schemaname = 'public'
        and p.tablename = c.relname
    ),
    array[]::text[]
  ) as policies,
  coalesce(
    (
      select array_agg(distinct g.grantee || ':' || g.privilege_type order by g.grantee || ':' || g.privilege_type)
      from information_schema.role_table_grants g
      where g.table_schema = 'public'
        and g.table_name = c.relname
        and g.grantee in ('anon', 'authenticated')
    ),
    array[]::text[]
  ) as anon_or_auth_grants
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
order by c.relname;
