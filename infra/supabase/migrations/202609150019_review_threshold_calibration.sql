-- Mirrors apps/api/alembic/versions/485506d5a415_add_review_threshold_calibration.py.
-- Alembic owns the application schema; this file exists only for the Supabase-platform
-- specifics (RLS posture), applied by hand.
--
-- Written idempotent throughout (`create table if not exists`, `create index if not exists`,
-- `add column if not exists`, and policy/trigger creation guarded by catalogue lookups) for the
-- reason recorded in docs/supabase.md ("Known drift"): the API's lifespan runs `alembic upgrade
-- head` on startup, so by the time this file is applied by hand the tables may already exist, and
-- a plain `create table` fails the whole (transactional) batch and rolls back before the RLS
-- posture at the bottom is ever reached.

-- ── The review-threshold calibrator (ADR 0008) ──────────────────────────────────────────────
-- A coordinator's structured false-alarm judgement may tune, per person and inside fixed bounds,
-- the point at which SilverLoop asks a human -- never the baseline. No "current threshold" is
-- stored: the live value is a pure fold over `review_threshold_decisions`, so the schema is two
-- append-only evidence tables and one nullable column.

-- "This should have reached me sooner." Nullable and not backfilled: no past reviewer was asked.
-- RLS and the deny posture for `case_reviews` already apply to the whole table
-- (202608200001_silverloop_core.sql, 202608200002_explicit_browser_denial.sql).
alter table public.case_reviews
  add column if not exists reached_too_late boolean;

-- One row per calibrator output: a proposed change, a considered no-change, or a write-up of a
-- revert. `write_up_for_decision_id` is unique (one write-up per revert) and deliberately not a
-- foreign key: `review_threshold_decisions` already references this table.
create table if not exists public.review_threshold_proposals (
  proposal_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  output_kind varchar(20) not null,
  proposer varchar(20) not null,
  round_id varchar(64),
  round_index integer,
  previous_severity_pct integer not null,
  previous_persistence_days integer not null,
  proposed_severity_pct integer,
  proposed_persistence_days integer,
  cause varchar(40),
  reasoning text not null,
  cited_evidence_ids json not null,
  trigger_case_id varchar(64) references public.review_cases(case_id),
  trigger_review_ids json not null,
  reported_by varchar(120),
  coordinator_reason varchar(40),
  write_up_for_decision_id varchar(64),
  agent_run_json json,
  proposed_on_day date not null,
  proposed_at timestamptz not null,
  constraint uq_review_threshold_proposals_write_up_for unique (write_up_for_decision_id)
);
create index if not exists ix_review_threshold_proposals_run_id
on public.review_threshold_proposals(run_id);
create index if not exists ix_review_threshold_proposals_person_id
on public.review_threshold_proposals(person_id);
create index if not exists ix_review_threshold_proposals_run_day
on public.review_threshold_proposals(run_id, proposed_on_day);
create index if not exists ix_review_threshold_proposals_reporter_at
on public.review_threshold_proposals(reported_by, proposed_at);

-- Approvals, rejections, reverts, expiries, reconfirmations and checking-period results.
-- `proposal_id` and `ends_approval_id` are unique so a proposal is decided once and an approval
-- ended once, whichever concurrent writer wins.
create table if not exists public.review_threshold_decisions (
  decision_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  kind varchar(30) not null,
  proposal_id varchar(64) references public.review_threshold_proposals(proposal_id),
  ends_approval_id varchar(64) references public.review_threshold_decisions(decision_id),
  affects_decision_id varchar(64) references public.review_threshold_decisions(decision_id),
  revert_trigger varchar(30),
  previous_severity_pct integer not null,
  previous_persistence_days integer not null,
  severity_pct integer,
  persistence_days integer,
  decided_by varchar(120) not null,
  rejection_reason varchar(40),
  note text,
  cause_confirmed boolean,
  replay_json json,
  trigger_case_id varchar(64) references public.review_cases(case_id),
  trigger_review_id varchar(64) references public.case_reviews(review_id),
  decided_on_day date not null,
  effective_from_day date not null,
  decided_at timestamptz not null,
  constraint uq_review_threshold_decisions_proposal unique (proposal_id),
  constraint uq_review_threshold_decisions_ends_approval unique (ends_approval_id)
);
create index if not exists ix_review_threshold_decisions_run_id
on public.review_threshold_decisions(run_id);
create index if not exists ix_review_threshold_decisions_person_id
on public.review_threshold_decisions(person_id);
create index if not exists ix_review_threshold_decisions_run_effective
on public.review_threshold_decisions(run_id, effective_from_day);

-- Append-only, the same trigger the other evidence tables carry. Guarded because the Alembic
-- migration installs the same triggers when it runs first on this database.
do $$
declare
  t text;
begin
  foreach t in array array['review_threshold_proposals', 'review_threshold_decisions']
  loop
    if not exists (
      select 1 from pg_trigger where tgname = t || '_append_only'
    ) then
      execute format(
        'create trigger %I before update or delete on public.%I for each row '
        'execute function reject_silverloop_evidence_mutation()',
        t || '_append_only', t
      );
    end if;
  end loop;
end
$$;

-- Match the RLS posture of every other table in this directory: enable RLS and deny the Data
-- API roles explicitly. Deliberately NOT `force row level security` -- FastAPI connects as the
-- table owner, which must retain its RLS bypass in order to read and write these tables.
do $$
declare
  t text;
begin
  foreach t in array array['review_threshold_proposals', 'review_threshold_decisions']
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
set version_num = '485506d5a415'
where version_num = 'd8b1e4f70c2a';
