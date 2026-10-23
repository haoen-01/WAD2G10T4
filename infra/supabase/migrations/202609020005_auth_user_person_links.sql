create table public.auth_user_person_links (
  id bigint generated always as identity primary key,
  sub varchar(128) not null unique,
  person_id varchar(64) not null references public.people(person_id),
  created_at timestamptz not null,
  created_by varchar(128) not null
);

create index ix_auth_user_person_links_person_id on public.auth_user_person_links(person_id);
create index ix_auth_user_person_links_sub on public.auth_user_person_links(sub);

-- Match the RLS posture of every other table in this directory: enable RLS and deny the
-- Data API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects
-- as the table owner, which must retain its RLS bypass in order to read and write this table.
alter table public.auth_user_person_links enable row level security;
revoke all on public.auth_user_person_links from anon, authenticated;
create policy deny_browser_access on public.auth_user_person_links
for all to anon, authenticated using (false) with check (false);

update public.alembic_version
set version_num = 'c9d3e8f2a1b5'
where version_num = 'b6f42a71e903';
