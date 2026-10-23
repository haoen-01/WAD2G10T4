-- Mirrors apps/api/alembic/versions/e3b7d5c18a42_case_clock_and_override_memory.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`add column if not exists`) for the reason recorded in
-- docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on startup, so
-- by the time this file is applied by hand the columns may already exist, and a plain
-- (non-guarded) DDL statement fails the whole (transactional) batch and rolls back before
-- anything later in the file is ever reached.

-- ── The case clock (audit-H finding 4) ──────────────────────────────────────────────────────
-- `opened_at` was the only timestamp a review case had, and it is a wall clock. Nothing in this
-- product advances time except a simulation event, so it cannot answer "how long has this been
-- waiting?" -- a case opened three calendar days ago may have seen no new reading at all.
-- `opened_day` records the simulated day the concern reached a human, in the same clock the
-- response window already counts in. `days_in_review` and `review_by_day` are derived from it by
-- the API rather than stored here: both are functions of this column plus a constant, and a
-- second stored copy could disagree with the first.
--
-- `resolution` records WHY a case closed, as one of `recovered` / `consent_withdrawn` /
-- `coordinator_decision`. That reason previously existed only inside the English prose of a
-- review note written by `reviewer = 'system'`, so anything wanting to act on it had to
-- string-match a sentence.
alter table public.review_cases
  add column if not exists opened_day date;

alter table public.review_cases
  add column if not exists resolution varchar(40);

-- ── Override memory (audit-H finding 3 / WAYFINDER F16) ─────────────────────────────────────
-- Review was built as an audit checkbox: a status and a note, with no record of whether the human
-- agreed with SilverLoop or overruled it, which made "is this system's judgement any good?" an
-- unanswerable question. `agent_recommendation` is a frozen copy of the case's recommendation as
-- it read at the moment of the review, not a reference to it -- a later refresh must not
-- retroactively change what the human was looking at when they decided.
--
-- Audit and evaluation only. Nothing in the learning or ranking path reads this table, and
-- nothing may start to: a coordinator overruling the system is not a training signal about which
-- activity a senior likes.
alter table public.case_reviews
  add column if not exists agent_recommendation text;

alter table public.case_reviews
  add column if not exists human_action varchar(40);

alter table public.case_reviews
  add column if not exists override_reason varchar(40);

-- No data step. Backfilling would mean inventing facts nobody recorded: a refresh overwrites
-- `decision_evidence_id`, so a pre-existing case's surviving evidence points at the latest day
-- rather than the first, and no past reviewer ever chose from an enum that did not exist. A case
-- predating this revision reports "not recorded", which is true.

-- RLS and the deny-browser-access posture for `review_cases` and `case_reviews` are already in
-- the Supabase mirror (infra/supabase/migrations/202608200001_silverloop_core.sql and
-- 202608200002_explicit_browser_denial.sql) and apply to
-- the whole table regardless of its columns; both tables are already listed in
-- infra/supabase/rls_posture_apply.sql. No new table, so nothing new is needed here.

update public.alembic_version
set version_num = 'e3b7d5c18a42'
where version_num = 'b6c1f4d92a37';
