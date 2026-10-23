-- Mirrors apps/api/alembic/versions/d8b1e4f70c2a_add_context_answer_scenario_day.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (guarded `add column`) for the reason recorded in
-- docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on startup, so
-- by the time this file is applied by hand the column may already exist, and a plain (non-guarded)
-- DDL statement fails the whole (transactional) batch and rolls back before anything later in the
-- file is ever reached.

-- A recorded answer to the quiet-day question now explains a quieter reading for a bounded number
-- of days (see apps/api/src/silverloop/context_explanation.py), and that window has to be counted
-- in the person's *simulated* calendar. `answered_at` is wall-clock and cannot carry it: a demo
-- advancing ten simulated days in one wall-clock minute would see every answer as given "today",
-- so no explanation would ever expire -- the same failure `_weekly_contact_count` already had.
-- `answered_on_day` is the scenario day, exactly as `baseline_confirmations.decided_on_day` is.
alter table public.context_question_answers
  add column if not exists answered_on_day date;

-- Deliberately not backfilled. An existing row's scenario day cannot be recovered from its
-- wall-clock timestamp -- the simulated calendar does not advance in step with real time, which is
-- the whole reason this column exists -- so any value written here would be a fabricated fact in an
-- evidence table. `context_explanation.active_explanation` skips a row whose `answered_on_day` is
-- null, so a pre-existing answer behaves exactly as it did before this revision: recorded,
-- displayed, counted for `asked_recently`, and explaining nothing.

-- RLS and the deny-browser-access posture for `context_question_answers` already apply to the
-- whole table (infra/supabase/migrations/202609060008_enjoyment_memory_goals_week_plan.sql) and
-- cover this column with no further action; nothing new needed here.

update public.alembic_version
set version_num = 'd8b1e4f70c2a'
where version_num = 'e1c9a5d70b42';
