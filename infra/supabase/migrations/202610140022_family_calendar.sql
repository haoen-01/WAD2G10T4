-- Mirrors apps/api/alembic/versions/b9d3e5f71a26_add_family_calendar.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql.

create table if not exists public.appointments (
  appointment_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  title varchar(120) not null,
  kind varchar(16) not null,
  start_date date not null,
  start_time varchar(5) not null,
  end_time varchar(5) not null,
  location varchar(160),
  notes text,
  repeat varchar(8) not null,
  repeat_until date,
  created_by varchar(128) not null,
  created_at timestamptz not null
);
create index if not exists ix_appointments_group_id on public.appointments(group_id);

create table if not exists public.availability_entries (
  entry_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  member_id varchar(64) not null references public.group_members(member_id),
  on_date date not null,
  start_time varchar(5) not null,
  end_time varchar(5) not null,
  status varchar(16) not null,
  appointment_id varchar(64) references public.appointments(appointment_id),
  created_at timestamptz not null
);
create index if not exists ix_availability_entries_group_id
  on public.availability_entries(group_id);
create index if not exists ix_availability_entries_member_id
  on public.availability_entries(member_id);
create index if not exists ix_availability_entries_appointment_id
  on public.availability_entries(appointment_id);

create table if not exists public.helper_assignments (
  assignment_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  appointment_id varchar(64) not null references public.appointments(appointment_id),
  on_date date not null,
  member_id varchar(64) not null references public.group_members(member_id),
  created_at timestamptz not null,
  constraint uq_helper_assignments_day_member unique (appointment_id, on_date, member_id)
);
create index if not exists ix_helper_assignments_group_id on public.helper_assignments(group_id);
create index if not exists ix_helper_assignments_appointment_id
  on public.helper_assignments(appointment_id);
create index if not exists ix_helper_assignments_member_id
  on public.helper_assignments(member_id);

-- Same posture as every other table: RLS on, the Data API roles denied outright. Not FORCE.
alter table public.appointments enable row level security;
alter table public.availability_entries enable row level security;
alter table public.helper_assignments enable row level security;
revoke all on public.appointments, public.availability_entries, public.helper_assignments
  from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'appointments' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.appointments
    for all to anon, authenticated using (false) with check (false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'availability_entries' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.availability_entries
    for all to anon, authenticated using (false) with check (false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'helper_assignments' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.helper_assignments
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'b9d3e5f71a26'
where version_num = 'a4f6c2e81d37';
