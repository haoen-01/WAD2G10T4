-- Mirrors apps/api/alembic/versions/d4a7c1f9e2b3_add_follow_through_loop.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture and the append-only evidence triggers), applied by hand.

-- Nullable and never backfilled: an outcome recorded before this column existed genuinely
-- carries no reason. `alter table ... add column` is DDL and is not blocked by the
-- intervention_outcomes append-only trigger, which rejects row updates and deletes.
alter table public.intervention_outcomes add column reason varchar(40);

create table public.intervention_follow_through (
  follow_through_id varchar(64) primary key,
  intervention_id varchar(64) not null references public.interventions(intervention_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  follow_through varchar(40) not null,
  note text,
  actor varchar(80) not null,
  recorded_at timestamptz not null,
  constraint uq_follow_through_intervention unique (intervention_id)
);

create index ix_intervention_follow_through_intervention_id
on public.intervention_follow_through(intervention_id);
create index ix_intervention_follow_through_run_id
on public.intervention_follow_through(run_id);
create index ix_intervention_follow_through_person_id
on public.intervention_follow_through(person_id);
create index ix_follow_through_run_recorded
on public.intervention_follow_through(run_id, recorded_at);

-- What a person said happened is evidence, and evidence is append-only here for the same
-- reason every other evidence table is.
create trigger intervention_follow_through_append_only
before update or delete on public.intervention_follow_through
for each row execute function public.reject_silverloop_evidence_mutation();

-- Deliberately NOT append-only: a preference is a live setting the person toggles, not a
-- record of something that happened. Muting a suggestion has to be reversible.
create table public.candidate_preferences (
  preference_id varchar(64) primary key,
  person_id varchar(64) not null references public.people(person_id),
  candidate_key varchar(120) not null,
  suppressed boolean not null,
  reason text,
  actor varchar(80) not null,
  updated_at timestamptz not null,
  constraint uq_candidate_preference_person_key unique (person_id, candidate_key)
);

create index ix_candidate_preferences_person_id
on public.candidate_preferences(person_id);

create table public.day_disputes (
  dispute_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  day date not null,
  accurate boolean not null,
  note text,
  actor varchar(80) not null,
  recorded_at timestamptz not null
);

create index ix_day_disputes_run_id on public.day_disputes(run_id);
create index ix_day_disputes_person_id on public.day_disputes(person_id);
create index ix_day_disputes_person_day on public.day_disputes(person_id, day);

create trigger day_disputes_append_only
before update or delete on public.day_disputes
for each row execute function public.reject_silverloop_evidence_mutation();

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write these tables.
alter table public.intervention_follow_through enable row level security;
revoke all on public.intervention_follow_through from anon, authenticated;
create policy deny_browser_access on public.intervention_follow_through
for all to anon, authenticated using (false) with check (false);

alter table public.candidate_preferences enable row level security;
revoke all on public.candidate_preferences from anon, authenticated;
create policy deny_browser_access on public.candidate_preferences
for all to anon, authenticated using (false) with check (false);

alter table public.day_disputes enable row level security;
revoke all on public.day_disputes from anon, authenticated;
create policy deny_browser_access on public.day_disputes
for all to anon, authenticated using (false) with check (false);

update public.alembic_version
set version_num = 'd4a7c1f9e2b3'
where version_num = 'c9d3e8f2a1b5';
