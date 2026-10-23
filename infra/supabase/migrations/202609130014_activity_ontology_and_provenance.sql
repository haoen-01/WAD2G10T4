-- Mirrors apps/api/alembic/versions/d81c4b0f6a27_add_activity_ontology_and_provenance.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (guarded `add column`, and a backfill that only touches rows
-- still null) for the reason recorded in docs/supabase.md ("Known drift"): the API's lifespan
-- runs `alembic upgrade head` on startup, so by the time this file is applied by hand the
-- columns may already exist, and a plain (non-guarded) DDL statement fails the whole
-- (transactional) batch and rolls back before anything later in the file is ever reached.

-- `category` was one free-text column serving three masters at once -- the card badge, the
-- learner's content axis and the diversity key -- and its values ("Group class", "Social group")
-- describe *format*, not content, so one "not for me" on a walk taught a dislike of tai chi.
-- `activity_type` (what the thing is), `activity_families_json` (the broad kinds, multi-label)
-- and `format` (how it is run) separate the facts it conflated. `category` stays as the badge,
-- written from `ontology.FORMAT_LABEL`. See silverloop/ontology.py.
alter table public.activity_candidates
  add column if not exists activity_type varchar(40);

alter table public.activity_candidates
  add column if not exists activity_families_json json;

alter table public.activity_candidates
  add column if not exists format varchar(40);

-- Provenance. Nullable, and a fixture listing leaves `last_verified_at` null on purpose: nobody
-- has checked these against a real centre, and a date here would claim they had.
alter table public.activity_candidates
  add column if not exists metadata_source varchar(120);

alter table public.activity_candidates
  add column if not exists last_verified_at timestamptz;

-- Stored rather than inferred from `distance_m is null`. That inference is only correct while
-- exactly one basis exists; the moment a routing adapter measures a real walk, every row it
-- wrote would still read "a fixed figure typed into the listing".
alter table public.activity_candidates
  add column if not exists distance_basis varchar(40);

-- Exactly the rule the reader applied before the column existed, so no row's meaning changes as
-- this runs. Idempotent: only touches rows still null, which a prior application of this file
-- would already have resolved.
update public.activity_candidates
set distance_basis = case when distance_m is null then 'unknown' else 'listing_static' end
where distance_basis is null;

-- RLS and the deny-browser-access posture for `activity_candidates` already apply to the whole
-- table (infra/supabase/migrations/202609060007_activity_catalogue.sql) and cover these columns
-- with no further action; nothing new needed here.

update public.alembic_version
set version_num = 'd81c4b0f6a27'
where version_num = 'a1d5f3b87c46';
