-- Mirrors apps/api/alembic/versions/c2725d7de5df_add_dimension_preference_run_scope.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (guarded `add column`/`create index`, and constraint creation
-- guarded by a catalogue lookup) for the reason recorded in docs/supabase.md ("Known drift"):
-- the API's lifespan runs `alembic upgrade head` on startup, so by the time this file is applied
-- by hand the column may already exist, and a plain (non-guarded) DDL statement fails the whole
-- (transactional) batch and rolls back before anything later in the file is ever reached.

-- A demo reset no longer deletes this table; it stamps every row that is not a *standing*
-- statement with the run that produced it instead. A *standing* `senior_statement` row (a
-- person's own words, with no `expires_at`) keeps `run_id` null and is never run-scoped -- it is
-- a standing instruction, like a mute. A *time-boxed* `senior_statement` row (`expires_at` set)
-- and every `decline_reason`/`inferred` row are run-scoped -- see
-- db_models.ActivityDimensionPreferenceRow's docstring.
alter table public.activity_dimension_preferences
  add column if not exists run_id varchar(64);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'fk_activity_dimension_preferences_run_id'
  ) then
    execute 'alter table public.activity_dimension_preferences '
      'add constraint fk_activity_dimension_preferences_run_id '
      'foreign key (run_id) references public.scenario_runs(run_id)';
  end if;
end
$$;

create index if not exists ix_activity_dimension_preferences_run_id
on public.activity_dimension_preferences(run_id);

-- Every row this table already held before this revision has `run_id` null, which reads as
-- "standing" only for a `senior_statement` row with no `expires_at` -- for every other row this
-- would make an inferred belief permanent, or let a time-boxed statement keep resurrecting after
-- a reset, exactly the bugs this column exists to close (see sql_repository.py's
-- `_preference_inactive`). Backfill those rows to their person's currently active scenario run.
-- A person with no active run is left null on purpose: the read path already treats a
-- non-standing row with no matching `run_id` as run-scoped-and-inactive, so guessing a run would
-- be no safer and would be a fabricated fact. Idempotent: only ever touches rows still
-- `run_id is null`, which a prior application of this file would already have resolved.
-- `order by ... limit 1`: nothing in the schema enforces one active run per person (only the
-- API's reset does), so a stray second active run must not abort this transactional file.
update public.activity_dimension_preferences
set run_id = (
  select sr.run_id from public.scenario_runs as sr
  where sr.person_id = activity_dimension_preferences.person_id and sr.active = true
  order by sr.started_at desc
  limit 1
)
where run_id is null
  and (source <> 'senior_statement' or expires_at is not null)
  and exists (
    select 1 from public.scenario_runs as sr2
    where sr2.person_id = activity_dimension_preferences.person_id and sr2.active = true
  );

-- RLS and the deny-browser-access posture for `activity_dimension_preferences` already apply to
-- the whole table (infra/supabase/migrations/202609060007_activity_catalogue.sql) and cover this
-- column with no further action; nothing new needed here.

update public.alembic_version
set version_num = 'c2725d7de5df'
where version_num = 'c2f4a8d1e6b7';
