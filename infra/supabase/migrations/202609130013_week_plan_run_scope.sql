-- Mirrors apps/api/alembic/versions/a1d5f3b87c46_run_scope_week_plan_entries.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (constraint drop/create guarded by a catalogue lookup) for the
-- reason recorded in docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade
-- head` on startup, so by the time this file is applied by hand the swap may already have
-- happened, and a plain (non-guarded) DDL statement fails the whole (transactional) batch and
-- rolls back before anything later in the file is ever reached.

-- `week_plan_entries` always carried `run_id`, but its uniqueness key spanned every run and the
-- API's readers never filtered on the column. A demo reset rewinds the simulated calendar to the
-- fixture's anchor day, so a plan an earlier run made landed inside the live week again: a dead
-- run's outings appeared on the senior's week, were reportable, and taught the *new* run's
-- dimension preferences about something it never planned. The API now filters every plan reader
-- and writer on the active run, and the key has to move with them -- person-scoped uniqueness
-- also made a live re-plan of the same choice impossible once a dead run held it.
-- See db_models.WeekPlanEntryRow's docstring and docs/adr/0004.
do $$
begin
  if exists (
    select 1 from pg_constraint where conname = 'uq_week_plan_person_day_activity'
  ) then
    execute 'alter table public.week_plan_entries '
      'drop constraint uq_week_plan_person_day_activity';
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'uq_week_plan_run_person_day_activity'
  ) then
    execute 'alter table public.week_plan_entries '
      'add constraint uq_week_plan_run_person_day_activity '
      'unique (run_id, person_id, day, activity_id)';
  end if;
end
$$;

-- No data step: the new key is strictly weaker than the old one, so every existing row already
-- satisfies it.

-- RLS and the deny-browser-access posture for `week_plan_entries` already apply to the whole
-- table (infra/supabase/migrations/202609060008_enjoyment_memory_goals_week_plan.sql) and are
-- unaffected by a constraint swap; nothing new needed here, and no new table to add to
-- infra/supabase/rls_posture_apply.sql.

update public.alembic_version
set version_num = 'a1d5f3b87c46'
where version_num = 'c2725d7de5df';
