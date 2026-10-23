-- Explicitly document the API-only boundary for Supabase Data API roles.
-- RLS already defaults to denial without a policy; these policies make the
-- intended denial visible to operators and database advisors.

create policy deny_browser_access on public.people
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.programmes
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.scenario_runs
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.audit_events
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.consent_evidence
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.daily_metrics
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.decision_evidence
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.interventions
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.review_cases
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.case_reviews
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.intervention_outcomes
for all to anon, authenticated using (false) with check (false);
create policy deny_browser_access on public.alembic_version
for all to anon, authenticated using (false) with check (false);
