-- Mirrors apps/api/alembic/versions/c4a7e1b93d58_add_family_activity.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql.

create table if not exists public.family_activity (
  activity_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  kind varchar(32) not null,
  actor_member_id varchar(64) not null references public.group_members(member_id),
  subject_member_id varchar(64) references public.group_members(member_id),
  appointment_id varchar(64),
  appointment_title varchar(120),
  appointment_kind varchar(16),
  on_date date,
  check_in_kind varchar(16),
  note varchar(200),
  origin varchar(16) not null,
  created_at timestamptz not null,
  constraint ck_family_activity_check_in_fields check (
    (kind = 'check_in') = (check_in_kind is not null)
    and (note is null or kind = 'check_in')
  )
);
create index if not exists ix_family_activity_group_created
  on public.family_activity(group_id, created_at, activity_id);
create index if not exists ix_family_activity_actor_member_id
  on public.family_activity(actor_member_id);

-- Same posture as every other table: RLS on, the Data API roles denied outright. Not FORCE.
alter table public.family_activity enable row level security;
revoke all on public.family_activity from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'family_activity' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.family_activity
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'c4a7e1b93d58'
where version_num = 'b9d3e5f71a26';
