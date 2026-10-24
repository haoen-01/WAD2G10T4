# Care+ glossary

Terms used across the product, the API and the docs. Definitions only; design lives in `docs/adr/` and
`docs/architecture.md`.

## The daily loop

**Baseline.** A senior's own usual activity, worked out from their recent daily metrics (median and
spread over a 28-day window). Care+ compares each day against this person's baseline, never a
population average.

**Valid-wear day.** A day the wearable was worn for at least 8 hours. Days below that are treated as
unusable data, not as a quiet day.

**Decision.** What Care+ chose to do about a day, from a fixed, deterministic ladder in `policy.py`:
`suppress`, `no_action`, `gentle_nudge`, `programme_suggestion` or `coordinator_review`. The least
intrusive permitted action wins. `no_action` is a recorded result, not a skipped step.

**Gate.** One rule in that ladder, checked in order: consent, data quality, confidence, rain context,
severity and persistence, then the weekly contact cap. A gate can only hold Care+ back; no learner or
language model can open one.

**Suggestion (intervention).** The message a senior sees on the Senior screen when the decision is a
nudge or a programme suggestion.

**Outcome.** How the senior answered a suggestion: _accepted_ ("show me more", not proof it helped),
_declined_, _deferred_ ("maybe later") or _no response_. Outcomes adapt which permitted suggestion is
offered next; they never change what is permitted.

**Contact cap.** The limit on how many suggestions a senior is sent in a week. After a senior accepts
one, they also get 3 days of quiet.

**Rain context.** Live weather that can explain a quiet day, so Care+ waits instead of nudging.

**Synthetic data.** Every activity figure in the demo is generated, and labelled as such. No real
wearable is connected.

## Family

**Care group.** The family members caring for one senior.

**Senior-link PIN.** A 6-digit PIN the senior shows on their own screen. It lasts 10 minutes and works
once. A family member who enters it creates the senior's care group; showing it is the senior's
agreement to be linked.

**Join PIN.** A 6-digit PIN any active member can show. It lasts 7 days and can be reused. Someone who
enters it waits as _pending_ until an active member approves them.

**Appointment.** An entry on the senior's shared calendar, saved by the API.

**Availability.** When a family member can help, saved by the API.

**Helper.** A family member who has taken an appointment. An appointment with nobody taking it
_needs a helper_.

**Activity feed.** What family members did in the care group, newest first: appointments added or
changed, who took one, free times shared, check-ins. Only active group members see it; the senior
does not.

**Check-in.** A family member telling the group they called, visited or messaged the senior, with an
optional note. Care+ sends nothing and contacts no one.

**Task.** A one-off, daily or weekly reminder on Home and Senior. Tasks are kept in the browser only;
see `docs/tasks.md`.

## Backend only (no screen)

These exist in the API and its tests but no current screen shows them.

**Review setting.** How far below a senior's own baseline, and for how many low valid-wear days,
before Care+ asks a coordinator to review. It starts at 40% for 3 days and moves only within fixed
bounds, with a coordinator's approval. A drop of 60% or more for 3 low days (the _absolute floor_)
always asks a human, whatever the setting.

**Review case.** What a `coordinator_review` decision opens for a human to look at.
