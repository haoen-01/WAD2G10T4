-- Mirrors apps/api/alembic/versions/c2f4a8d1e6b7_add_activity_responses_and_preference_expiry.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- `add column if not exists`, and policy/trigger/constraint creation guarded by catalogue
-- lookups) for the reason recorded in docs/supabase.md ("Known drift"): the API's lifespan runs
-- `alembic upgrade head` on startup, so by the time this file is applied by hand the tables may
-- already exist, and a plain `create table` fails the whole (transactional) batch and rolls back
-- before the RLS posture at the bottom is ever reached.

-- `source` joins the unique key: the decline and enjoyment learners keep their evidence on
-- separate tiers, and the old key let a decline overwrite what an enjoyed activity taught.
alter table public.activity_dimension_preferences
  drop constraint if exists uq_activity_dimension_person_value;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'uq_activity_dimension_person_value_source'
  ) then
    execute 'alter table public.activity_dimension_preferences '
      'add constraint uq_activity_dimension_person_value_source '
      'unique (person_id, dimension, value, source)';
  end if;
end
$$;
alter table public.activity_dimension_preferences
  add column if not exists expires_at timestamptz,
  add column if not exists stated_text varchar(280),
  add column if not exists first_observed_at timestamptz;

-- One tap on a search result: "I'm interested" or "Not for me". Append-only, many per person
-- and listing. `query_id` is an opaque correlation label, never a foreign key.
create table if not exists public.activity_offer_responses (
  response_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  activity_id varchar(80) not null references public.activity_candidates(activity_id),
  query_id varchar(64),
  response varchar(20) not null,
  reason varchar(40),
  rank_shown integer,
  plan_id varchar(64),
  recorded_on_day date not null,
  actor varchar(80) not null,
  recorded_at timestamptz not null
);
create index if not exists ix_activity_offer_responses_run_id
on public.activity_offer_responses(run_id);
create index if not exists ix_activity_offer_responses_person_id
on public.activity_offer_responses(person_id);
create index if not exists ix_activity_offer_responses_person_activity
on public.activity_offer_responses(person_id, activity_id);
create index if not exists ix_activity_offer_responses_run_recorded
on public.activity_offer_responses(run_id, recorded_at);

-- What happened to a planned activity, once the person has said. One row per plan entry.
create table if not exists public.plan_follow_through (
  follow_through_id varchar(64) primary key,
  plan_id varchar(64) not null references public.week_plan_entries(plan_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  follow_through varchar(40) not null,
  note varchar(280),
  actor varchar(80) not null,
  recorded_at timestamptz not null,
  constraint uq_plan_follow_through_plan unique (plan_id)
);
create index if not exists ix_plan_follow_through_plan_id
on public.plan_follow_through(plan_id);
create index if not exists ix_plan_follow_through_run_id
on public.plan_follow_through(run_id);
create index if not exists ix_plan_follow_through_person_id
on public.plan_follow_through(person_id);
create index if not exists ix_plan_follow_through_run_recorded
on public.plan_follow_through(run_id, recorded_at);

-- Whether a planned activity was any good, once the person went and has said. One per plan.
create table if not exists public.plan_enjoyment (
  enjoyment_id varchar(64) primary key,
  plan_id varchar(64) not null references public.week_plan_entries(plan_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  enjoyment varchar(40) not null,
  liked_json json not null,
  actor varchar(80) not null,
  recorded_at timestamptz not null,
  constraint uq_plan_enjoyment_plan unique (plan_id)
);
create index if not exists ix_plan_enjoyment_plan_id
on public.plan_enjoyment(plan_id);
create index if not exists ix_plan_enjoyment_run_id
on public.plan_enjoyment(run_id);
create index if not exists ix_plan_enjoyment_person_id
on public.plan_enjoyment(person_id);
create index if not exists ix_plan_enjoyment_run_recorded
on public.plan_enjoyment(run_id, recorded_at);

-- Append-only, the same trigger the other evidence tables carry. Guarded because the Alembic
-- migration installs the same triggers when it runs first on this database.
do $$
declare
  t text;
begin
  foreach t in array array['activity_offer_responses', 'plan_follow_through', 'plan_enjoyment']
  loop
    if not exists (
      select 1 from pg_trigger where tgname = t || '_append_only'
    ) then
      execute format(
        'create trigger %I before update or delete on public.%I for each row '
        'execute function reject_silverloop_evidence_mutation()',
        t || '_append_only', t
      );
    end if;
  end loop;
end
$$;

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write these tables.
do $$
declare
  t text;
begin
  foreach t in array array['activity_offer_responses', 'plan_follow_through', 'plan_enjoyment']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public' and tablename = t and policyname = 'deny_browser_access'
    ) then
      execute format(
        'create policy deny_browser_access on public.%I for all to anon, authenticated '
        'using (false) with check (false)',
        t
      );
    end if;
  end loop;
end
$$;

update public.alembic_version
set version_num = 'c2f4a8d1e6b7'
where version_num = 'b8e4f6c1a205';
