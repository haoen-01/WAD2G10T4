-- Care+ RLS posture (apply-only).
--
-- Enables row-level security, drops FORCE if it is somehow set, revokes the `anon` and
-- `authenticated` Data API roles' table privileges, and installs one deny-all
-- `deny_browser_access` policy for every public domain table the SQLAlchemy ORM
-- (`apps/api/src/silverloop/db_models.py`) defines.
--
-- This file contains no `create table`, `alter table ... add column`, `drop`, or any other
-- statement that could fail because a table already does or does not exist, and it never
-- reads or writes a data row. Every statement in it is naturally idempotent (`enable row
-- level security`, `no force row level security` and `revoke` succeed unconditionally; the
-- one statement that is not idempotent by itself, `create policy`, is guarded by a
-- `pg_policies` lookup). It is therefore safe to run any number of times, in any order
-- relative to `alembic upgrade head`, against a database whose tables were created by
-- Alembic, by an `infra/supabase/migrations/*.sql` mirror, or both.
--
-- Why this exists alongside `infra/supabase/migrations/*.sql`: that directory mixes schema
-- DDL with RLS posture, and mirror files written before the idempotency convention
-- introduced at `202609120011_activity_responses.sql` are not safe to replay over a schema
-- Alembic already created (see docs/supabase.md, "Known drift" -- it has happened twice).
-- Concatenating those files into one script to close a gap on the live project inherits
-- that same non-idempotent `create table`, and a partial-failure rollback again leaves the
-- RLS posture at the bottom of the batch unapplied even though the table itself already
-- exists. This script has no such statement, so it cannot fail for that reason. It does not
-- replace the historical mirrors, which remain the record of how the schema and its RLS
-- posture were introduced over time, table by table; it exists only to make "every table
-- has RLS and exactly one deny policy" independently re-establishable in one step,
-- regardless of what has or has not already been applied.
--
-- Companion: `infra/supabase/rls_posture_check.sql` is a read-only report of the posture
-- this file establishes. Run it before and after applying this file.
--
-- Keeping this current: when a new Alembic migration adds a table, add its name to the
-- array below. `apps/api/tests/test_rls_posture_apply.py` fails locally if a table defined
-- in `db_models.py` is missing from this list, and the PostgreSQL integration test in
-- `apps/api/tests/test_postgres_integration.py` fails in CI if applying this file does not
-- leave that table's live posture correct.

do $$
declare
  guarded_table text;
begin
  foreach guarded_table in array array[
    'accounts',
    'activity_candidates',
    'activity_dimension_preferences',
    'activity_goals',
    'activity_offer_responses',
    'appointment_notes',
    'appointments',
    'audit_events',
    'auth_user_person_links',
    'availability_entries',
    'baseline_confirmations',
    'care_groups',
    'candidate_preferences',
    'case_reviews',
    'consent_evidence',
    'context_question_answers',
    'daily_metrics',
    'day_disputes',
    'decision_evidence',
    'family_activity',
    'family_pins',
    'group_members',
    'helper_assignments',
    'intervention_enjoyment',
    'intervention_follow_through',
    'intervention_outcomes',
    'interventions',
    'people',
    'pin_attempts',
    'plan_enjoyment',
    'plan_follow_through',
    'programmes',
    'proposed_memories',
    'replan_offers',
    'review_cases',
    'review_threshold_decisions',
    'review_threshold_proposals',
    'scenario_runs',
    'simulation_events',
    'task_ticks',
    'tasks',
    'week_plan_entries'
  ]
  loop
    -- `enable row level security` and `revoke` are already idempotent (no error if applied
    -- twice). `no force row level security` is the same: it is a no-op when FORCE was never
    -- set. FastAPI connects as the table owner, which must retain its RLS bypass, so FORCE
    -- is actively cleared rather than merely left alone -- see docs/supabase.md's note that
    -- a live FORCE flag was drift, not an intended posture.
    execute format('alter table public.%I enable row level security', guarded_table);
    execute format('alter table public.%I no force row level security', guarded_table);
    execute format('revoke all on public.%I from anon, authenticated', guarded_table);

    if not exists (
      select 1 from pg_policies
      where schemaname = 'public'
        and tablename = guarded_table
        and policyname = 'deny_browser_access'
    ) then
      execute format(
        'create policy deny_browser_access on public.%I '
        'for all to anon, authenticated using (false) with check (false)',
        guarded_table
      );
    end if;
  end loop;
end
$$;
