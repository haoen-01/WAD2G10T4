-- Mirrors apps/api/alembic/versions/7c3e9a1f4b28_add_review_context_gap_category.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics, applied by hand.
--
-- Written idempotent (`add column if not exists`, and the Alembic marker advanced only from its
-- exact predecessor) for the reason recorded in docs/supabase.md ("Known drift"): the API's
-- lifespan runs `alembic upgrade head` on startup, so by the time this file is applied by hand the
-- column may already exist.

-- ── Calibration trust (docs/calibration-trust-spec.md) ──────────────────────────────────────
-- What kind of known context explained a review, when a coordinator chose to say. Nullable and
-- not backfilled: no past reviewer was asked. Set only beside an override for `known_context`,
-- tallied for the care team, and read by no decision, proposal or review setting.
-- RLS and the deny posture for `case_reviews` already apply to the whole table
-- (202608200001_silverloop_core.sql, 202608200002_explicit_browser_denial.sql), and its
-- append-only trigger is row-level, so a new column needs nothing further.
alter table public.case_reviews
  add column if not exists context_gap_category varchar(40);

update public.alembic_version
set version_num = '7c3e9a1f4b28'
where version_num = '485506d5a415';
