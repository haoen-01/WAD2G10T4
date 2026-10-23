-- SilverLoop durable schema for the Supabase-hosted PostgreSQL option.
-- The browser has no direct table access: FastAPI owns all domain reads and writes.

create table public.people (
  person_id varchar(64) primary key,
  display_name varchar(160) not null,
  preferred_language varchar(120) not null,
  created_at timestamptz not null
);

create table public.programmes (
  programme_id varchar(80) primary key,
  name varchar(240) not null,
  venue varchar(240) not null,
  distance_km double precision not null,
  next_session timestamptz not null,
  accessibility_json json not null,
  evidence_source varchar(120) not null,
  valid_until timestamptz not null
);

create table public.scenario_runs (
  run_id varchar(64) primary key,
  person_id varchar(64) not null references public.people(person_id),
  seed integer not null,
  scenario_version varchar(40) not null,
  current_day date not null,
  active boolean not null,
  started_at timestamptz not null,
  ended_at timestamptz
);
create index ix_scenario_runs_active on public.scenario_runs(active);
create index ix_scenario_runs_person_id on public.scenario_runs(person_id);

create table public.audit_events (
  event_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) references public.people(person_id),
  event_type varchar(80) not null,
  actor varchar(120) not null,
  decision varchar(48),
  detail_json json not null,
  recorded_at timestamptz not null
);
create index ix_audit_events_person_id on public.audit_events(person_id);
create index ix_audit_events_run_id on public.audit_events(run_id);
create index ix_audit_run_recorded on public.audit_events(run_id, recorded_at);

create table public.consent_evidence (
  evidence_id varchar(96) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  active boolean not null,
  reason varchar(240) not null,
  actor varchar(80) not null,
  source varchar(80) not null,
  recorded_at timestamptz not null
);
create index ix_consent_evidence_person_id on public.consent_evidence(person_id);
create index ix_consent_evidence_run_id on public.consent_evidence(run_id);
create index ix_consent_person_recorded on public.consent_evidence(person_id, recorded_at);

create table public.daily_metrics (
  metric_id varchar(64) primary key,
  evidence_id varchar(96) not null unique,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  day date not null,
  observed_at timestamptz not null,
  steps integer not null,
  active_minutes integer not null,
  sleep_hours double precision,
  wear_hours double precision not null,
  source varchar(80) not null,
  fixture_classification varchar(40) not null,
  context_json json not null,
  recorded_at timestamptz not null,
  constraint uq_daily_metrics_run_day unique (run_id, day)
);
create index ix_daily_metrics_person_id on public.daily_metrics(person_id);
create index ix_daily_metrics_run_day on public.daily_metrics(run_id, day);
create index ix_daily_metrics_run_id on public.daily_metrics(run_id);

create table public.decision_evidence (
  evidence_id varchar(96) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  observed_at timestamptz not null,
  recorded_at timestamptz not null,
  source varchar(80) not null,
  fixture_classification varchar(40) not null,
  confidence double precision not null,
  policy_version varchar(40) not null,
  decision varchar(48) not null,
  reasons_json json not null,
  input_event varchar(80) not null,
  quality_evidence_id varchar(96) not null
);
create index ix_decision_evidence_person_id on public.decision_evidence(person_id);
create index ix_decision_evidence_run_id on public.decision_evidence(run_id);
create index ix_decision_person_observed on public.decision_evidence(person_id, observed_at);
create index ix_decision_run_recorded on public.decision_evidence(run_id, recorded_at);

create table public.interventions (
  intervention_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  decision_evidence_id varchar(96) not null references public.decision_evidence(evidence_id),
  decision varchar(48) not null,
  title varchar(240) not null,
  message text not null,
  created_at timestamptz not null,
  status varchar(40) not null,
  evidence_json json not null
);
create index ix_interventions_decision_evidence_id on public.interventions(decision_evidence_id);
create index ix_interventions_person_id on public.interventions(person_id);
create index ix_interventions_run_created on public.interventions(run_id, created_at);
create index ix_interventions_run_id on public.interventions(run_id);

create table public.review_cases (
  case_id varchar(64) primary key,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  person_id varchar(64) not null references public.people(person_id),
  decision_evidence_id varchar(96) not null references public.decision_evidence(evidence_id),
  title varchar(240) not null,
  status varchar(40) not null,
  priority integer not null,
  opened_at timestamptz not null,
  summary text not null,
  evidence_json json not null,
  recommendation text not null
);
create index ix_review_cases_decision_evidence_id on public.review_cases(decision_evidence_id);
create index ix_review_cases_person_id on public.review_cases(person_id);
create index ix_review_cases_run_id on public.review_cases(run_id);
create index ix_review_cases_run_status on public.review_cases(run_id, status);

create table public.case_reviews (
  review_id varchar(64) primary key,
  case_id varchar(64) not null references public.review_cases(case_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  status varchar(40) not null,
  reviewer varchar(120) not null,
  note text not null,
  recorded_at timestamptz not null
);
create index ix_case_reviews_case_id on public.case_reviews(case_id);
create index ix_case_reviews_case_recorded on public.case_reviews(case_id, recorded_at);
create index ix_case_reviews_run_id on public.case_reviews(run_id);

create table public.intervention_outcomes (
  outcome_id varchar(64) primary key,
  intervention_id varchar(64) not null references public.interventions(intervention_id),
  run_id varchar(64) not null references public.scenario_runs(run_id),
  outcome varchar(48) not null,
  actor varchar(80) not null,
  reviewer varchar(120),
  recorded_at timestamptz not null
);
create index ix_intervention_outcomes_intervention_id on public.intervention_outcomes(intervention_id);
create index ix_intervention_outcomes_run_id on public.intervention_outcomes(run_id);
create index ix_outcomes_intervention_recorded on public.intervention_outcomes(intervention_id, recorded_at);

create or replace function public.reject_silverloop_evidence_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'append-only evidence cannot be changed';
end;
$$;

create trigger audit_events_append_only
before update or delete on public.audit_events
for each row execute function public.reject_silverloop_evidence_mutation();
create trigger case_reviews_append_only
before update or delete on public.case_reviews
for each row execute function public.reject_silverloop_evidence_mutation();
create trigger consent_evidence_append_only
before update or delete on public.consent_evidence
for each row execute function public.reject_silverloop_evidence_mutation();
create trigger decision_evidence_append_only
before update or delete on public.decision_evidence
for each row execute function public.reject_silverloop_evidence_mutation();
create trigger intervention_outcomes_append_only
before update or delete on public.intervention_outcomes
for each row execute function public.reject_silverloop_evidence_mutation();

create table public.alembic_version (
  version_num varchar(32) primary key
);
insert into public.alembic_version(version_num) values ('3c430fbc9737');

alter table public.people enable row level security;
alter table public.programmes enable row level security;
alter table public.scenario_runs enable row level security;
alter table public.audit_events enable row level security;
alter table public.consent_evidence enable row level security;
alter table public.daily_metrics enable row level security;
alter table public.decision_evidence enable row level security;
alter table public.interventions enable row level security;
alter table public.review_cases enable row level security;
alter table public.case_reviews enable row level security;
alter table public.intervention_outcomes enable row level security;
alter table public.alembic_version enable row level security;

revoke all on all tables in schema public from anon, authenticated;
revoke execute on function public.reject_silverloop_evidence_mutation() from public, anon, authenticated;

comment on schema public is
  'SilverLoop domain schema. Browser roles have no direct access; FastAPI is the only domain gateway.';
