-- Mirrors apps/api/alembic/versions/f7c2a9d4e6b3_add_enjoyment_memory_goals_and_week_plan.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- and policy creation guarded by a `pg_policies` lookup) for the reason recorded in
-- docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on startup,
-- so by the time this file is applied by hand the tables may already exist, and a plain
-- `create table` fails the whole (transactional) batch and rolls back before the RLS posture at
-- the bottom is ever reached. Idempotent statements mean this file is safe to (re)run in either
-- order, any number of times.

-- Whether one piece of outreach was any good, once the person has said. One row per
-- intervention, matching intervention_follow_through's own uniqueness rule.
create table if not exists public.intervention_enjoyment (
  enjoyment_id varchar(64) primary key,
  intervention_id varchar(64) not null references public.interventions(intervention_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  enjoyment varchar(40) not null,
  liked_json json not null,
  actor varchar(80) not null,
  recorded_at timestamptz not null,
  constraint uq_enjoyment_intervention unique (intervention_id)
);

create index if not exists ix_intervention_enjoyment_run_id
on public.intervention_enjoyment(run_id);
create index if not exists ix_intervention_enjoyment_person_id
on public.intervention_enjoyment(person_id);
create index if not exists ix_enjoyment_run_recorded
on public.intervention_enjoyment(run_id, recorded_at);

-- Something SilverLoop believes it has learned, held back until the person agrees to it.
-- `status` starts `pending` and becomes `remember` / `just_today` / `no` once decided -- terminal,
-- not append-only.
create table if not exists public.proposed_memories (
  proposal_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  dimension varchar(40) not null,
  value varchar(160) not null,
  statement text not null,
  question text not null,
  source_text text,
  status varchar(20) not null,
  created_at timestamptz not null,
  decided_at timestamptz,
  decided_by varchar(80)
);

create index if not exists ix_proposed_memories_run_id
on public.proposed_memories(run_id);
create index if not exists ix_proposed_memories_person_id
on public.proposed_memories(person_id);
create index if not exists ix_proposed_memories_person_status
on public.proposed_memories(person_id, status);
create index if not exists ix_proposed_memories_person_dimension_value
on public.proposed_memories(person_id, dimension, value);

-- A record that one context question was asked and answered, so `question_for` knows which
-- questions have already been put to this person this run. The question itself is never stored
-- ahead of time -- it is computed fresh from PersonState every time.
create table if not exists public.context_question_answers (
  answer_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  question_id varchar(80) not null,
  value varchar(160) not null,
  note text,
  actor varchar(80) not null,
  answered_at timestamptz not null
);

create index if not exists ix_context_question_answers_run_id
on public.context_question_answers(run_id);
create index if not exists ix_context_question_answers_person_id
on public.context_question_answers(person_id);
create index if not exists ix_context_question_answers_run
on public.context_question_answers(run_id, question_id);

-- A lifestyle goal the person has chosen -- never a health target, never scored.
-- (person_id, kind) is unique: the current goal of a given kind is one row, replaced in place.
create table if not exists public.activity_goals (
  goal_id varchar(64) primary key,
  person_id varchar(64) not null references public.people(person_id),
  kind varchar(40) not null,
  target_per_week integer,
  active boolean not null,
  created_at timestamptz not null,
  constraint uq_activity_goal_person_kind unique (person_id, kind)
);

create index if not exists ix_activity_goals_person_id
on public.activity_goals(person_id);

-- One activity a person has put on their own week -- chosen, not suggested.
-- (person_id, day, activity_id) is unique so re-submitting the same choice is a no-op.
create table if not exists public.week_plan_entries (
  plan_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  day date not null,
  activity_id varchar(80) not null references public.activity_candidates(activity_id),
  origin varchar(20) not null,
  replaced_reason text,
  created_at timestamptz not null,
  constraint uq_week_plan_person_day_activity unique (person_id, day, activity_id)
);

create index if not exists ix_week_plan_entries_run_id
on public.week_plan_entries(run_id);
create index if not exists ix_week_plan_entries_person_id
on public.week_plan_entries(person_id);
create index if not exists ix_week_plan_entries_person_day
on public.week_plan_entries(person_id, day);

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write these tables.
-- `enable row level security` and `revoke` are themselves idempotent; only `create policy` needs
-- a guard, since Postgres has no `create policy if not exists`.
do $$
declare
  guarded_table text;
begin
  foreach guarded_table in array array[
    'intervention_enjoyment',
    'proposed_memories',
    'context_question_answers',
    'activity_goals',
    'week_plan_entries'
  ]
  loop
    execute format('alter table public.%I enable row level security', guarded_table);
    execute format('revoke all on public.%I from anon, authenticated', guarded_table);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public'
        and tablename = guarded_table
        and policyname = 'deny_browser_access'
    ) then
      execute format(
        'create policy deny_browser_access on public.%I for all to anon, authenticated using (false) with check (false)',
        guarded_table
      );
    end if;
  end loop;
end
$$;

update public.alembic_version
set version_num = 'f7c2a9d4e6b3'
where version_num = 'e5b8d2a4f7c1';
