-- Mirrors apps/api/alembic/versions/e5b8d2a4f7c1_add_activity_catalogue.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- and policy creation guarded by a `pg_policies` lookup) for the reason recorded twice now in
-- docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on startup,
-- so by the time this file is applied by hand the tables may already exist, and a plain
-- `create table` fails the whole (transactional) batch and rolls back before the RLS posture at
-- the bottom is ever reached. Idempotent statements mean this file is safe to (re)run in either
-- order, any number of times.

-- A catalogue, not evidence: no append-only trigger, matching activity_candidates' equivalent
-- in Alembic (db_models.ActivityCandidateRow has none either).
create table if not exists public.activity_candidates (
  activity_id varchar(80) primary key,
  source varchar(40) not null,
  integration_status varchar(40) not null,
  title varchar(240) not null,
  provider varchar(160) not null,
  start_at timestamptz,
  location_name varchar(200) not null,
  location_address varchar(300),
  location_latitude double precision,
  location_longitude double precision,
  category varchar(120),
  indoor_outdoor varchar(20) not null,
  -- Nullable: "the listing does not say" and "solo" are different facts.
  social_shape varchar(20),
  intensity varchar(20),
  accessibility_tags_json json not null,
  language_tags_json json not null,
  capacity integer,
  availability varchar(20) not null,
  price varchar(80),
  source_url varchar(300),
  retrieved_at timestamptz not null,
  distance_m integer
);

-- Deliberately NOT append-only, like candidate_preferences: a live belief about a *kind* of
-- activity, replaced in place as more declines arrive, not a record of something that happened.
create table if not exists public.activity_dimension_preferences (
  preference_id varchar(64) primary key,
  person_id varchar(64) not null references public.people(person_id),
  dimension varchar(40) not null,
  value varchar(160) not null,
  strength double precision not null,
  source varchar(40) not null,
  confirmed boolean not null,
  observations integer not null,
  updated_at timestamptz not null,
  constraint uq_activity_dimension_person_value unique (person_id, dimension, value)
);

create index if not exists ix_activity_dimension_preferences_person_id
on public.activity_dimension_preferences(person_id);

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write these tables.
-- `enable row level security` and `revoke` are themselves idempotent (no error if already
-- applied); only `create policy` needs a guard, since Postgres has no
-- `create policy if not exists`.
alter table public.activity_candidates enable row level security;
revoke all on public.activity_candidates from anon, authenticated;
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'activity_candidates'
      and policyname = 'deny_browser_access'
  ) then
    create policy deny_browser_access on public.activity_candidates
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

alter table public.activity_dimension_preferences enable row level security;
revoke all on public.activity_dimension_preferences from anon, authenticated;
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'activity_dimension_preferences'
      and policyname = 'deny_browser_access'
  ) then
    create policy deny_browser_access on public.activity_dimension_preferences
    for all to anon, authenticated using (false) with check (false);
  end if;
end
$$;

update public.alembic_version
set version_num = 'e5b8d2a4f7c1'
where version_num = 'd4a7c1f9e2b3';
