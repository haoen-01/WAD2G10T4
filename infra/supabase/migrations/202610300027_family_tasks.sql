-- Mirrors apps/api/alembic/versions/a7d4c2e9f1b3_add_family_tasks.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql.

create table if not exists public.tasks (
  task_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  title varchar(120) not null,
  kind varchar(16) not null,
  start_date date not null,
  time varchar(5) not null,
  repeat varchar(8) not null,
  repeat_until date,
  notes text not null,
  created_by varchar(128) not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
create index if not exists ix_tasks_group_id on public.tasks(group_id);

create table if not exists public.task_ticks (
  tick_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  task_id varchar(64) not null references public.tasks(task_id),
  day date not null,
  done_by varchar(128) not null,
  done_at timestamptz not null,
  constraint uq_task_ticks_task_day unique (task_id, day)
);
create index if not exists ix_task_ticks_group_id on public.task_ticks(group_id);
create index if not exists ix_task_ticks_task_id on public.task_ticks(task_id);

-- Same posture as every other table: RLS on, the Data API roles denied outright. Not FORCE.
alter table public.tasks enable row level security;
alter table public.task_ticks enable row level security;
revoke all on public.tasks from anon, authenticated;
revoke all on public.task_ticks from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'tasks' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.tasks
    for all to anon, authenticated using (false) with check (false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'task_ticks' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.task_ticks
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'a7d4c2e9f1b3'
where version_num = 'c1e5a8f2d640';
