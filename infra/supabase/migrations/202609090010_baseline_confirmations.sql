-- Mirrors apps/api/alembic/versions/b8e4f6c1a205_add_baseline_confirmations.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- and policy creation guarded by a `pg_policies` lookup) for the reason recorded in
-- docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on startup,
-- so by the time this file is applied by hand the table may already exist, and a plain
-- `create table` fails the whole (transactional) batch and rolls back before the RLS posture at
-- the bottom is ever reached. Idempotent statements mean this file is safe to (re)run in either
-- order, any number of times.

-- The senior's own release for the drift clamp: an append-only record of "is this your new
-- normal?" being asked and answered, confirm or decline. The most recent `confirm` row for a run
-- is the reference `calculate_reference` uses going forward; see baseline_confirmation.py.
create table if not exists public.baseline_confirmations (
  confirmation_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  decision varchar(20) not null,
  streak_days integer not null,
  previous_reference_steps double precision not null,
  new_reference_steps double precision,
  decided_on_day date not null,
  decided_at timestamptz not null,
  actor varchar(80) not null
);

create index if not exists ix_baseline_confirmations_run_id
on public.baseline_confirmations(run_id);
create index if not exists ix_baseline_confirmations_person_id
on public.baseline_confirmations(person_id);
create index if not exists ix_baseline_confirmations_run_decided
on public.baseline_confirmations(run_id, decided_on_day);

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write this table.
-- `enable row level security` and `revoke` are themselves idempotent; only `create policy` needs
-- a guard, since Postgres has no `create policy if not exists`.
do $$
begin
  execute 'alter table public.baseline_confirmations enable row level security';
  execute 'revoke all on public.baseline_confirmations from anon, authenticated';
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'baseline_confirmations'
      and policyname = 'deny_browser_access'
  ) then
    execute
      'create policy deny_browser_access on public.baseline_confirmations for all '
      'to anon, authenticated using (false) with check (false)';
  end if;
end
$$;

update public.alembic_version
set version_num = 'b8e4f6c1a205'
where version_num = 'a3f8c72d1e94';
