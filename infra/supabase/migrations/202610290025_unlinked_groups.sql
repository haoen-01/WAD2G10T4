-- Mirrors apps/api/alembic/versions/f3a9c1e7b254_unlinked_family_groups.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql:
-- safe to run twice, and over a schema the API's `alembic upgrade head` already changed.
--
-- A family group can exist before its senior is linked (ADR 0010): `person_id` becomes nullable
-- and stays unique (Postgres allows many NULLs under UNIQUE). No new table, so no RLS change: the
-- deny posture on care_groups from 202610140021 still applies.

alter table public.care_groups add column if not exists senior_name varchar(80);
alter table public.care_groups add column if not exists linked_at timestamptz;
alter table public.care_groups add column if not exists linked_by varchar(128);

-- Every group that exists before this migration has a senior.
update public.care_groups
set senior_name = coalesce(
      (select substr(people.display_name, 1, 80) from public.people
       where people.person_id = care_groups.person_id),
      ''),
    linked_at = created_at,
    linked_by = created_by
where senior_name is null;

alter table public.care_groups alter column senior_name set not null;
alter table public.care_groups alter column person_id drop not null;
alter table public.care_groups alter column linked_via drop not null;

update public.alembic_version
set version_num = 'f3a9c1e7b254'
where version_num = 'd8e2b6a4c917';
