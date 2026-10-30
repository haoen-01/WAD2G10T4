-- Mirrors apps/api/alembic/versions/c1e5a8f2d640_group_member_last_opened.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql:
-- safe to run twice, and over a schema the API's `alembic upgrade head` already changed.
--
-- When this member last opened this family group (issue #17). Existing rows stay NULL, meaning
-- never opened. No new table, so no RLS change: the deny posture on group_members from
-- 202610140021 still applies.

alter table public.group_members add column if not exists last_opened_at timestamptz;

update public.alembic_version
set version_num = 'c1e5a8f2d640'
where version_num = 'f3a9c1e7b254';
