-- Mirrors apps/api/alembic/versions/e1c9a5d70b42_split_preference_evidence_and_add_scope.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (guarded `add column`, and a backfill that only touches rows
-- where both sides are still null) for the reason recorded in docs/supabase.md ("Known drift"):
-- the API's lifespan runs `alembic upgrade head` on startup, so by the time this file is applied
-- by hand the columns may already exist, and a plain (non-guarded) DDL statement fails the whole
-- (transactional) batch and rolls back before anything later in the file is ever reached.

-- `strength` was one signed scalar carrying which way a belief leans, how much evidence is behind
-- it and how confident that makes it. Splitting the evidence in two makes `strength` and
-- `confidence` separately derivable -- and order-independent, which "it was fine" overwriting
-- "I loved it" was not. See silverloop/preferences.py::resolve.
alter table public.activity_dimension_preferences
  add column if not exists positive_evidence double precision;

alter table public.activity_dimension_preferences
  add column if not exists negative_evidence double precision;

-- The ordinal half. A "too far" at 1.2 km used to be stored as the nominal bucket the listing
-- fell in (`near`), which taught the system to avoid activities near home. `pivot` is the number
-- the answer put a line at and `direction` says which side of it the person wants.
alter table public.activity_dimension_preferences
  add column if not exists pivot double precision;

alter table public.activity_dimension_preferences
  add column if not exists direction varchar(10);

-- One origin, one observation: the most recent thing folded into this belief. On a
-- `senior_statement` row it is the id of the inferred row that statement consumed, which is what
-- makes a ratified belief one row rather than two that contradict each other.
alter table public.activity_dimension_preferences
  add column if not exists origin_id varchar(80);

-- What `forget` stamps instead of deleting the row, and what ratification stamps on the row it
-- consumed. A superseded row is never read, never rendered and never scored; keeping it means the
-- audit trail is not rewritten, and the next observation starts a fresh belief from zero rather
-- than resurrecting a count the person believed they had erased.
alter table public.activity_dimension_preferences
  add column if not exists superseded_by varchar(80);

-- How far a clarification chip said a decline reaches. Null means unclarified, which is
-- item-level only.
alter table public.activity_dimension_preferences
  add column if not exists scope varchar(20);

-- Each pre-existing row's evidence, read back out of its own numbers. Pre-split, `strength` was
-- always `cap * n/(n+2)` for `n = observations`, and the cap depended on what the row recorded:
--
--   * 1.0 for a decline or an enjoyed outing -- `n` on the leaning side reproduces the row's own
--     `strength` exactly through `(pos - neg)/(pos + neg + 2)`;
--   * 0.15 for the two "barely a preference" bands ("it was fine", "I'd prefer something else")
--     -- these must be scaled by that cap, or three "it was fine"s are migrated as three
--     genuinely enjoyed outings (0.090 -> 0.600, a 6.7x amplification). `0.15 * n` resolves to
--     what this code writes from the same history, so a migrated and a fresh database agree;
--   * a statement is one origin however often it was made, and its `strength` is +/-1.0.
--
-- The two learned bands are disjoint (with one observation the uncapped shape is already 1/3 and
-- the capped one never reaches 0.15), so this classifies rather than guesses. Mirrors
-- silverloop/preferences.py::_legacy_evidence. Idempotent: only touches rows where both sides
-- are still null, which a prior application of this file would already have resolved.
update public.activity_dimension_preferences
set positive_evidence = case
      when strength > 0 then case
        when source = 'senior_statement' then 1.0
        when abs(strength) <= 0.15
          then 0.15 * (case when observations > 0 then observations else 1 end)
        else (case when observations > 0 then observations else 1 end)
      end
      else 0
    end,
    negative_evidence = case
      when strength < 0 then case
        when source = 'senior_statement' then 1.0
        when abs(strength) <= 0.15
          then 0.15 * (case when observations > 0 then observations else 1 end)
        else (case when observations > 0 then observations else 1 end)
      end
      else 0
    end
where positive_evidence is null and negative_evidence is null;

-- The write path a clarification chip has to reach, on both decline surfaces. Both tables are
-- append-only, so an added nullable column is compatible with every row already in them.
alter table public.activity_offer_responses
  add column if not exists clarification varchar(20);

alter table public.intervention_outcomes
  add column if not exists clarification varchar(20);

-- RLS and the deny-browser-access posture for all three tables already apply to the whole table
-- (infra/supabase/migrations/202608200001_silverloop_core.sql,
-- 202609060007_activity_catalogue.sql, 202609120011_activity_responses.sql) and cover these
-- columns with no further action; no new table is created here, so nothing new is needed.

update public.alembic_version
set version_num = 'e1c9a5d70b42'
where version_num = 'e3b7d5c18a42';
