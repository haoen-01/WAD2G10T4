-- Mirrors apps/api/alembic/versions/e6b2d9a4c718_add_helper_asks.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand. Idempotent for the same reason as 202610140021_family_groups.sql.

create table if not exists public.helper_asks (
  ask_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  appointment_id varchar(64) not null,
  appointment_title varchar(120) not null,
  on_date date not null,
  asker_member_id varchar(64) not null references public.group_members(member_id),
  asked_member_id varchar(64) not null references public.group_members(member_id),
  state varchar(16) not null,
  created_at timestamptz not null,
  ended_at timestamptz,
  ended_by_member_id varchar(64) references public.group_members(member_id),
  constraint ck_helper_asks_not_self check (asker_member_id <> asked_member_id)
);
-- At most one open ask per appointment day.
create unique index if not exists uq_helper_asks_open_day
  on public.helper_asks(appointment_id, on_date) where state = 'open';
create index if not exists ix_helper_asks_group_state on public.helper_asks(group_id, state);

create table if not exists public.notifications (
  notification_id varchar(64) primary key,
  group_id varchar(64) not null references public.care_groups(group_id),
  recipient_member_id varchar(64) not null references public.group_members(member_id),
  kind varchar(24) not null,
  ask_id varchar(64) not null references public.helper_asks(ask_id),
  created_at timestamptz not null,
  read_at timestamptz
);
create index if not exists ix_notifications_recipient_created
  on public.notifications(recipient_member_id, created_at, notification_id);
create index if not exists ix_notifications_ask_id on public.notifications(ask_id);

-- Same posture as every other table: RLS on, the Data API roles denied outright. Not FORCE.
alter table public.helper_asks enable row level security;
alter table public.notifications enable row level security;
revoke all on public.helper_asks from anon, authenticated;
revoke all on public.notifications from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'helper_asks' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.helper_asks
    for all to anon, authenticated using (false) with check (false);
  end if;
  if not exists (select 1 from pg_policies where schemaname = 'public'
                 and tablename = 'notifications' and policyname = 'deny_browser_access') then
    create policy deny_browser_access on public.notifications
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'e6b2d9a4c718'
where version_num = 'a7d4c2e9f1b3';
