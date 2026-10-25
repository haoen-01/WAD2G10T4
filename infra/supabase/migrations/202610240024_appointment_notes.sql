-- Mirrors apps/api/alembic/versions/d8e2b6a4c917_add_appointment_notes.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql.

create table if not exists public.appointment_notes (
  note_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  appointment_id varchar(64) not null references public.appointments(appointment_id),
  on_date date not null,
  member_id varchar(64) not null references public.group_members(member_id),
  text varchar(500) not null,
  created_at timestamptz not null
);
create index if not exists ix_appointment_notes_group_id
  on public.appointment_notes(group_id);
create index if not exists ix_appointment_notes_appointment_id
  on public.appointment_notes(appointment_id);
create index if not exists ix_appointment_notes_member_id
  on public.appointment_notes(member_id);
create index if not exists ix_appointment_notes_day_created
  on public.appointment_notes(appointment_id, on_date, created_at);

-- Same posture as every other table: RLS on, the Data API roles denied outright. Not FORCE.
alter table public.appointment_notes enable row level security;
revoke all on public.appointment_notes from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'appointment_notes' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.appointment_notes
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'd8e2b6a4c917'
where version_num = 'c4a7e1b93d58';
