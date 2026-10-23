-- Mirrors apps/api/alembic/versions/b6c1f4d92a37_add_replan_offers.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- `add column if not exists`, and policy creation guarded by a catalogue lookup) for the reason
-- recorded in docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade head` on
-- startup, so by the time this file is applied by hand the table may already exist, and a plain
-- `create table` fails the whole (transactional) batch and rolls back before the RLS posture at
-- the bottom is ever reached.

-- One offer to replace a planned activity the world changed under, and what the person said.
-- Written by `advance()` in the same transaction as the change that invalidated the plan;
-- resolved in place by the person's own `replace` or `decline`. `reason` is a closed vocabulary
-- (`full`, `cancelled`, `weather`) and is the reason *code*, never the sentence shown to anyone.
create table if not exists public.replan_offers (
  offer_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  plan_id varchar(64) not null references public.week_plan_entries(plan_id),
  reason varchar(20) not null,
  alternative_activity_id varchar(80) references public.activity_candidates(activity_id),
  offered_at timestamptz not null,
  resolved_at timestamptz,
  resolution varchar(20)
);
create index if not exists ix_replan_offers_run_id on public.replan_offers(run_id);
create index if not exists ix_replan_offers_person_id on public.replan_offers(person_id);
create index if not exists ix_replan_offers_run_person on public.replan_offers(run_id, person_id);
create index if not exists ix_replan_offers_plan on public.replan_offers(plan_id);

-- Why this plan could no longer happen, and which plan took its place. `replaced_reason` has been
-- on the table since 202609060008 and until now was only ever written as NULL; the link completes
-- the pair. Every pre-existing row keeps NULL, which is exactly what "never replaced" means.
alter table public.week_plan_entries
  add column if not exists replaced_by_plan_id varchar(64);

-- NO append-only trigger here, deliberately, unlike activity_offer_responses / plan_follow_through
-- / plan_enjoyment: an offer is resolved in place (accepted, declined, expired), so
-- `reject_silverloop_evidence_mutation` would block the very update this table exists for. The
-- audit trail (`replan_offered`, `replanned`, `replan_declined` in public.audit_events) is the
-- append-only record of the same events.

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write this table.
do $$
declare
  t text;
begin
  foreach t in array array['replan_offers']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public' and tablename = t and policyname = 'deny_browser_access'
    ) then
      execute format(
        'create policy deny_browser_access on public.%I for all to anon, authenticated '
        'using (false) with check (false)',
        t
      );
    end if;
  end loop;
end
$$;

update public.alembic_version
set version_num = 'b6c1f4d92a37'
where version_num = 'd81c4b0f6a27';
