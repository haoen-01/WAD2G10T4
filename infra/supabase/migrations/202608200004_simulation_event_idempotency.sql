create table public.simulation_events (
  simulation_event_id varchar(64) primary key,
  client_event_id varchar(96) not null,
  run_id varchar(64) not null references public.scenario_runs(run_id),
  event_name varchar(80) not null,
  response_json json not null,
  recorded_at timestamptz not null,
  constraint uq_simulation_event_run_client unique (run_id, client_event_id)
);

create index ix_simulation_events_run_id on public.simulation_events(run_id);
create index ix_simulation_events_run_recorded
on public.simulation_events(run_id, recorded_at);

create trigger simulation_events_append_only
before update or delete on public.simulation_events
for each row execute function public.reject_silverloop_evidence_mutation();

alter table public.simulation_events enable row level security;
revoke all on public.simulation_events from anon, authenticated;
create policy deny_browser_access on public.simulation_events
for all to anon, authenticated using (false) with check (false);

update public.alembic_version
set version_num = 'b6f42a71e903'
where version_num = '9f1a6c02d4e8';
